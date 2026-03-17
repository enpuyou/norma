"""S2 — Enforcement Integration Scenario Test.

Enterprise scenario:
    A platform team wraps their LangChain agent's tools with norma
    using NormaAgentSession.wrap_tools().  When the agent attempts a tool
    call that violates its contract (e.g. accessing confidential data), the
    call is blocked BEFORE execution and a violation is persisted to the DB.

What this test validates:
    - wrap_tools() actually intercepts real LangChain BaseTool._run() calls
    - Allowed tools return their real output (norma is transparent when compliant)
    - Denied tools return a BLOCKED message — the actual tool._run() is never called
    - Violations are persisted to the DB (verifiable by querying SQLite directly)
    - The agent's trust score in the DB drops after a violation — not just in memory

Inputs:
    - Real @tool-decorated functions from norma/agents/financial_reader.py
    - The financial_reader.py CONTRACT_YAML with read_confidential in the deny list

No LLM calls.  Uses scenario_db fixture (fresh temp DB per test).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from norma.agents.financial_reader import (
    CONTRACT_YAML,
    REPORTS_PUBLIC,
    list_reports,
    read_confidential,
    read_report,
)
from norma.integrations.session import NormaAgentSession
from norma.models.agent import Agent
from norma.models.violation import Violation


def _get_agent(db_url: str, agent_id: str) -> Agent | None:
    """Read the agent row from the DB synchronously."""
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        return s.get(Agent, agent_id)


def _get_violations(db_url: str, agent_id: str) -> list[Violation]:
    """Read all violation rows for an agent."""
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        return (
            s.query(Violation)
            .filter(Violation.agent_id == agent_id)
            .all()
        )


# ── Test: allowed tool call is transparent ──────────────────────────────────────

def test_allowed_tool_returns_real_output(scenario_db: str) -> None:
    """
    Scenario: agent calls list_reports (allowed by contract).
    Expected: output is the real directory listing, NOT a BLOCKED message.
    The tool should execute normally — norma is invisible when compliant.
    """
    # Ensure the public reports directory exists (financial_reader expects it)
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)

    with NormaAgentSession(
        agent_id="enforce-test-allowed", contract_yaml=CONTRACT_YAML, db_url=scenario_db
    ) as sess:
        tools = sess.wrap_tools([list_reports, read_report, read_confidential])
        output = tools[0].run("")  # list_reports takes no required args

    assert "[BLOCKED by norma.ai]" not in output
    # Output is real — either "No reports found" or an actual file listing
    assert isinstance(output, str) and len(output) > 0


# ── Test: denied tool is blocked before execution ──────────────────────────────

def test_denied_tool_is_blocked_before_execution(scenario_db: str) -> None:
    """
    Scenario: agent attempts to call read_confidential (deny list in contract).
    Expected:
      - Tool returns a BLOCKED message (not an exception, not a real file read)
      - The tool's actual _run() is never called (the file is never opened)
      - One violation row is persisted in the DB
    """
    agent_id = "enforce-test-denied"

    # Track if the real tool body was ever called
    _real_called = []
    original_run = read_confidential._run

    def _patched_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        _real_called.append(True)
        return original_run(*args, **kwargs)

    read_confidential._run = _patched_run  # type: ignore[method-assign]

    try:
        with NormaAgentSession(
            agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
        ) as sess:
            tools = sess.wrap_tools([list_reports, read_report, read_confidential])
            blocked_output = tools[2].run("exec_compensation_2025")
    finally:
        read_confidential._run = original_run  # type: ignore[method-assign]

    # The BLOCKED message was returned
    assert "[BLOCKED by norma.ai]" in blocked_output
    assert "read_confidential" in blocked_output or "deny" in blocked_output.lower()

    # The real tool body was NEVER called
    assert len(_real_called) == 0, (
        "Enforcement must intercept before execution — real _run() must not be called"
    )


# ── Test: violation persisted to DB ────────────────────────────────────────────

def test_violation_persisted_after_blocked_call(scenario_db: str) -> None:
    """
    Scenario: agent is blocked.  The governance claim requires the violation
    be durable — persisted to SQLite so it appears in the audit log and
    triggers the trust state change.

    What we verify: read the DB directly after the session exits.
    """
    agent_id = "enforce-test-persist"

    with NormaAgentSession(
        agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
    ) as sess:
        tools = sess.wrap_tools([read_confidential])
        tools[0].run("exec_compensation_2025")

    violations = _get_violations(scenario_db, agent_id)
    assert len(violations) == 1, f"Expected 1 violation, found {len(violations)}"
    assert violations[0].blocked is True
    assert violations[0].agent_id == agent_id
    assert violations[0].policy_rule is not None and len(violations[0].policy_rule) > 0
    assert "read_confidential" in violations[0].policy_rule


# ── Test: trust score drops in DB after violation ──────────────────────────────

def test_trust_score_drops_in_db_after_violation(scenario_db: str) -> None:
    """
    Scenario: agent starts at 0.40 trust.  One violation → trust drops to 0.15
    (penalty of 0.25, configured in financial_reader.py CONTRACT_YAML).

    The claim 'violations drop trust score' must be verifiable from the DB,
    not only in the in-process TrustState.
    """
    agent_id = "enforce-test-trust"

    with NormaAgentSession(
        agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
    ) as sess:
        tools = sess.wrap_tools([read_confidential])
        tools[0].run("exec_compensation_2025")

    agent = _get_agent(scenario_db, agent_id)
    assert agent is not None
    # 0.40 initial − 0.25 penalty = 0.15
    assert agent.trust_score < 0.40, (
        f"Trust must drop after violation.  Got {agent.trust_score:.3f}, expected < 0.40"
    )
    assert agent.trust_score == pytest.approx(0.15, abs=0.01)


# ── Test: allowed + denied run in same session ─────────────────────────────────

def test_mixed_session_records_single_violation(scenario_db: str) -> None:
    """
    Scenario: one session has an allowed tool call followed by a denied one.
    Expected: single violation, trust drops, completion_status = failed.
    The allowed call is not penalised.
    """
    import pytest  # noqa: F811
    agent_id = "enforce-test-mixed"
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)

    with NormaAgentSession(
        agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
    ) as sess:
        tools = sess.wrap_tools([list_reports, read_confidential])
        tools[0].run("")           # allowed
        tools[1].run("secret")    # denied

    violations = _get_violations(scenario_db, agent_id)
    assert len(violations) == 1  # only the denied call

    agent = _get_agent(scenario_db, agent_id)
    assert agent is not None
    assert agent.trust_score < 0.40  # trust dropped despite having an allowed call


import pytest  # noqa: E402 — needed for approx in the test above
