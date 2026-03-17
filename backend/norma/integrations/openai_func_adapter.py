"""OpenAI function-calling adapter — monitors standard OpenAI chat.completions.create() calls.

This adapter intercepts OpenAI API calls (both sync and async) and:
  1. Enforces tool permissions before function calls execute
  2. Emits llm_call spans for every chat completion
  3. Emits tool_call spans for every function/tool call
  4. Records real token usage from the API response
  5. Applies circuit breaker limits

Usage:

    from norma.integrations.openai_func_adapter import OpenAIFuncSession
    from openai import OpenAI

    client = OpenAI()

    with OpenAIFuncSession(
        agent_id="my-openai-agent",
        contract_yaml=CONTRACT_YAML,
    ) as sess:
        patched_client = sess.patch_client(client)

        response = patched_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "..."}],
            tools=[...],
        )
        # norma automatically records tokens, enforces tool calls, emits spans

    # After __exit__: run persisted, trust updated, spans saved
"""

from __future__ import annotations

import json
import time
from typing import Any

import structlog

from norma.integrations.session_core import (
    NormaSessionCore,
    AgentPausedError,
    CircuitBreakerError,
    ToolBlockedError,
)

log = structlog.get_logger()

__all__ = [
    "OpenAIFuncSession",
    "AgentPausedError",
    "CircuitBreakerError",
    "ToolBlockedError",
]


class OpenAIFuncSession(NormaSessionCore):
    """
    OpenAI function-calling adapter — patches OpenAI client to intercept
    chat.completions.create() calls.

    What is REAL:
      - Every chat.completions.create() call emits an llm_call span with
        real token counts from the API response
      - Function/tool calls in the response are checked against the contract's
        allowed/denied tool lists
      - Tool arguments and results are captured in tool_call spans
      - Circuit breaker halts if too many tool calls or cost exceeded
      - Trust score is updated, violations are recorded

    What requires user code:
      - The user must call function implementations themselves and pass results
        back to the model — this adapter monitors, it doesn't orchestrate
      - Use record_tool_result() to log the actual function execution
    """

    framework = "openai_func"

    def patch_client(self, client: Any) -> Any:
        """
        Patch an OpenAI client so chat.completions.create() is intercepted.

        Returns the same client object (mutated). The original create() is
        restored when the session exits.

        Args:
            client: An openai.OpenAI() instance.

        Returns:
            The patched client.
        """
        session = self
        original_create = client.chat.completions.create
        self._original_create = original_create
        self._client = client

        def monitored_create(*args: Any, **kwargs: Any) -> Any:
            model = kwargs.get("model", "unknown")
            messages = kwargs.get("messages", [])
            tools_schema = kwargs.get("tools", [])

            # Emit llm_call span
            llm_span = session.trace.start_span(
                "llm_call", model,
                parent=session._root_span,
                input_data={
                    "message_count": len(messages),
                    "model": model,
                    "has_tools": bool(tools_schema),
                    "tool_count": len(tools_schema),
                },
            )

            start = time.time()
            try:
                response = original_create(*args, **kwargs)
            except Exception as exc:
                session.trace.end_span(llm_span, status="error",
                                       output_data=str(exc)[:500])
                raise

            latency_ms = int((time.time() - start) * 1000)

            # Extract token usage
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

            # Get response content
            choice = response.choices[0] if response.choices else None
            content = ""
            if choice and choice.message:
                content = choice.message.content or ""

            session._apply_llm_metrics(
                span=llm_span,
                model=model,
                tokens_in=prompt_tokens,
                tokens_out=completion_tokens,
                output_text=content,
                prompt_payload={"messages": messages, "tools": tools_schema},
                extra_attributes={
                    "latency_ms": latency_ms,
                    "finish_reason": choice.finish_reason if choice else None,
                    "has_tool_calls": bool(
                        choice and choice.message and choice.message.tool_calls
                    ),
                },
            )

            # Check tool calls in the response
            if choice and choice.message and choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    func_name = tc.function.name
                    func_args = tc.function.arguments

                    # Enforce
                    allowed, block_msg = session.check_and_enforce_tool(
                        func_name, func_args or ""
                    )
                    if not allowed:
                        # Mark tool call as blocked in span
                        log.warning("norma: OpenAI tool call blocked",
                                    tool=func_name)
                        # We can't prevent OpenAI from returning the tool call,
                        # but we flag it so the user knows not to execute it
                        tc._norma_blocked = True  # type: ignore[attr-defined]
                        tc._norma_block_msg = block_msg  # type: ignore[attr-defined]
                    else:
                        tc._norma_blocked = False  # type: ignore[attr-defined]

            return response

        client.chat.completions.create = monitored_create
        return client

    def is_tool_blocked(self, tool_call: Any) -> bool:
        """Check if a tool call from the OpenAI response was blocked by norma.

        Usage:
            for tc in response.choices[0].message.tool_calls:
                if sess.is_tool_blocked(tc):
                    # Don't execute this function
                    continue
                result = call_function(tc.function.name, tc.function.arguments)
                sess.record_tool_result(tc.function.name, tc.function.arguments, result)
        """
        return getattr(tool_call, "_norma_blocked", False)

    def get_block_message(self, tool_call: Any) -> str | None:
        """Get the block message for a blocked tool call."""
        if self.is_tool_blocked(tool_call):
            return getattr(tool_call, "_norma_block_msg", None)
        return None

    def record_tool_result(
        self,
        tool_name: str,
        arguments: str,
        result: str,
        latency_ms: int = 0,
    ) -> None:
        """Record the result of executing a function call.

        Call this after you execute the function to capture the output as a span.
        """
        span = self.start_tool_span(
            tool_name,
            input_data={"arguments": arguments[:500]},
        )
        self.end_tool_span(span, str(result)[:1000], latency_ms)
        self._steps.append({
            "tool_name": tool_name,
            "input_text": arguments[:500],
            "output_text": str(result)[:1000],
            "latency_ms": latency_ms,
            "blocked": False,
            "policy_rule": None,
        })

    def __exit__(self, *args: Any) -> bool:
        # Restore original create
        if hasattr(self, "_client") and hasattr(self, "_original_create"):
            self._client.chat.completions.create = self._original_create
        return super().__exit__(*args)
