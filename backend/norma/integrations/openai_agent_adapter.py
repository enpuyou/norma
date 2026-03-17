"""OpenAI Agents SDK adapter — monitors Agent runs via RunHooks.

This adapter hooks into the OpenAI Agents SDK's lifecycle events to:
  1. Emit llm_call spans for every model invocation with real token counts
  2. Emit tool_call spans for every function tool execution
  3. Enforce tool permissions — blocked tools raise ToolBlockedError
  4. Emit agent_start / agent_end / handoff spans for multi-agent flows
  5. Apply circuit breaker limits
  6. Record full telemetry (tokens, cost, latency, quality)

Usage:

    from agents import Agent, Runner, function_tool
    from norma.integrations.openai_agent_adapter import OpenAIAgentSession

    @function_tool
    def lookup_data(query: str) -> str:
        return "..."

    agent = Agent(name="my-agent", tools=[lookup_data])

    with OpenAIAgentSession(
        agent_id="my-openai-agent",
        contract_yaml=CONTRACT_YAML,
    ) as sess:
        result = await Runner.run(agent, "Summarize Q2 earnings",
                                  hooks=sess.get_hooks())

    # After __exit__: run persisted, trust updated, spans saved
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from norma.integrations.session_core import (
    NormaSessionCore,
    AgentPausedError,
    CircuitBreakerError,
    ToolBlockedError,
)
from norma.core.trace import SpanData

log = structlog.get_logger()

__all__ = [
    "OpenAIAgentSession",
    "AgentPausedError",
    "CircuitBreakerError",
    "ToolBlockedError",
]


class OpenAIAgentSession(NormaSessionCore):
    """
    OpenAI Agents SDK adapter — provides RunHooks that emit spans and
    enforce tool permissions through the SDK's hook lifecycle.

    What is REAL:
      - Every LLM call emits an llm_call span with real token counts from
        the ModelResponse.usage object
      - Every tool invocation emits a tool_call span with name, result, latency
      - Tools are checked against the contract's allowed/denied lists
      - Agent start/end and handoff events are captured as spans
      - Circuit breaker halts if too many tool calls or cost exceeded
      - Trust score is updated, violations are recorded

    How it works:
      - Call sess.get_hooks() and pass the result to Runner.run(hooks=...)
      - The SDK calls our hooks at each lifecycle point
      - on_tool_start checks enforcement; raises ToolBlockedError if denied
    """

    framework = "openai_agents"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Track open spans keyed by (agent_name, span_type) for pairing start/end
        self._agent_spans: dict[str, SpanData] = {}
        self._llm_spans: dict[str, SpanData] = {}
        self._tool_spans: dict[str, SpanData] = {}
        self._tool_start_times: dict[str, float] = {}
        self._hooks: Any = None

    def get_hooks(self) -> Any:
        """Return a RunHooks instance wired to this session.

        Pass this to Runner.run(hooks=...) to enable norma monitoring.

        Returns:
            A RunHooks subclass instance that emits spans and enforces
            tool permissions through this session.
        """
        if self._hooks is None:
            self._hooks = self._create_hooks()
        return self._hooks

    def _create_hooks(self) -> Any:
        """Create the RunHooks subclass dynamically.

        We import agents here so the module can be imported even if
        openai-agents is not installed (graceful degradation).

        Handles the case where a project-local `agents/` directory shadows
        the `openai-agents` package by detecting the conflict and temporarily
        swapping sys.modules to import from the correct package.
        """
        import importlib
        import importlib.util
        import sys
        from pathlib import Path

        def _import_run_hooks():
            """Import RunHooks from the openai-agents package, handling shadowing."""
            # Check if 'agents' is already imported and is the correct package
            agents_mod = sys.modules.get("agents")
            if agents_mod and hasattr(agents_mod, "RunHooks"):
                return agents_mod.RunHooks

            # If agents_mod exists but doesn't have RunHooks, it's the wrong module
            if agents_mod and not hasattr(agents_mod, "RunHooks"):
                # Save and clear all agents.* entries
                stale = {}
                for k in list(sys.modules.keys()):
                    if k == "agents" or k.startswith("agents."):
                        stale[k] = sys.modules.pop(k)

                # Also temporarily remove the project root from sys.path
                project_root = str(
                    Path(__file__).resolve().parent.parent.parent.parent
                )
                path_removed = False
                if project_root in sys.path:
                    sys.path.remove(project_root)
                    path_removed = True

                try:
                    # Now import should find the site-packages version
                    from agents import RunHooks as _RH

                    # Cache the real agents module for future calls
                    real_agents = sys.modules["agents"]

                    # Restore project agents back, but keep the real SDK accessible
                    # via a private key
                    sys.modules["_norma_openai_agents_sdk"] = real_agents

                    # Remove the real agents entries and restore stale ones
                    for k in list(sys.modules.keys()):
                        if k == "agents" or k.startswith("agents."):
                            sys.modules.pop(k, None)
                    sys.modules.update(stale)

                    return _RH
                except ImportError:
                    # Restore everything and fail
                    sys.modules.update(stale)
                    raise
                finally:
                    if path_removed:
                        sys.path.insert(0, project_root)

            # No conflict — try normal import
            from agents import RunHooks
            return RunHooks

        try:
            RunHooks = _import_run_hooks()
        except ImportError:
            raise ImportError(
                "openai-agents package is required for OpenAIAgentSession. "
                "Install it with: poetry add openai-agents"
            )

        session = self

        class NormaRunHooks(RunHooks):  # type: ignore[type-arg]
            """RunHooks implementation that emits norma spans and enforces policy."""

            # ── Agent lifecycle ────────────────────────────────────────────

            async def on_agent_start(
                self, context: Any, agent: Any,
            ) -> None:
                agent_name = getattr(agent, "name", "unknown")
                span = session.trace.start_span(
                    "agent_start", agent_name,
                    parent=session._root_span,
                    input_data={"agent_name": agent_name},
                )
                session._agent_spans[agent_name] = span

            async def on_agent_end(
                self, context: Any, agent: Any, output: Any,
            ) -> None:
                agent_name = getattr(agent, "name", "unknown")
                span = session._agent_spans.pop(agent_name, None)
                if span:
                    output_str = str(output)[:1000] if output else None
                    session.trace.end_span(
                        span,
                        output_data=output_str,
                        status="ok",
                    )

            async def on_handoff(
                self, context: Any, from_agent: Any, to_agent: Any,
            ) -> None:
                from_name = getattr(from_agent, "name", "unknown")
                to_name = getattr(to_agent, "name", "unknown")
                span = session.trace.start_span(
                    "handoff", f"{from_name}->{to_name}",
                    parent=session._root_span,
                    input_data={
                        "from_agent": from_name,
                        "to_agent": to_name,
                    },
                )
                session.trace.end_span(span, status="ok")

            # ── LLM lifecycle ─────────────────────────────────────────────

            async def on_llm_start(
                self, context: Any, agent: Any,
                system_prompt: Any, input_items: Any,
            ) -> None:
                agent_name = getattr(agent, "name", "unknown")
                model = getattr(agent, "model", None) or "unknown"
                # Count input items for context
                item_count = len(input_items) if input_items else 0
                span = session.trace.start_span(
                    "llm_call", str(model),
                    parent=session._root_span,
                    input_data={
                        "agent": agent_name,
                        "model": str(model),
                        "input_items": item_count,
                        "has_system_prompt": system_prompt is not None,
                    },
                )
                span.attributes["prompt_hash"] = session._prompt_hash(
                    {
                        "system_prompt": str(system_prompt) if system_prompt is not None else "",
                        "input_items": input_items,
                        "agent": agent_name,
                    }
                )
                session._llm_spans[agent_name] = span

            async def on_llm_end(
                self, context: Any, agent: Any, response: Any,
            ) -> None:
                agent_name = getattr(agent, "name", "unknown")
                span = session._llm_spans.pop(agent_name, None)

                # Extract token usage from ModelResponse.usage
                usage = getattr(response, "usage", None)
                tokens_in = getattr(usage, "input_tokens", 0) if usage else 0
                tokens_out = getattr(usage, "output_tokens", 0) if usage else 0
                # Extract response metadata
                response_id = getattr(response, "response_id", None)
                output_items = getattr(response, "output", [])
                output_count = len(output_items) if output_items else 0
                output_text = ""
                if output_items:
                    output_text = str(output_items)[:1000]

                if span:
                    session._apply_llm_metrics(
                        span=span,
                        model=str(getattr(agent, "model", None) or "unknown"),
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        output_text=output_text,
                        extra_attributes={
                            "response_id": response_id,
                            "output_item_count": output_count,
                            "status": "ok",
                        },
                    )

            # ── Tool lifecycle ────────────────────────────────────────────

            async def on_tool_start(
                self, context: Any, agent: Any, tool: Any,
            ) -> None:
                tool_name = getattr(tool, "name", str(type(tool).__name__))

                # Enforce tool permissions
                allowed, block_msg = session.check_and_enforce_tool(
                    tool_name, ""
                )
                if not allowed:
                    log.warning(
                        "norma: OpenAI Agents SDK tool blocked",
                        tool=tool_name,
                        agent=getattr(agent, "name", "unknown"),
                    )
                    raise ToolBlockedError(session.enforce_tool(tool_name))

                # Start a tool span
                span = session.start_tool_span(
                    tool_name,
                    input_data={
                        "agent": getattr(agent, "name", "unknown"),
                        "tool_type": type(tool).__name__,
                    },
                )
                session._tool_spans[tool_name] = span
                session._tool_start_times[tool_name] = time.time()

            async def on_tool_end(
                self, context: Any, agent: Any, tool: Any, result: str,
            ) -> None:
                tool_name = getattr(tool, "name", str(type(tool).__name__))
                span = session._tool_spans.pop(tool_name, None)
                start_time = session._tool_start_times.pop(tool_name, None)

                latency_ms = (
                    int((time.time() - start_time) * 1000)
                    if start_time else 0
                )

                if span:
                    session.end_tool_span(span, str(result)[:1000], latency_ms)

                # Record step for backward compat
                session._steps.append({
                    "tool_name": tool_name,
                    "input_text": "",  # SDK doesn't expose tool args in hooks
                    "output_text": str(result)[:1000],
                    "latency_ms": latency_ms,
                    "blocked": False,
                    "policy_rule": None,
                })

        return NormaRunHooks()
