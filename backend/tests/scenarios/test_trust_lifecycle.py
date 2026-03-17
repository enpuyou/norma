"""S5 — Trust Lifecycle Scenario Test.

Enterprise scenario:
    A newly deployed agent (financial-reader-v1) must earn promotion from
    Restricted to Standard tier through demonstrated reliability.

    The team needs to verify that:
      1. Each clean run actually increases the trust score in the DB
         (not just in an in-process TrustState object that vanishes on exit)
      2. Trust threshold triggers a pending contract version (not an auto-promotion)
      3. Promotion only takes effect after human approval
      4. A violation after promotion immediately demotes the agent

What this test validates:
    - NormaAgentSession (not agent.run_clean()) drives trust updates
    - Trust changes are read back from SQLite between sessions
    - Tier transitions go through the pending_contract_version gate
    - Demotion persists to DB

Inputs:
    - Real @tool-decorated functions from financial_reader.py
    - financial_reader.py CONTRACT_YAML (increment: 0.05, threshold: 0.65 at 5 runs)

No LLM calls.  Uses scenario_db fixture (fresh temp DB per test).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from norma.agents.financial_reader import (
    CONTRACT_YAML,
    REPORTS_PUBLIC,
    list_reports,
    read_confidential,
    read_report,
)
from norma.core.trust_engine import approve_pending_contract, TrustState
from norma.integrations.session import NormaAgentSession
from norma.models.agent import Agent


def _get_agent(db_url: str, agent_id: str) -> Agent | None:
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        return s.get(Agent, agent_id)


def _update_agent(db_url: str, agent_id: str, **updates: object) -> None:
    """Helper to mutate agent fields for test setup."""
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        agent = s.get(Agent, agent_id)
        if agent:
            for k, v in updates.items():
                setattr(agent, k, v)
            s.commit()


# ── Test: trust score increases with each clean run ───────────────────────────

def test_trust_increases_per_clean_run(scenario_db: str) -> None:
    """
    Scenario: run the agent 5 times on allowed tools.  Read trust from DB after
    each run to verify it actually increased — not just in-process state.

    financial_reader CONTRACT_YAML sets clean_run_increment = 0.05.
    Starting at 0.40, after 5 clean runs: 0.40 + 5 × 0.05 = 0.65.
    """
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)
    agent_id = "trust-lifecycle-clean"
    prev_trust = 0.40

    for run_n in range(1, 6):
        with NormaAgentSession(
            agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
        ) as sess:
            tools = sess.wrap_tools([list_reports, read_report])
            tools[0].run("")  # allowed call → clean run

        agent = _get_agent(scenario_db, agent_id)
        assert agent is not None, f"Agent row missing after run {run_n}"
        assert agent.trust_score > prev_trust, (
            f"Run {run_n}: trust should have increased from {prev_trust:.3f}, "
            f"got {agent.trust_score:.3f}"
        )
        prev_trust = agent.trust_score

    # After 5 × 0.05: should be at / near 0.65
    assert prev_trust == pytest.approx(0.65, abs=0.01)


# ── Test: threshold triggers pending contract (not auto-promotion) ─────────────

def test_tier_threshold_proposes_contract_not_promotes(scenario_db: str) -> None:
    """
    Scenario: after 5 clean runs (score ≥ 0.65), the system proposes a contract
    version for human review.  The agent remains in 'restricted' tier until
    the human approves — no automatic promotion.
    """
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)
    agent_id = "trust-lifecycle-gate"

    for _ in range(5):
        with NormaAgentSession(
            agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
        ) as sess:
            sess.wrap_tools([list_reports])[0].run("")  # list_reports takes no required args

    agent = _get_agent(scenario_db, agent_id)
    assert agent is not None
    assert agent.trust_score >= 0.65

    # A pending contract version should be proposed
    assert agent.pending_contract_version is not None, (
        "Expected a pending contract proposal after reaching the threshold"
    )
    # But the tier must NOT have changed yet — promotion requires human approval
    assert agent.current_tier == "restricted", (
        f"Tier must remain 'restricted' until human approves.  Got '{agent.current_tier}'"
    )


# ── Test: human approval promotes tier ────────────────────────────────────────

def test_tier_promoted_after_human_approval(scenario_db: str) -> None:
    """
    Scenario: after the threshold is reached, a human calls the trust engine's
    approve function.  Only then does the tier change.

    In production this is triggered by POST /api/contracts/{id}/approve/{v}.
    Here we test the trust engine layer directly.
    """
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)
    agent_id = "trust-lifecycle-approve"

    for _ in range(5):
        with NormaAgentSession(
            agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
        ) as sess:
            sess.wrap_tools([list_reports])[0].run("")  # list_reports takes no required args

    agent = _get_agent(scenario_db, agent_id)
    assert agent is not None
    assert agent.pending_contract_version is not None

    # Human approves — simulate by calling approve_pending_contract and persisting
    engine = create_engine(scenario_db)
    with SyncSession(engine) as s:
        agent_row = s.get(Agent, agent_id)
        import yaml  # noqa: F401
        import yaml as _yaml
        trust_cfg = _yaml.safe_load(CONTRACT_YAML).get("trust", {})
        state = TrustState(
            agent_id=agent_id,
            trust_score=agent_row.trust_score,
            current_tier=agent_row.current_tier,
            pending_contract_version=agent_row.pending_contract_version,
            clean_run_increment=trust_cfg.get("clean_run_increment", 0.05),
            violation_penalty=trust_cfg.get("violation_penalty", 0.25),
            tier_thresholds=trust_cfg.get(
                "tier_thresholds",
                {"standard": {"min_score": 0.65, "min_clean_runs": 5}},
            ),
        )
        approve_pending_contract(state, approver="test-human")
        agent_row.current_tier = state.current_tier
        agent_row.pending_contract_version = None
        s.commit()

    agent = _get_agent(scenario_db, agent_id)
    assert agent.current_tier == "standard", (
        f"Expected 'standard' after human approval, got '{agent.current_tier}'"
    )


# ── Test: violation after promotion demotes immediately ────────────────────────

def test_violation_demotes_from_standard_to_restricted(scenario_db: str) -> None:
    """
    Scenario: agent has been promoted to standard tier.  When it attempts a
    denied action, it is immediately demoted back to restricted.

    Trust score penalty: 0.65 − 0.25 = 0.40.
    """
    agent_id = "trust-lifecycle-demote"

    # Fast-path setup: insert a pre-promoted agent directly
    engine = create_engine(scenario_db)
    from norma.models.agent import Agent as AgentModel
    with SyncSession(engine) as s:
        agent_row = AgentModel(
            agent_id=agent_id,
            name="Trust Demotion Test Agent",
            type="single",
            current_tier="standard",
            trust_score=0.65,
            enabled=True,
        )
        s.add(agent_row)
        s.commit()

    with NormaAgentSession(
        agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
    ) as sess:
        tools = sess.wrap_tools([read_confidential])
        tools[0].run("exec_compensation_2025")

    agent = _get_agent(scenario_db, agent_id)
    assert agent is not None
    # Trust drops
    assert agent.trust_score <= 0.41, (
        f"Expected trust ≤ 0.41 after violation, got {agent.trust_score:.3f}"
    )
    # Tier reverts
    assert agent.current_tier == "restricted", (
        f"Expected 'restricted' after violation, got '{agent.current_tier}'"
    )


# ── Test: clean runs are cumulative across separate sessions ───────────────────

def test_trust_persists_across_session_restarts(scenario_db: str) -> None:
    """
    Scenario: the monitoring server restarts.  When the agent runs again,
    trust should continue from where it left off — not reset to 0.40.

    This verifies that NormaAgentSession reads trust from the DB, not from
    an in-memory default.
    """
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)
    agent_id = "trust-lifecycle-persist"

    # First session: 3 clean runs
    for _ in range(3):
        with NormaAgentSession(
            agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
        ) as sess:
            sess.wrap_tools([list_reports])[0].run("")  # list_reports takes no required args

    trust_after_3 = _get_agent(scenario_db, agent_id).trust_score
    expected_after_3 = 0.40 + 3 * 0.05
    assert trust_after_3 == pytest.approx(expected_after_3, abs=0.01)

    # "Server restart" — new sessions start fresh (NormaAgentSession reads DB)
    for _ in range(2):
        with NormaAgentSession(
            agent_id=agent_id, contract_yaml=CONTRACT_YAML, db_url=scenario_db
        ) as sess:
            sess.wrap_tools([list_reports])[0].run("")  # list_reports takes no required args

    trust_after_5 = _get_agent(scenario_db, agent_id).trust_score
    expected_after_5 = 0.40 + 5 * 0.05
    assert trust_after_5 == pytest.approx(expected_after_5, abs=0.01), (
        "Trust must accumulate across separate sessions, not reset per session"
    )
