"""Scenario test — Span tracing, circuit breaker, and agent pause.

Exercises the Phase 1 trace infrastructure end-to-end:
  S1. Normal runs emit a span tree (root → enforcement → tool_call spans)
  S2. Blocked tool calls emit blocked enforcement spans
  S3. Circuit breaker trips when max_tool_calls is exceeded
  S4. Paused agents (enabled=False) are rejected with AgentPausedError
  S5. Span API returns flat + tree views

All tests use real contract YAML, real LangChain tools, real enforcement.
No LLM is invoked — token counts are 0 (correct for scripted runs).
"""

from __future__ import annotations

import yaml
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from langchain_core.tools import tool as langchain_tool

from norma.integrations.session import (
    NormaAgentSession,
    AgentPausedError,
    CircuitBreakerError,
)
from norma.models.agent import Agent
from norma.models.run import Run
from norma.models.span import Span


# ── Fixtures ───────────────────────────────────────────────────────────────────

CONTRACT_YAML = yaml.dump({
    "agent_id": "trace-test-agent",
    "authorities": {
        "tools": {
            "allow": ["list_reports", "read_report"],
            "deny": ["read_confidential"],
        },
        "data": {
            "allow": ["reports/public/*"],
            "deny": ["reports/confidential/*"],
        },
    },
    "sla": {
        "max_latency_ms": 5000,
        "max_cost_per_run": 1.00,
        "max_tool_calls_per_run": 3,  # low limit for circuit breaker test
    },
    "trust": {
        "clean_run_increment": 0.025,
        "violation_penalty": 0.25,
        "tier_thresholds": {
            "standard": {"min_score": 0.65, "min_clean_runs": 10},
            "trusted": {"min_score": 0.82, "min_clean_runs": 20},
        },
    },
})


@langchain_tool
def list_reports() -> str:
    """List available reports."""
    return "q2_2025_earnings.txt, q3_2025_earnings.txt, q4_2025_earnings.txt"


@langchain_tool
def read_report(filename: str) -> str:
    """Read a public report by filename."""
    return f"Revenue for {filename}: $42.5B (+8% YoY)"


@langchain_tool
def read_confidential(filename: str) -> str:
    """Read a confidential report — should be blocked."""
    return f"CONFIDENTIAL: {filename}"


def _get_spans(db_url: str, run_id: int) -> list:
    """Helper to query spans for a given run."""
    engine = create_engine(db_url, echo=False)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        spans = db.query(Span).filter(Span.trace_id == run_id).order_by(Span.id).all()
        result = [
            {
                "span_id": s.span_id,
                "parent_span_id": s.parent_span_id,
                "span_type": s.span_type,
                "name": s.name,
                "status": s.status,
                "tokens_in": s.tokens_in,
                "tokens_out": s.tokens_out,
            }
            for s in spans
        ]
    engine.dispose()
    return result


def _get_latest_run(db_url: str) -> dict | None:
    """Helper to query the most recent run."""
    engine = create_engine(db_url, echo=False)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        run = db.query(Run).order_by(Run.id.desc()).first()
        if not run:
            return None
        result = {
            "id": run.id,
            "agent_id": run.agent_id,
            "session_id": run.session_id,
            "completion_status": run.completion_status,
        }
    engine.dispose()
    return result


# ── S1: Normal run emits span tree ────────────────────────────────────────────


def test_clean_run_emits_span_tree(scenario_db: str) -> None:
    """A clean run should produce: root session span → enforcement → tool_call."""
    with NormaAgentSession(
        agent_id="trace-test-agent",
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
        session_id="sess-001",
        check_enabled=False,
    ) as sess:
        tools = sess.wrap_tools([list_reports, read_report])
        tools[0].run({})  # list_reports
        tools[1].run("q4_2025_earnings.txt")  # read_report

    run = _get_latest_run(scenario_db)
    assert run is not None
    assert run["session_id"] == "sess-001"
    assert run["completion_status"] == "success"

    spans = _get_spans(scenario_db, run["id"])

    # Expected: 1 root session + 2 enforcement checks + 2 tool calls = 5 spans
    assert len(spans) == 5, f"Expected 5 spans, got {len(spans)}: {spans}"

    # Root span
    root = [s for s in spans if s["span_type"] == "session"]
    assert len(root) == 1
    assert root[0]["name"] == "trace-test-agent"
    assert root[0]["status"] == "ok"
    assert root[0]["parent_span_id"] is None

    # Enforcement spans
    enforcements = [s for s in spans if s["span_type"] == "enforcement_check"]
    assert len(enforcements) == 2
    for e in enforcements:
        assert e["status"] == "ok"  # allowed

    # Tool call spans
    tool_calls = [s for s in spans if s["span_type"] == "tool_call"]
    assert len(tool_calls) == 2
    assert tool_calls[0]["name"] == "list_reports"
    assert tool_calls[1]["name"] == "read_report"

    # All child spans should reference the root span
    root_span_id = root[0]["span_id"]
    for s in spans:
        if s["span_type"] != "session":
            assert s["parent_span_id"] == root_span_id


# ── S2: Blocked tool emits blocked enforcement span ───────────────────────────


def test_blocked_tool_emits_blocked_span(scenario_db: str) -> None:
    """When a denied tool is called, enforcement span should be 'blocked'."""
    with NormaAgentSession(
        agent_id="trace-test-agent",
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
        check_enabled=False,
    ) as sess:
        tools = sess.wrap_tools([read_confidential])
        output = tools[0].run("exec_compensation_2025.txt")
        assert "BLOCKED" in output

    run = _get_latest_run(scenario_db)
    assert run is not None
    assert run["completion_status"] == "failed"

    spans = _get_spans(scenario_db, run["id"])

    # Should have: root session + 1 blocked enforcement = 2 spans
    assert len(spans) == 2, f"Expected 2 spans, got {len(spans)}: {spans}"

    enforcement = [s for s in spans if s["span_type"] == "enforcement_check"]
    assert len(enforcement) == 1
    assert enforcement[0]["status"] == "blocked"


# ── S3: Circuit breaker trips on excessive tool calls ─────────────────────────


def test_circuit_breaker_trips(scenario_db: str) -> None:
    """Circuit breaker should halt execution after max_tool_calls_per_run (3)."""
    with NormaAgentSession(
        agent_id="trace-test-agent",
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
        check_enabled=False,
    ) as sess:
        tools = sess.wrap_tools([list_reports, read_report])

        # 3 calls should succeed (within limit)
        tools[0].run({})  # call 1
        tools[1].run("q2_2025_earnings.txt")  # call 2
        tools[1].run("q3_2025_earnings.txt")  # call 3

        # 4th call should be halted by circuit breaker
        output = tools[1].run("q4_2025_earnings.txt")
        assert "HALTED" in output
        assert "circuit breaker" in output.lower() or "Circuit breaker" in output

    run = _get_latest_run(scenario_db)
    assert run is not None
    assert run["completion_status"] == "failed"

    spans = _get_spans(scenario_db, run["id"])

    # Should have circuit breaker span
    cb_spans = [s for s in spans if s["span_type"] == "tool_call" and s["status"] == "blocked"]
    assert len(cb_spans) >= 1, f"Expected at least 1 circuit breaker span, got: {spans}"


# ── S4: Paused agent raises AgentPausedError ──────────────────────────────────


def test_paused_agent_rejected(scenario_db: str) -> None:
    """A paused (enabled=False) agent should be rejected before any execution."""
    # Pre-create agent as paused
    engine = create_engine(scenario_db, echo=False)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        db.add(Agent(
            agent_id="trace-test-agent",
            name="Trace Test Agent",
            type="single",
            current_tier="restricted",
            trust_score=0.40,
            enabled=False,  # PAUSED
        ))
        db.commit()
    engine.dispose()

    with pytest.raises(AgentPausedError):
        with NormaAgentSession(
            agent_id="trace-test-agent",
            contract_yaml=CONTRACT_YAML,
            db_url=scenario_db,
            check_enabled=True,
        ) as sess:
            # Should never reach here
            tools = sess.wrap_tools([list_reports])
            tools[0].run({})


# ── S5: Multiple session runs tracked by session_id ───────────────────────────


def test_session_id_grouping(scenario_db: str) -> None:
    """Multiple runs with the same session_id should be queryable together."""
    for i in range(3):
        with NormaAgentSession(
            agent_id="trace-test-agent",
            contract_yaml=CONTRACT_YAML,
            db_url=scenario_db,
            session_id="multi-turn-001",
            check_enabled=False,
        ) as sess:
            tools = sess.wrap_tools([list_reports])
            tools[0].run({})

    # Verify all 3 runs have the same session_id
    engine = create_engine(scenario_db, echo=False)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        runs = db.query(Run).filter(Run.session_id == "multi-turn-001").all()
        assert len(runs) == 3
    engine.dispose()
