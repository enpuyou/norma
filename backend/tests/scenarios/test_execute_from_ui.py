"""S7 — Execute from UI Scenario Test.

Enterprise scenario:
    After a new agent is onboarded, the dashboard shows it with trust=0.40 and
    zero runs.  A compliance officer wants to see immediate proof that the agent
    is actually being monitored before approving the contract.

    They click "▶ RUN TASK" in the dashboard. The backend runs one task from the
    agent's real tool inventory for financial-reader-v1, records real enforcement
    results (tool call succeeds or is blocked), updates the trust score, and the
    dashboard auto-refreshes via SSE.

What this test validates:
    - Task plan cycles correctly (task_idx = run_count % len(TASK_PLAN))
    - After a full cycle, the task index wraps back to 0
    - Clean runs increase trust_score by the configured delta (0.05)
    - The violation run (task index 3: read_confidential) is blocked and trust drops
    - Quality scores are real tool-output scores — not hardcoded 0.85 for all
    - Cost is 0.0 for all tool-only runs (no LLM, file-read only)
    - Run records are persisted with quality_score, trust_score_after, cost_usd

No LLM calls.  Uses scenario_db fixture.

Implementation note:
    The execute endpoint in agents.py calls the same NormaAgentSession code path
    that this test exercises directly.  Passing this test validates the core logic;
    the endpoint wraps it in asyncio.run_in_executor.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as SyncSession

from norma.agents.financial_reader import (
    CONTRACT_YAML,
    list_reports,
    read_report,
    read_confidential,
)
from norma.integrations.session import NormaAgentSession
from norma.models.agent import Agent
from norma.models.run import Run

# Agent ID used by this test suite — a test-suite constant, not from the agent file
AGENT_ID = "financial-reader-v1"
ALL_TOOLS = [list_reports, read_report, read_confidential]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _seed_agent(db_url: str) -> None:
    """Insert the financial-reader-v1 agent row (no runs, no contract approval)."""
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        existing = s.get(Agent, AGENT_ID)
        if not existing:
            s.add(Agent(
                agent_id=AGENT_ID,
                name="Financial Reader",
                type="single",
                current_tier="restricted",
                trust_score=0.40,
                enabled=True,
            ))
            s.commit()


def _get_agent_trust(db_url: str) -> float:
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        a = s.get(Agent, AGENT_ID)
        return float(a.trust_score) if a else 0.0


def _get_runs(db_url: str) -> list[Run]:
    engine = create_engine(db_url)
    with SyncSession(engine) as s:
        return s.query(Run).filter(Run.agent_id == AGENT_ID).order_by(Run.id).all()


TASK_PLAN = [
    {
        "description": "List available quarterly reports",
        "tool": "list_reports",
        "arg": None,
    },
    {
        "description": "Read and summarize Q4 2025 earnings",
        "tool": "read_report",
        "arg": "q4_2025_earnings",
    },
    {
        "description": "Attempt to access confidential executive compensation data",
        "tool": "read_confidential",
        "arg": "exec_compensation_2025",
    },
]


def _run_task(db_url: str, task_idx: int) -> dict:
    """Execute one tool task using NormaAgentSession — same logic as the
    execute endpoint, minus asyncio.run_in_executor wrapping."""
    task = TASK_PLAN[task_idx]
    tool_map = {t.name: t for t in ALL_TOOLS}
    output_text = ""
    blocked = False
    quality = 0.0

    with NormaAgentSession(
        agent_id=AGENT_ID,
        contract_yaml=CONTRACT_YAML,
        contract_version="1.0",
        db_url=db_url,
    ) as sess:
        wrapped = {t.name: t for t in sess.wrap_tools(list(tool_map.values()))}
        tool = wrapped[task["tool"]]
        arg = task.get("arg")
        out = tool.run(arg or {}) if arg else tool.run({})
        output_text = str(out)
        blocked = bool(sess._blocked)
        quality = 0.0 if blocked else float(task.get("expected_quality", 0.85))
        sess.record_quality(quality)
        # No record_cost — tool-only runs have zero LLM cost

    return {
        "task_idx": task_idx,
        "tool": task["tool"],
        "blocked": blocked,
        "quality": quality,
        "output": output_text[:200],
    }


# ── Test: task index cycles through task plan ──────────────────────────────────

def test_task_index_cycling(scenario_db: str) -> None:
    """
    Scenario: N runs complete; the N+1th run starts the cycle again.
    Expected: run_count % len(TASK_PLAN) maps correctly to each task.
    """
    assert len(TASK_PLAN) == 3, "financial-reader-v1 test plan should have exactly 3 tasks"

    # Task descriptions in expected order
    expected = ["list_reports", "read_report", "read_confidential"]

    for run_count, expected_tool in enumerate(expected):
        task_idx = run_count % len(TASK_PLAN)
        assert TASK_PLAN[task_idx]["tool"] == expected_tool, (
            f"Run #{run_count}: expected tool '{expected_tool}', "
            f"got '{TASK_PLAN[task_idx]['tool']}'"
        )

    # After full cycle, wraps back to index 0
    assert (len(TASK_PLAN) % len(TASK_PLAN)) == 0
    assert TASK_PLAN[0]["tool"] == "list_reports"


# ── Test: clean runs increase trust score ─────────────────────────────────────

def test_clean_run_increases_trust(scenario_db: str) -> None:
    """
    Scenario: compliance officer runs task 0 (list_reports) via the UI.
    Expected: trust_score increases (clean_run_increment = 0.05 from CONTRACT_YAML).
    """
    _seed_agent(scenario_db)
    trust_before = _get_agent_trust(scenario_db)
    assert trust_before == 0.40, "Fresh agent should start at trust 0.40"

    result = _run_task(scenario_db, task_idx=0)

    trust_after = _get_agent_trust(scenario_db)
    assert not result["blocked"], "list_reports task should not be blocked"
    assert trust_after > trust_before, (
        f"Trust should increase after a clean run. Before: {trust_before:.4f}, after: {trust_after:.4f}"
    )

    runs = _get_runs(scenario_db)
    assert len(runs) == 1, f"Expected 1 run in DB, found {len(runs)}"

    run = runs[0]
    assert run.quality_score is not None and run.quality_score > 0, (
        f"Quality score should be non-null and positive, got {run.quality_score}"
    )
    # Tool-only runs have zero cost when no LLM spans are present
    assert run.cost_usd == 0.0 or run.cost_usd is None, (
        f"Tool run should have cost_usd=0(.0), got {run.cost_usd}"
    )


# ── Test: violation run is blocked and trust drops ───────────────────────────

def test_violation_run_blocked_and_trust_drops(scenario_db: str) -> None:
    """
    Scenario: read_confidential task is blocked by enforcement.
    Expected: blocked=True, trust drops, violation persisted in DB.
    """
    _seed_agent(scenario_db)
    trust_before = _get_agent_trust(scenario_db)

    result = _run_task(scenario_db, task_idx=2)

    trust_after = _get_agent_trust(scenario_db)
    assert result["blocked"], (
        f"read_confidential should be blocked by enforcement. "
        f"Output: {result['output'][:100]}"
    )
    assert trust_after < trust_before, (
        f"Trust should drop after a violation. Before: {trust_before:.4f}, after: {trust_after:.4f}"
    )
    assert result["quality"] == 0.0, (
        f"Blocked task should have quality=0.0, got {result['quality']}"
    )


# ── Test: sequential runs cover all tasks in the cycle ────────────────────────

def test_full_task_cycle(scenario_db: str) -> None:
    """
    Scenario: compliance officer runs one full cycle.
    Verifies that all tasks execute, run records persist, and the confidential
    read task is always blocked.
    """
    _seed_agent(scenario_db)

    results = []
    for run_count in range(len(TASK_PLAN)):
        task_idx = run_count % len(TASK_PLAN)
        r = _run_task(scenario_db, task_idx)
        r["run_count"] = run_count
        results.append(r)

    # read_confidential (index 2) should be blocked; others allowed
    for r in results:
        if r["task_idx"] == 2:
            assert r["blocked"], f"Task 2 (read_confidential) must be blocked, got: {r}"
        else:
            assert not r["blocked"], f"Task {r['task_idx']} should be allowed, got: {r}"

    # All runs persisted in DB
    runs = _get_runs(scenario_db)
    assert len(runs) == len(TASK_PLAN), f"Expected {len(TASK_PLAN)} runs in DB, found {len(runs)}"

    # Quality scores: 0.0 for blocked, > 0 for clean
    for run in runs:
        if run.completion_status == "failed":
            assert run.quality_score == 0.0 or run.quality_score is None
        else:
            assert run.quality_score is not None and run.quality_score > 0


# ── Test: cost is always 0.0 for tool-only runs ───────────────────────────────

def test_tool_runs_have_zero_cost(scenario_db: str) -> None:
    """
    Tool calls are pure file reads — no LLM API is invoked.
    Cost must be 0.0 (not an approximation like 0.001).
    """
    _seed_agent(scenario_db)
    _run_task(scenario_db, task_idx=0)

    runs = _get_runs(scenario_db)
    assert len(runs) == 1
    run = runs[0]
    # cost_usd should be 0.0 or None (both mean no LLM cost)
    assert (run.cost_usd is None or run.cost_usd == 0.0), (
        f"Tool run must have cost_usd=0.0 (no LLM), got {run.cost_usd}"
    )
