"""NormaCallbackHandler — LangChain BaseCallbackHandler for token + span tracking.

Attach this to any LangChain chain, agent, or LLM call to automatically capture
token usage, emit llm_call spans, and feed it into a NormaAgentSession.

Usage with a real LLM agent:

    from norma.middleware.langchain_callback import NormaCallbackHandler
    from norma.integrations.session import NormaAgentSession

    with NormaAgentSession(agent_id, contract_yaml) as sess:
        wrapped_tools = sess.wrap_tools(tools)
        callback = NormaCallbackHandler(sess)
        agent = create_react_agent(llm, wrapped_tools)
        agent.invoke({"input": task}, config={"callbacks": [callback]})

What this callback does:
  - on_llm_start:    opens an llm_call span in the session's TraceCollector
  - on_llm_end:      reads token_usage from the LLM response, ends the span
                     with real tokens, and calls sess.record_tokens()
  - on_agent_finish: logs the agent's return value for debugging

What it does NOT do:
  - Block tool calls (that is handled by sess.wrap_tools())
  - Create DB records (that is handled by NormaAgentSession.__exit__)
"""

from __future__ import annotations

from typing import Any, Union
from uuid import UUID

import structlog
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from norma.core.trace import SpanData
from norma.integrations.session import NormaAgentSession

log = structlog.get_logger()


class NormaCallbackHandler(BaseCallbackHandler):
    """
    LangChain callback handler that feeds real token usage into a NormaAgentSession
    and emits llm_call spans for every LLM invocation.

    Attach as a callback when calling .invoke() / .ainvoke() on any LangChain
    chain or agent executor.
    """

    raise_error = False  # never let callback errors surface to the user

    def __init__(self, session: NormaAgentSession) -> None:
        super().__init__()
        self._session = session
        self._input_tokens = 0
        self._output_tokens = 0
        # Track open spans by LangChain run_id → span
        self._open_spans: dict[UUID, SpanData] = {}

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Open an llm_call span when an LLM call starts."""
        model_name = (
            serialized.get("kwargs", {}).get("model_name")
            or serialized.get("kwargs", {}).get("model")
            or serialized.get("id", ["unknown"])[-1]
        )
        # Truncate prompts for storage
        prompt_preview = prompts[0][:500] if prompts else ""
        span = self._session.trace.start_span(
            "llm_call",
            model_name,
            parent=self._session._active_subagent_span or self._session._root_span,
            input_data={"prompt_preview": prompt_preview, "prompt_count": len(prompts)},
        )
        span.attributes["prompt_hash"] = self._session._prompt_hash(
            {"prompts": prompts, "model": model_name}
        )
        self._open_spans[run_id] = span

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Open an llm_call span when a chat model call starts."""
        model_name = (
            serialized.get("kwargs", {}).get("model_name")
            or serialized.get("kwargs", {}).get("model")
            or serialized.get("id", ["unknown"])[-1]
        )
        # Count messages
        msg_count = sum(len(batch) for batch in messages)
        span = self._session.trace.start_span(
            "llm_call",
            model_name,
            parent=self._session._active_subagent_span or self._session._root_span,
            input_data={"message_count": msg_count, "model": model_name},
        )
        span.attributes["prompt_hash"] = self._session._prompt_hash(
            {
                "messages": [
                    [getattr(m, "content", "") for m in batch]
                    for batch in messages
                ],
                "model": model_name,
            }
        )
        self._open_spans[run_id] = span

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Extract token usage from any LLM response, close the span."""
        usage: dict[str, int] = {}

        # OpenAI-style usage in llm_output
        if response.llm_output:
            usage = response.llm_output.get("token_usage", {})

        # Newer style: usage_metadata on each generation
        if not usage:
            for gen_list in response.generations:
                for gen in gen_list:
                    meta = getattr(gen, "generation_info", {}) or {}
                    if "usage" in meta:
                        usage = meta["usage"]
                        break

        # Support both OpenAI-style keys and newer provider-neutral keys
        prompt_tokens = (
            usage.get("prompt_tokens")
            or usage.get("input_tokens")
            or 0
        )
        completion_tokens = (
            usage.get("completion_tokens")
            or usage.get("output_tokens")
            or 0
        )

        # Fallback: usage metadata may live on generated message objects
        if prompt_tokens == 0 and completion_tokens == 0:
            for gen_list in response.generations:
                for gen in gen_list:
                    msg = getattr(gen, "message", None)
                    meta = getattr(msg, "usage_metadata", None) or {}
                    if isinstance(meta, dict):
                        prompt_tokens = int(meta.get("input_tokens") or meta.get("prompt_tokens") or 0)
                        completion_tokens = int(meta.get("output_tokens") or meta.get("completion_tokens") or 0)
                        if prompt_tokens or completion_tokens:
                            break
                if prompt_tokens or completion_tokens:
                    break
        self._input_tokens += prompt_tokens
        self._output_tokens += completion_tokens

        # Close the llm_call span with token data
        span = self._open_spans.pop(run_id, None)
        if span:
            # Get output preview
            output_preview = ""
            if response.generations:
                for gen_list in response.generations:
                    for gen in gen_list:
                        output_preview = gen.text[:500] if gen.text else ""
                        break
                    if output_preview:
                        break

            self._session._apply_llm_metrics(
                span=span,
                model=span.name,
                tokens_in=prompt_tokens,
                tokens_out=completion_tokens,
                output_text=output_preview,
                extra_attributes={
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            )

        # Update session cumulative tokens
        self._session.record_tokens(
            input=self._input_tokens,
            output=self._output_tokens,
        )
        log.debug(
            "norma: token usage captured",
            prompt=self._input_tokens,
            completion=self._output_tokens,
        )

    def on_llm_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Close the span with error status if the LLM call fails."""
        span = self._open_spans.pop(run_id, None)
        if span:
            self._session.trace.end_span(
                span,
                status="error",
                output_data=str(error)[:500],
            )
        log.warning("norma: LLM error observed", error=str(error)[:120])

    def on_agent_finish(self, finish: Any, *, run_id: UUID, **kwargs: Any) -> None:
        log.debug("norma: agent finished", output=str(finish.return_values)[:120])

    def on_tool_error(
        self,
        error: Union[Exception, KeyboardInterrupt],
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        log.warning("norma: tool error observed", error=str(error)[:120])
