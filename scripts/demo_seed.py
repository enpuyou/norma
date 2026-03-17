#!/usr/bin/env python3
"""demo_seed.py — Build genuine run history for the norma demo.

This script runs real norma sessions (with or without LLM) to populate the
database with authentic telemetry. It creates:
  - Multiple clean runs under contract v1.0 (restricted tier)
  - A contract upgrade to v2.0 (standard tier)
  - A violation run (blocked tool attempt)
  - A few runs under v2.0 to show the version-split on the trend graph

Usage
-----
  # Scripted mode — no LLM needed, fast, great for CI:
  python scripts/demo_seed.py

  # LLM mode — requires OPENAI_API_KEY, produces richer quality scores:
  python scripts/demo_seed.py --llm

  # Seed both agents:
  python scripts/demo_seed.py --agent financial-reader
  python scripts/demo_seed.py --agent research-team

  # Only approve contracts (no new runs):
  python scripts/demo_seed.py --approve-contracts-only

  # Wipe existing data first:
  python scripts/demo_seed.py --reset

Options
-------
  --agent           financial-reader (default) or research-team
  --llm             Use real LLM for richer quality scoring
  --runs            Total clean runs to create (default: 8)
  --approve-contracts-only  Just push contract v1→v2 approval, don't run
  --reset           Delete all runs/violations for this agent before seeding
  --db-url          SQLite URL override

Environment
-----------
  OPENAI_API_KEY    Required for --llm mode
  NORMA_DB_URL      Override default DB location
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Ensure backend is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _PROJECT_ROOT / "backend"
for p in [str(_PROJECT_ROOT), str(_BACKEND)]:
    if p not in sys.path:
        sys.path.insert(0, p)


def _get_db_url(override: str | None) -> str:
    from norma.config import get_settings
    url = override or os.environ.get("NORMA_DB_URL") or get_settings().database_url
    return url.replace("+aiosqlite", "")


def _print(msg: str, color: str | None = None) -> None:
    colors = {"green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m", "cyan": "\033[96m", "reset": "\033[0m"}
    if color:
        print(f"{colors.get(color, '')}{msg}{colors['reset']}")
    else:
        print(msg)


def _run_single_task(
    *,
    agent_id: str,
    contract_yaml: str,
    contract_version: str,
    tool_map: dict,
    tool_name: str,
    arg: str | dict | None,
    db_url: str,
    expected_quality: float = 0.88,
) -> dict:
    """Run a single tool call under norma enforcement, returns result dict."""
    from norma.integrations.session import NormaAgentSession

    with NormaAgentSession(
        agent_id=agent_id,
        contract_yaml=contract_yaml,
        contract_version=contract_version,
        db_url=db_url,
        initiated_by="demo_seed",
    ) as sess:
        wrapped = {t.name: t for t in sess.wrap_tools(list(tool_map.values()))}
        t = wrapped[tool_name]
        if isinstance(arg, dict):
            output = t.run(arg)
        elif arg:
            output = t.run(arg)
        else:
            output = t.run({})
        blocked = sess._blocked
        if not blocked:
            sess.record_quality(expected_quality)

    return {"tool": tool_name, "blocked": blocked, "output": str(output)[:200]}


def _run_llm_task(
    *,
    agent_id: str,
    contract_yaml: str,
    contract_version: str,
    build_fn,
    prompt: str,
    db_url: str,
) -> dict:
    """Run a real LLM agent under norma monitoring."""
    from norma.integrations.session import NormaAgentSession

    with NormaAgentSession(
        agent_id=agent_id,
        contract_yaml=contract_yaml,
        contract_version=contract_version,
        db_url=db_url,
        initiated_by="demo_seed",
    ) as sess:
        executor = build_fn()
        if hasattr(executor, "tools"):
            executor.tools = sess.wrap_tools(executor.tools)
        try:
            result = executor.invoke({"input": prompt})
            output = result.get("output", str(result))
        except Exception as e:
            output = f"[ERROR] {e}"
            sess._completion_status = "failed"
        blocked = sess._blocked

    return {"tool": "llm_agent", "blocked": blocked, "output": str(output)[:200]}


def _ensure_contract_versions(
    agent_id: str,
    contract_yaml_v1: str,
    contract_yaml_v2: str,
    db_url: str,
) -> None:
    """Upsert both contract versions into the DB and approve them."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime

    engine = create_engine(db_url, echo=False)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        # Ensure agent exists
        db.execute(text("""
            INSERT OR IGNORE INTO agents (agent_id, name, type, current_tier, trust_score, enabled)
            VALUES (:aid, :name, 'single', 'restricted', 0.40, 1)
        """), {"aid": agent_id, "name": agent_id})
        db.commit()

    # Use norma's contract API to create/approve versions
    try:
        from norma.models.contract import ContractVersion
        engine2 = create_engine(db_url, echo=False)
        Session2 = sessionmaker(bind=engine2)
        now = datetime.utcnow()

        for version, yaml_content in [("1.0", contract_yaml_v1), ("2.0", contract_yaml_v2)]:
            with Session2() as db:
                existing = db.execute(
                    text("SELECT id FROM contract_versions WHERE agent_id=:aid AND version=:v"),
                    {"aid": agent_id, "v": version},
                ).fetchone()

                if not existing:
                    db.add(ContractVersion(
                        agent_id=agent_id,
                        version=version,
                        yaml_content=yaml_content,
                        status="active",
                        approved_by="demo_seed",
                        approved_at=now,
                        created_by="demo_seed",
                        created_at=now,
                        activated_at=now,
                    ))
                    db.commit()
                    _print(f"  Created contract v{version} for {agent_id}", "green")
                else:
                    _print(f"  Contract v{version} already exists for {agent_id}")
    except Exception as e:
        _print(f"  Warning: could not upsert contracts: {e}", "yellow")


def _reset_agent_data(agent_id: str, db_url: str) -> None:
    """Delete all runs/violations/spans for this agent."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(db_url, echo=False)
    with engine.connect() as conn:
        # Get all run IDs for this agent
        rows = conn.execute(
            text("SELECT id FROM runs WHERE agent_id = :aid"),
            {"aid": agent_id},
        ).fetchall()
        run_ids = [r[0] for r in rows]

        if run_ids:
            id_list = ",".join(str(i) for i in run_ids)
            conn.execute(text(f"DELETE FROM violations WHERE run_id IN ({id_list})"))
            conn.execute(text(f"DELETE FROM run_steps WHERE run_id IN ({id_list})"))
            conn.execute(text(f"DELETE FROM spans WHERE trace_id IN ({id_list})"))
            conn.execute(text(f"DELETE FROM prompt_snapshots WHERE run_id IN ({id_list})"))
            conn.execute(text(f"DELETE FROM runs WHERE agent_id = :aid"), {"aid": agent_id})
            conn.execute(text("DELETE FROM agents WHERE agent_id = :aid"), {"aid": agent_id})
            conn.commit()
            _print(f"  Reset: deleted {len(run_ids)} runs for {agent_id}", "yellow")
        else:
            _print(f"  Reset: no existing runs for {agent_id}")


def seed_financial_reader(
    *,
    db_url: str,
    use_llm: bool,
    n_runs: int,
    approve_contracts_only: bool,
) -> None:
    from norma.agents.financial_reader import (
        AGENT_ID, ALL_TOOLS, CONTRACT_YAML, CONTRACT_YAML_V2,
    )

    tool_map = {t.name: t for t in ALL_TOOLS}
    _print(f"\n  Seeding agent: {AGENT_ID}", "cyan")

    _ensure_contract_versions(AGENT_ID, CONTRACT_YAML, CONTRACT_YAML_V2, db_url)
    if approve_contracts_only:
        return

    # Phase 1: v1.0 clean runs (~60% of total)
    n_v1 = max(1, int(n_runs * 0.6))
    _print(f"\n  Phase 1: {n_v1} clean runs under contract v1.0…")
    for i in range(n_v1):
        # Alternate between list_reports and read_report for variety
        if i % 2 == 0:
            r = _run_single_task(
                agent_id=AGENT_ID, contract_yaml=CONTRACT_YAML,
                contract_version="1.0", tool_map=tool_map,
                tool_name="list_reports", arg=None,
                db_url=db_url, expected_quality=0.82 + (i % 3) * 0.03,
            )
        else:
            r = _run_single_task(
                agent_id=AGENT_ID, contract_yaml=CONTRACT_YAML,
                contract_version="1.0", tool_map=tool_map,
                tool_name="read_report", arg="q3_2024",
                db_url=db_url, expected_quality=0.85 + (i % 4) * 0.02,
            )
        status = "BLOCKED" if r["blocked"] else "ok"
        _print(f"    run {i+1}/{n_v1}: {r['tool']} → {status}")
        time.sleep(0.05)  # slight spread for timestamp ordering

    # Phase 2: 1 violation run (confidential access attempt)
    _print("\n  Phase 2: 1 violation run (confidential access — should be BLOCKED)…")
    r = _run_single_task(
        agent_id=AGENT_ID, contract_yaml=CONTRACT_YAML,
        contract_version="1.0", tool_map=tool_map,
        tool_name="read_confidential", arg="executive_compensation",
        db_url=db_url,
    )
    _print(f"    violation run: {r['tool']} → {'BLOCKED ✗' if r['blocked'] else 'ALLOWED (unexpected!)'}", "red" if r["blocked"] else "yellow")

    # Phase 3: v2.0 runs (~remaining)
    n_v2 = n_runs - n_v1
    _print(f"\n  Phase 3: {n_v2} runs under contract v2.0 (standard tier)…")
    v2_tasks = ["list_reports", "read_report", "export_to_drive"]
    v2_args = [None, "q4_2024", {"filename": "q4_2024_summary", "content": "Q4 2024 earnings: revenue up 12% YoY."}]
    for i in range(n_v2):
        idx = i % len(v2_tasks)
        r = _run_single_task(
            agent_id=AGENT_ID, contract_yaml=CONTRACT_YAML_V2,
            contract_version="2.0", tool_map=tool_map,
            tool_name=v2_tasks[idx], arg=v2_args[idx],
            db_url=db_url, expected_quality=0.88 + (i % 3) * 0.03,
        )
        status = "BLOCKED" if r["blocked"] else "ok"
        _print(f"    run {i+1}/{n_v2}: {r['tool']} → {status}")
        time.sleep(0.05)

    if use_llm:
        _print("\n  Phase 4: 1 real LLM run (full report analysis)…")
        from agents.financial_reader.earnings_report_reader import build_llm_agent
        r = _run_llm_task(
            agent_id=AGENT_ID, contract_yaml=CONTRACT_YAML_V2,
            contract_version="2.0", build_fn=build_llm_agent,
            prompt="List the available reports, then read and summarize the Q4 2024 earnings.",
            db_url=db_url,
        )
        _print(f"    LLM run → {'BLOCKED' if r['blocked'] else 'ok'}: {r['output'][:80]}…")


def seed_research_team(
    *,
    db_url: str,
    use_llm: bool,
    n_runs: int,
    approve_contracts_only: bool,
) -> None:
    from norma.agents.research_team import (
        AGENT_ID, ALL_TOOLS, CONTRACT_YAML, CONTRACT_YAML_V2,
    )

    tool_map = {t.name: t for t in ALL_TOOLS}
    _print(f"\n  Seeding agent: {AGENT_ID}", "cyan")

    _ensure_contract_versions(AGENT_ID, CONTRACT_YAML, CONTRACT_YAML_V2, db_url)
    if approve_contracts_only:
        return

    n_v1 = max(1, int(n_runs * 0.6))
    _print(f"\n  Phase 1: {n_v1} clean runs under contract v1.0…")
    v1_tasks = ["list_research_papers", "search_research_by_topic", "fetch_research_paper"]
    v1_args = [None, "machine learning safety", "ai_safety_overview"]
    for i in range(n_v1):
        idx = i % len(v1_tasks)
        r = _run_single_task(
            agent_id=AGENT_ID, contract_yaml=CONTRACT_YAML,
            contract_version="1.0", tool_map=tool_map,
            tool_name=v1_tasks[idx], arg=v1_args[idx],
            db_url=db_url, expected_quality=0.83 + (i % 3) * 0.03,
        )
        status = "BLOCKED" if r["blocked"] else "ok"
        _print(f"    run {i+1}/{n_v1}: {r['tool']} → {status}")
        time.sleep(0.05)

    _print("\n  Phase 2: 1 violation run (restricted data access — should be BLOCKED)…")
    r = _run_single_task(
        agent_id=AGENT_ID, contract_yaml=CONTRACT_YAML,
        contract_version="1.0", tool_map=tool_map,
        tool_name="read_restricted_data", arg="internal_strategy_2025",
        db_url=db_url,
    )
    _print(f"    violation run: {r['tool']} → {'BLOCKED ✗' if r['blocked'] else 'ALLOWED (unexpected!)'}", "red" if r["blocked"] else "yellow")

    n_v2 = n_runs - n_v1
    _print(f"\n  Phase 3: {n_v2} runs under contract v2.0…")
    v2_tasks = ["list_research_papers", "search_research_by_topic", "extract_key_metrics", "summarize_findings"]
    v2_args = [None, "AI governance frameworks", "ai_safety_overview", "ai_safety_overview"]
    for i in range(n_v2):
        idx = i % len(v2_tasks)
        r = _run_single_task(
            agent_id=AGENT_ID, contract_yaml=CONTRACT_YAML_V2,
            contract_version="2.0", tool_map=tool_map,
            tool_name=v2_tasks[idx], arg=v2_args[idx],
            db_url=db_url, expected_quality=0.87 + (i % 4) * 0.02,
        )
        status = "BLOCKED" if r["blocked"] else "ok"
        _print(f"    run {i+1}/{n_v2}: {r['tool']} → {status}")
        time.sleep(0.05)

    if use_llm:
        _print("\n  Phase 4: 1 real LLM research run…")
        from agents.research_team.orchestrator import build_agent
        r = _run_llm_task(
            agent_id=AGENT_ID, contract_yaml=CONTRACT_YAML_V2,
            contract_version="2.0", build_fn=build_agent,
            prompt="Research the latest trends in AI safety and draft a brief executive report.",
            db_url=db_url,
        )
        _print(f"    LLM run → {'BLOCKED' if r['blocked'] else 'ok'}: {r['output'][:80]}…")


SEEDERS = {
    "financial-reader": seed_financial_reader,
    "research-team": seed_research_team,
    "all": None,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed norma demo database with genuine run history.")
    parser.add_argument("--agent", default="financial-reader", choices=list(SEEDERS.keys()))
    parser.add_argument("--llm", action="store_true", help="Use real LLM (requires OPENAI_API_KEY)")
    parser.add_argument("--runs", type=int, default=8, help="Total runs to create per agent")
    parser.add_argument("--approve-contracts-only", action="store_true")
    parser.add_argument("--reset", action="store_true", help="Delete existing data before seeding")
    parser.add_argument("--db-url", default=None)
    args = parser.parse_args()

    db_url = _get_db_url(args.db_url)

    if args.llm and not os.environ.get("OPENAI_API_KEY"):
        _print("ERROR: --llm requires OPENAI_API_KEY to be set.", "red")
        sys.exit(1)

    agents_to_seed = (
        ["financial-reader", "research-team"] if args.agent == "all"
        else [args.agent]
    )

    _print("\n  norma demo_seed.py", "cyan")
    _print(f"  DB: {db_url}")
    _print(f"  Mode: {'LLM' if args.llm else 'Scripted'} | Runs: {args.runs} | Reset: {args.reset}")

    for agent_name in agents_to_seed:
        if args.reset:
            from norma.agents import financial_reader as _fr
            from norma.agents import research_team as _rt
            _shim = _fr if agent_name == "financial-reader" else _rt
            _reset_agent_data(_shim.AGENT_ID, db_url)

        seeder = SEEDERS[agent_name]
        seeder(
            db_url=db_url,
            use_llm=args.llm,
            n_runs=args.runs,
            approve_contracts_only=args.approve_contracts_only,
        )

    _print("\n  Seeding complete.", "green")
    _print("  Dashboard → http://localhost:3030")
    _print("  API       → http://localhost:8080/api/agents\n")


if __name__ == "__main__":
    main()
