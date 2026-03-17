"""
norma.track() — one-line opt-in to start monitoring any existing LangGraph agent.

Usage:

    # 1. Wrap an existing graph (returns NormaMiddleware, drop-in replacement)
    from norma.integrations import track
    graph = track(my_langgraph_graph, agent_id="support-agent")
    result = graph.invoke(inputs)  # same API, now monitored

    # 2. Manual session (run-level tracking without wrapping the graph)
    from norma.integrations import session
    with session(agent_id="support-agent") as s:
        result = my_graph.invoke(inputs)
        s.record_quality(score=0.92)
        s.record_tokens(input=1200, output=340)

    # 3. Auto-generate a contract from config, then track
    from norma.integrations import track
    graph = track(
        my_graph,
        agent_id="support-agent",
        tools=["kb_search", "ticket_read"],
        description="L1 support triage agent",
        auto_contract=True,  # generates a draft contract, requires human approval before enforcement
    )
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Generator

from norma.middleware.langgraph_hooks import NormaMiddleware


# ────────────────────────────────────────────────────────────────────────────
# track() — wrap any graph with norma monitoring
# ────────────────────────────────────────────────────────────────────────────

def track(
    graph: Any,
    *,
    agent_id: str,
    contract_yaml: str | None = None,
    tools: list[str] | None = None,
    description: str | None = None,
    auto_contract: bool = False,
    db_url: str | None = None,
) -> NormaMiddleware:
    """
    Wrap an existing LangGraph graph with norma.ai monitoring.

    The returned object has the same .invoke() / .ainvoke() interface as the
    original graph. Drop it in place of the original with no other changes.

    Args:
        graph:          Your existing LangGraph StateGraph or CompiledGraph.
        agent_id:       Unique identifier for this agent (snake_case string).
        contract_yaml:  YAML contract to enforce. If None and auto_contract=True,
                        a draft is generated and enforcement is disabled until a
                        human approves via the norma dashboard or `norma-import`.
        tools:          List of tool names the agent uses (used for auto-contract).
        description:    Plain-English description (used for auto-contract).
        auto_contract:  Generate a contract proposal from tools + description.
                        Enforcement is OFF until the proposal is approved.
        db_url:         Override the DATABASE_URL for this agent's telemetry.

    Returns:
        NormaMiddleware — drop-in replacement for `graph`.

    Notes:
        - If no contract is provided and auto_contract=False, norma tracks
          telemetry (tokens, cost, latency) but enforcement is disabled.
        - Contract auto-generation requires OPENAI_API_KEY if you want the
          LLM to infer fields. Without a key, a conservative stub contract
          is generated as the starting point.
    """
    if auto_contract and contract_yaml is None:
        contract_yaml = _stub_contract(agent_id, tools or [], description or agent_id)

    return NormaMiddleware(
        graph=graph,
        agent_id=agent_id,
        contract_yaml=contract_yaml or "",
        db_url=db_url,
    )


# ────────────────────────────────────────────────────────────────────────────
# session() — manual run-level tracking context manager
# ────────────────────────────────────────────────────────────────────────────

@contextmanager
def session(
    agent_id: str,
    *,
    contract_yaml: str | None = None,
    db_url: str | None = None,
) -> Generator[Any, None, None]:
    """
    Context manager for manually tracking a single agent run and persisting it.

    with norma.session("my-agent") as s:
        result = my_graph.invoke(inputs)
        s.record_quality(score=0.91)
        s.record_tokens(input=1200, output=340)

    This now flushes to the DB on exit (same persistence path as dashboard runs).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _SyncSession

    from norma.config import get_settings
    from norma.integrations.session import NormaAgentSession
    from norma.models.contract import Contract

    resolved_db_url = (db_url or get_settings().database_url).replace("+aiosqlite", "")

    resolved_contract_yaml = contract_yaml
    if not resolved_contract_yaml:
        engine = create_engine(resolved_db_url, echo=False)
        try:
            with _SyncSession(engine) as s:
                active = (
                    s.query(Contract)
                    .filter(Contract.agent_id == agent_id, Contract.is_active == True)  # noqa: E712
                    .order_by(Contract.id.desc())
                    .first()
                )
                if active:
                    resolved_contract_yaml = active.yaml_content
                else:
                    latest = (
                        s.query(Contract)
                        .filter(Contract.agent_id == agent_id)
                        .order_by(Contract.id.desc())
                        .first()
                    )
                    resolved_contract_yaml = latest.yaml_content if latest else None
        finally:
            engine.dispose()

    if not resolved_contract_yaml:
        resolved_contract_yaml = _stub_contract(agent_id, tools=[], description=f"External run for {agent_id}")

    with NormaAgentSession(
        agent_id=agent_id,
        contract_yaml=resolved_contract_yaml,
        contract_version="external",
        db_url=resolved_db_url,
        initiated_by="external",
    ) as sess:
        yield sess


class RunSession:
    """Backward-compatible alias type for legacy imports.

    Use `session(...)` as the runtime entrypoint.
    """


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _stub_contract(agent_id: str, tools: list[str], description: str) -> str:
    """
    Generate a minimal conservative contract stub without an LLM call.
    All tools are in the allow list; deny list is empty (human fills it during review).
    Enforcement is disabled until a human approves via the dashboard.
    """
    import yaml
    contract = {
        "agent_id": agent_id,
        "version": "1.0",
        "tier": "restricted",
        "_generated_by": "norma auto-contract (stub — awaiting human review)",
        "_enforcement": "DISABLED until approved",
        "scope": {
            "description": description,
        },
        "authorities": {
            "tools": {"allow": tools, "deny": []},
            "data":  {"allow": ["**"], "deny": []},
        },
        "output_constraints": {
            "deny_patterns": ["credit_card_regex", "ssn_regex"],
        },
        "sla": {
            "max_cost_per_run": 5.00,
            "max_latency_seconds": 60,
            "min_quality_score": 0.70,
        },
        "trust": {
            "initial_score": 0.40,
            "violation_penalty": 0.25,
            "clean_run_increment": 0.025,
            "tier_thresholds": {
                "standard": {"min_score": 0.65, "min_clean_runs": 10},
                "trusted":  {"min_score": 0.82, "min_clean_runs": 20},
            },
        },
    }
    return yaml.dump(contract, default_flow_style=False)
