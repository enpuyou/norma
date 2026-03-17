"""CrewAI adapter built on NormaSessionCore for tool-level governance and tracing."""

from __future__ import annotations

import time
from typing import Any, Callable

from norma.integrations.session_core import NormaSessionCore


class CrewAISession(NormaSessionCore):
    """Framework adapter for CrewAI tasks/agents.

    Usage:
        with CrewAISession(agent_id=..., contract_yaml=...) as sess:
            wrapped = sess.wrap_tool("search_docs", search_docs)
            result = wrapped("budget policy")
            sess.record_llm_call(...)
    """

    framework = "crewai"

    def wrap_tool(self, tool_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            input_text = str({"args": args, "kwargs": kwargs})[:500]
            allowed, _ = self.check_and_enforce_tool(tool_name, input_text)
            if not allowed:
                raise RuntimeError(f"[norma] CrewAI tool blocked: {tool_name}")

            span = self.start_tool_span(tool_name, input_data={"args": str(args)[:500], "kwargs": str(kwargs)[:500]})
            start = time.time()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                self.trace.end_span(span, status="error", output_data=str(exc)[:500])
                raise

            latency_ms = int((time.time() - start) * 1000)
            output_text = str(result)[:1000]
            self.end_tool_span(span, output_text=output_text, latency_ms=latency_ms)
            self.record_tool_call(tool_name, input_text=input_text, output_text=output_text, latency_ms=latency_ms)
            return result

        return _wrapped
