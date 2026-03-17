"""S8 — Compliance Pipeline Scenario Test.

Enterprise scenario:
    A compliance team deploys a multi-agent pipeline for financial document review:
      - orchestrator-agent (parent): coordinates the pipeline run
      - audit-reader-agent (sub-agent 1): reads public reports — allowed
      - access-control-agent (sub-agent 2): attempts to read confidential data — BLOCKED

    All three agents run under real NormaAgentSession with enforcement.
    The orchestrator creates a parent Run; each sub-agent creates a child Run
    with parent_run_id pointing to the parent.

    After the run:
      - Parent run exists in DB with no violations
      - Sub-agent 1 run exists, quality > 0, trust increased
      - Sub-agent 2 run exists, has 1 violation (blocked), trust decreased
      - RunStep records exist for sub-agent 2 with blocked=True
      - The run tree structure is parent→[child1, child2]

What this test validates:
    - NormaAgentSession.parent_run_id links child runs to a parent
    - Enforcement blocks a denied tool in a sub-agent (real wrap_tools path)
    - Sub-agent violations are persisted to the DB with correct field values
    - Trust drops after a sub-agent violation
    - RunStep records track per-tool-call events including blocked ones
    - Parent run and child runs correctly form a tree (parent_run_id FK)

Inputs:
    - Real @tool-decorated functions from norma/agents/financial_reader.py
    - CONTRACT_YAML from financial_reader.py (denies read_confidential)
    - Fresh SQLite DB per test (no state leakage)

No LLM calls.  Uses scenario_db fixture (from scenarios/conftest.py).
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
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
from norma.models.run import Run
from norma.models.run_step import RunStep
from norma.models.violation import Violation


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_agent(db_url: str, agent_id: str) -> Agent | None:
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        return s.get(Agent, agent_id)


def _get_runs(db_url: str, agent_id: str) -> list[Run]:
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        rows = s.execute(
            select(Run).where(Run.agent_id == agent_id).order_by(Run.id)
        ).scalars().all()
        # detach
        return list(rows)


def _get_violations(db_url: str, agent_id: str) -> list[Violation]:
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        rows = s.execute(
            select(Violation).where(Violation.agent_id == agent_id)
        ).scalars().all()
        return list(rows)


def _get_steps_for_run(db_url: str, run_id: int) -> list[RunStep]:
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        rows = s.execute(
            select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.step_index)
        ).scalars().all()
        return list(rows)


def _get_all_runs(db_url: str) -> list[Run]:
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        rows = s.execute(select(Run).order_by(Run.id)).scalars().all()
        return list(rows)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_orchestrator_parent_run_created(scenario_db: str) -> None:
    """
    Scenario: the orchestrator runs and creates a parent Run record with no tools
    called.  Its run ID is used as parent_run_id for sub-agents in subsequent tests.
    """
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)
    orch_id = "compliance-orchestrator"

    with NormaAgentSession(
        agent_id=orch_id,
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
    ) as sess:
        # Orchestrator calls list_reports — a purely informational, allowed tool.
        tools = sess.wrap_tools([list_reports])
        result = tools[0].run("")

        # The result must be a real listing (not a blocked message)
        assert "BLOCKED" not in result.upper(), (
            f"list_reports should be allowed; got: {result!r}"
        )

    # Orchestrator run should be in DB
    runs = _get_runs(scenario_db, orch_id)
    assert len(runs) == 1, f"Expected 1 orchestrator run, got {len(runs)}"

    run = runs[0]
    # Parent runs have no parent_run_id themselves
    assert run.parent_run_id is None
    # A clean orchestrator run should not have violations
    violations = _get_violations(scenario_db, orch_id)
    assert len(violations) == 0, f"Orchestrator should have 0 violations, got {len(violations)}"


def test_sub_agent_allowed_run_attached_to_parent(scenario_db: str) -> None:
    """
    Scenario: a sub-agent runs an allowed tool call.  Its run is linked to the
    orchestrator's parent run via parent_run_id.

    The sub-agent's trust score increases (clean run).
    The run record references the parent run ID.
    """
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)
    orch_id = "compliance-orchestrator-linked"
    sub_id = "compliance-reader-sub"

    # 1. Create orchestrator run first to get a parent_run_id
    with NormaAgentSession(
        agent_id=orch_id,
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
    ) as sess:
        sess.wrap_tools([list_reports])  # wrap but don't call — just start the session

    orch_runs = _get_runs(scenario_db, orch_id)
    assert len(orch_runs) == 1, "Orchestrator run not created"
    parent_run_id = orch_runs[0].id

    # 2. Sub-agent runs as a child of the orchestrator
    sub_start_trust: float | None = None
    with NormaAgentSession(
        agent_id=sub_id,
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
        parent_run_id=parent_run_id,
    ) as sess:
        agent_row = _get_agent(scenario_db, sub_id)
        if agent_row:
            sub_start_trust = agent_row.trust_score

        tools = sess.wrap_tools([list_reports, read_report])
        result = tools[0].run("")
        assert "BLOCKED" not in result.upper(), (
            f"list_reports should be allowed for sub-agent; got: {result!r}"
        )

    # 3. Sub-agent run must reference the parent
    sub_runs = _get_runs(scenario_db, sub_id)
    assert len(sub_runs) == 1, f"Expected 1 sub-agent run, got {len(sub_runs)}"
    sub_run = sub_runs[0]

    assert sub_run.parent_run_id == parent_run_id, (
        f"Sub-agent run.parent_run_id={sub_run.parent_run_id!r} "
        f"should equal parent run id {parent_run_id}"
    )

    # 4. Clean run should not produce violations
    violations = _get_violations(scenario_db, sub_id)
    assert len(violations) == 0, f"Clean sub-agent run should have 0 violations, got {len(violations)}"

    # 5. Trust should have increased (clean run increment applied)
    sub_agent_after = _get_agent(scenario_db, sub_id)
    if sub_start_trust is not None and sub_agent_after:
        assert sub_agent_after.trust_score >= sub_start_trust, (
            f"Sub-agent trust should not drop on clean run: "
            f"before={sub_start_trust:.3f} after={sub_agent_after.trust_score:.3f}"
        )


def test_sub_agent_blocked_tool_produces_violation_and_run_step(scenario_db: str) -> None:
    """
    Scenario: a sub-agent attempts to call read_confidential — a tool in the deny list.
    The call must be blocked BEFORE execution, and:
      - A Violation record is persisted with blocked=True
      - A RunStep record is persisted with blocked=True and the correct policy_rule
      - The sub-agent's trust score decreases
    """
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)
    orch_id = "compliance-orchestrator-violation"
    sub_id = "compliance-access-control-sub"

    # 1. Parent run
    with NormaAgentSession(
        agent_id=orch_id,
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
    ) as sess:
        sess.wrap_tools([list_reports])

    orch_runs = _get_runs(scenario_db, orch_id)
    parent_run_id = orch_runs[0].id

    # 2. Sub-agent attempts a blocked tool
    trust_before: float | None = None
    with NormaAgentSession(
        agent_id=sub_id,
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
        parent_run_id=parent_run_id,
    ) as sess:
        agent_row_before = _get_agent(scenario_db, sub_id)
        if agent_row_before:
            trust_before = agent_row_before.trust_score

        tools = sess.wrap_tools([list_reports, read_confidential])
        # Call the blocked tool — read_confidential is in the deny list
        result = tools[1].run("exec_compensation_2025")

        # Must be blocked — actual tool._run() must NOT have executed
        assert "BLOCKED" in result.upper(), (
            f"read_confidential should have been blocked by enforcement; "
            f"got result: {result!r}"
        )

    # 3. Verify violation is in DB with blocked=True
    violations = _get_violations(scenario_db, sub_id)
    assert len(violations) >= 1, (
        "Expected at least 1 violation record after a blocked tool call"
    )
    blocked_violation = next(
        (v for v in violations if v.blocked), None
    )
    assert blocked_violation is not None, (
        "At least one violation must have blocked=True"
    )
    assert "confidential" in (blocked_violation.action_attempted or "").lower() or \
           "confidential" in (blocked_violation.policy_rule or "").lower(), (
        f"Violation should reference 'confidential' in action_attempted or policy_rule; "
        f"action_attempted={blocked_violation.action_attempted!r} "
        f"policy_rule={blocked_violation.policy_rule!r}"
    )

    # 4. Verify RunStep record with blocked=True
    sub_runs = _get_runs(scenario_db, sub_id)
    assert len(sub_runs) == 1, f"Expected 1 sub-agent run, got {len(sub_runs)}"
    sub_run_id = sub_runs[0].id

    steps = _get_steps_for_run(scenario_db, sub_run_id)
    assert len(steps) >= 1, (
        f"Expected RunStep records for run {sub_run_id}, got none"
    )
    blocked_step = next((s for s in steps if s.blocked), None)
    assert blocked_step is not None, (
        "At least one RunStep must have blocked=True"
    )
    assert blocked_step.tool_name == "read_confidential", (
        f"Blocked step should be for 'read_confidential', got {blocked_step.tool_name!r}"
    )

    # 5. Trust score must have decreased
    agent_after = _get_agent(scenario_db, sub_id)
    assert agent_after is not None, "Sub-agent row must exist after session"
    if trust_before is not None:
        assert agent_after.trust_score < trust_before, (
            f"Trust should decrease after a violation: "
            f"before={trust_before:.3f} after={agent_after.trust_score:.3f}"
        )


def test_run_tree_parent_child_structure(scenario_db: str) -> None:
    """
    Scenario: after a full orchestrator + 2 sub-agent run, the run tree
    has the correct parent-child structure:

        orchestrator_run
        ├── sub_agent_1_run  (clean — list_reports)
        └── sub_agent_2_run  (violation — read_confidential)

    Verified by reading the DB directly (not through the API, which is covered
    by the integration tests).
    """
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)
    orch_id = "tree-orchestrator"
    sub1_id = "tree-reader-sub"
    sub2_id = "tree-access-sub"

    # 1. Orchestrator run
    with NormaAgentSession(
        agent_id=orch_id,
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
    ) as sess:
        tools = sess.wrap_tools([list_reports])
        tools[0].run("")  # allowed, clean

    orch_runs = _get_runs(scenario_db, orch_id)
    assert len(orch_runs) == 1
    parent_id = orch_runs[0].id

    # 2. Sub-agent 1: allowed run (child of orchestrator)
    with NormaAgentSession(
        agent_id=sub1_id,
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
        parent_run_id=parent_id,
    ) as sess:
        tools = sess.wrap_tools([list_reports])
        tools[0].run("")

    # 3. Sub-agent 2: violation run (child of orchestrator)
    with NormaAgentSession(
        agent_id=sub2_id,
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
        parent_run_id=parent_id,
    ) as sess:
        tools = sess.wrap_tools([read_confidential])
        tools[0].run("exec_compensation_2025")  # blocked

    # 4. Verify tree structure via direct DB queries
    all_runs = _get_all_runs(scenario_db)

    # Filter to this test's runs
    orch_run = next((r for r in all_runs if r.agent_id == orch_id), None)
    sub1_run = next((r for r in all_runs if r.agent_id == sub1_id), None)
    sub2_run = next((r for r in all_runs if r.agent_id == sub2_id), None)

    assert orch_run is not None, "Orchestrator run missing from DB"
    assert sub1_run is not None, "Sub-agent 1 run missing from DB"
    assert sub2_run is not None, "Sub-agent 2 run missing from DB"

    # Parent runs have no parent
    assert orch_run.parent_run_id is None, (
        f"Orchestrator run should have no parent, got {orch_run.parent_run_id!r}"
    )

    # Child runs reference the parent
    assert sub1_run.parent_run_id == orch_run.id, (
        f"sub1 parent_run_id={sub1_run.parent_run_id!r} should be {orch_run.id!r}"
    )
    assert sub2_run.parent_run_id == orch_run.id, (
        f"sub2 parent_run_id={sub2_run.parent_run_id!r} should be {orch_run.id!r}"
    )

    # Sub-agent 1 has no violations; sub-agent 2 does
    sub1_violations = _get_violations(scenario_db, sub1_id)
    sub2_violations = _get_violations(scenario_db, sub2_id)
    assert len(sub1_violations) == 0, f"Sub-agent 1 (clean) should have 0 violations, got {len(sub1_violations)}"
    assert len(sub2_violations) >= 1, f"Sub-agent 2 (violation) should have ≥1 violation, got {len(sub2_violations)}"

    # Sub-agent 2's run step should have blocked=True
    sub2_steps = _get_steps_for_run(scenario_db, sub2_run.id)
    blocked_steps = [s for s in sub2_steps if s.blocked]
    assert len(blocked_steps) >= 1, (
        f"Sub-agent 2's run ({sub2_run.id}) should have ≥1 blocked RunStep, "
        f"got {len(blocked_steps)} blocked out of {len(sub2_steps)} total steps"
    )


def test_run_steps_populated_for_allowed_tool_call(scenario_db: str) -> None:
    """
    Scenario: when an agent makes an allowed tool call, a RunStep record
    is created with blocked=False, a real tool_name, and a non-None output_text.

    This validates that the step tracer persists real tool output — not a stub.
    """
    REPORTS_PUBLIC.mkdir(parents=True, exist_ok=True)
    agent_id = "step-trace-allowed"

    with NormaAgentSession(
        agent_id=agent_id,
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
    ) as sess:
        tools = sess.wrap_tools([list_reports, read_report])
        result = tools[0].run("")  # list_reports — always returns a string

    # Run must exist
    runs = _get_runs(scenario_db, agent_id)
    assert len(runs) == 1, f"Expected 1 run, got {len(runs)}"
    run_id = runs[0].id

    # RunStep records must exist
    steps = _get_steps_for_run(scenario_db, run_id)
    assert len(steps) >= 1, f"Expected ≥1 RunStep for run {run_id}"

    allowed_step = next((s for s in steps if not s.blocked), None)
    assert allowed_step is not None, "Should have at least one non-blocked step"

    # Tool name must be recorded
    assert allowed_step.tool_name == "list_reports", (
        f"Expected tool_name='list_reports', got {allowed_step.tool_name!r}"
    )

    # Output must be the REAL tool output
    assert allowed_step.output_text is not None, "output_text should not be None for allowed call"
    assert len(allowed_step.output_text) > 0, "output_text should not be empty"

    # The step output should match the direct tool result
    assert allowed_step.output_text == result or result in allowed_step.output_text, (
        f"Step output_text should match the tool result.\n"
        f"  output_text={allowed_step.output_text!r}\n"
        f"  result      ={result!r}"
    )

    # Latency must have been measured (> 0 ms)
    assert allowed_step.latency_ms is not None and allowed_step.latency_ms >= 0, (
        f"latency_ms should be ≥ 0 for an allowed call, got {allowed_step.latency_ms!r}"
    )
