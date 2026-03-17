"""NormaAgentSession — LangChain/LangGraph adapter for norma agent monitoring.

This extends NormaSessionCore with LangChain-specific tool wrapping:
  - wrap_tools() monkey-patches LangChain BaseTool._run with enforcement
  - Works with LangChain, LangGraph, and any framework using BaseTool

This is the original norma session class — all existing code that imports
NormaAgentSession continues to work unchanged.

Usage:

    from norma.integrations.session import NormaAgentSession

    with NormaAgentSession(
        agent_id="financial-reader-v1",
        contract_yaml=CONTRACT_YAML,
    ) as sess:
        tools = sess.wrap_tools([list_reports, read_report, read_confidential])
        output = tools[1].run("q4_2025_earnings")
        sess.record_quality(0.92)
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from langchain_core.tools import BaseTool

from norma.integrations.session_core import (
    NormaSessionCore,
    ToolBlockedError,
    AgentPausedError,
    CircuitBreakerError,
)

log = structlog.get_logger()

# Re-export exceptions at the old import path for backward compatibility
__all__ = [
    "NormaAgentSession",
    "ToolBlockedError",
    "AgentPausedError",
    "CircuitBreakerError",
]


class NormaAgentSession(NormaSessionCore):
    """
    LangChain/LangGraph adapter — wraps BaseTool instances with enforcement.

    This is the original norma session class.  All existing imports,
    tests, and agents continue working without changes.
    """

    framework = "langchain"

    # ── LangChain-specific API ─────────────────────────────────────────────────

    def wrap_tools(self, tools: list[BaseTool]) -> list[BaseTool]:
        """
        Wrap each LangChain tool so norma.enforce() runs before execution.

        If enforcement blocks the tool:
          - the tool returns a BLOCKED message string (does not raise)
          - the blocked flag is set on this session
          - the violation is queued for DB persistence at session end
        """
        return [self._wrap_one(tool) for tool in tools]

    def _wrap_one(self, tool: BaseTool) -> BaseTool:
        """Monkey-patch _run on a single tool with enforcement + tracing."""
        session = self
        original_run = tool._run

        def enforced_run(*args: Any, config: Any = None, **kwargs: Any) -> str:
            # Extract the first string arg as the potential data path
            _kw_vals = [v for k, v in kwargs.items() if k != "config"]
            raw_input = str(args[0]) if args else str(_kw_vals[0]) if _kw_vals else ""

            # Pre-flight: circuit breaker + enforcement
            allowed, block_msg = session.check_and_enforce_tool(tool.name, raw_input)
            if not allowed:
                return block_msg  # type: ignore[return-value]

            # Start tool call span
            tool_span = session.start_tool_span(
                tool.name,
                input_data={"args": raw_input[:500]},
            )

            log.debug("norma: tool call allowed", tool=tool.name)
            _step_start = time.time()
            try:
                result = original_run(*args, config=config, **kwargs)  # type: ignore[arg-type]
            except TypeError:
                result = original_run(*args, **kwargs)  # type: ignore[arg-type]
            _step_latency = int((time.time() - _step_start) * 1000)

            # Record
            output_str = str(result) if result else ""
            session._steps.append({
                "tool_name": tool.name,
                "input_text": raw_input[:500],
                "output_text": output_str[:1000],
                "latency_ms": _step_latency,
                "blocked": False,
                "policy_rule": None,
            })
            session.end_tool_span(tool_span, output_str, _step_latency)

            return result

        tool._run = enforced_run  # type: ignore[method-assign]
        return tool
