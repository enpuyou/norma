"""NormaMiddleware — wraps a LangGraph StateGraph with norma monitoring.

Drop-in replacement for any LangGraph graph:

    from norma.middleware.langgraph_hooks import NormaMiddleware

    graph = build_my_graph()                            # your existing code
    monitored = NormaMiddleware(graph, agent_id="my-agent", contract_yaml=yaml_str)
    result = monitored.invoke({"input": "..."})         # same interface

For LangChain agents (ReAct, tool-calling etc.) use NormaAgentSession directly:

    from norma.integrations.session import NormaAgentSession
"""

from __future__ import annotations

from typing import Any

import structlog

from norma.core.quality_scorer import evaluate_quality_sync

log = structlog.get_logger()


class NormaMiddleware:
    """
    Wraps a LangGraph CompiledGraph to auto-monitor invocations.

    Each call to invoke() / ainvoke() opens a NormaAgentSession,
    runs the graph, then persists the run to DB on completion.
    Tool enforcement requires tools to be wrapped via sess.wrap_tools()
    before being passed to the graph — see norma-watch CLI for an example.
    """

    def __init__(
        self,
        graph: Any,
        agent_id: str,
        contract_yaml: str,
        contract_version: str = "1.0",
        db_url: str | None = None,
    ) -> None:
        self.graph = graph
        self.agent_id = agent_id
        self.contract_yaml = contract_yaml
        self.contract_version = contract_version
        self.db_url = db_url

    def invoke(self, inputs: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Synchronous invoke with norma monitoring."""
        from norma.integrations.session import NormaAgentSession
        from norma.middleware.langchain_callback import NormaCallbackHandler

        with NormaAgentSession(
            agent_id=self.agent_id,
            contract_yaml=self.contract_yaml,
            contract_version=self.contract_version,
            db_url=self.db_url,
        ) as sess:
            cb = NormaCallbackHandler(sess)
            existing_cbs = kwargs.pop("callbacks", []) or []
            result: dict[str, Any] = self.graph.invoke(
                inputs,
                config={"callbacks": existing_cbs + [cb]},
                **kwargs,
            )
            # Real quality scoring from output content
            output_text = str(result)
            quality_result = evaluate_quality_sync(output_text)
            sess.record_quality(quality_result.score)
            return result

    async def ainvoke(self, inputs: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Async invoke — opens a sync session in a thread executor."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.invoke(inputs, **kwargs))
