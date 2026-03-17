from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

# Test-suite constant — not imported from agent file (agent is norma-unaware)
AGENT_ID = "financial-reader-v1"
from norma.api.agents import execute_agent_task, replay_agent_run
from norma.config import get_settings
from norma.models.agent import Agent
from norma.models.run import Run


def _seed_agent(db_url: str) -> None:
    """Insert the financial-reader-v1 agent row with entry_point so execute works."""
    from pathlib import Path
    # Resolve the real entry point path
    # test_run_replay.py → scenarios/ → tests/ → backend/ → norma/ (4 parents)
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    entry_point = str(project_root / "agents" / "financial_reader" / "earnings_report_reader.py")

    engine = create_engine(db_url)
    with SyncSession(engine) as db:
        existing = db.get(Agent, AGENT_ID)
        if not existing:
            db.add(Agent(
                agent_id=AGENT_ID,
                name="Financial Reader",
                type="single",
                current_tier="restricted",
                trust_score=0.40,
                enabled=True,
                entry_point=entry_point,
            ))
        else:
            existing.entry_point = entry_point
        db.commit()

        # Seed a contract so execute endpoint can proceed (contract required by DB-driven path)
        from norma.agents.financial_reader import CONTRACT_YAML
        from norma.models.contract import Contract
        from datetime import datetime, timezone
        existing_contract = db.query(Contract).filter(Contract.agent_id == AGENT_ID).first()
        if not existing_contract:
            db.add(Contract(
                agent_id=AGENT_ID,
                version="1.0",
                yaml_content=CONTRACT_YAML,
                is_active=True,
                created_by="test-seed",
                approved_by="test-seed",
                activated_at=datetime.now(timezone.utc),
            ))
            db.commit()
    engine.dispose()



@pytest.mark.asyncio
async def test_replay_runs_full_sequence_with_current_contract(
    scenario_db: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_agent(scenario_db)

    settings = get_settings()
    async_db_url = scenario_db.replace("sqlite:///", "sqlite+aiosqlite:///")
    monkeypatch.setattr(settings, "database_url", async_db_url)

    async_engine = create_async_engine(async_db_url)
    SessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        await execute_agent_task(
            agent_id=AGENT_ID,
            mode="step",
            body={"tool": "list_reports"},  # use no-arg tool to avoid validation error
            db=db,
        )

        source_result = await db.execute(
            select(Run.id)
            .where(Run.agent_id == AGENT_ID)
            .order_by(Run.id.desc())
            .limit(1)
        )
        source_run_id = source_result.scalar_one()

        replay = await replay_agent_run(
            agent_id=AGENT_ID,
            source_run_id=source_run_id,
            db=db,
        )

        assert replay["replayed"] is True
        assert replay["source_run_id"] == source_run_id
        assert replay["replay_mode"] == "full"
        assert replay["execution"]["mode"] == "full"
        assert replay["execution"]["total_tasks"] > 0
        assert replay["created_runs"] == replay["execution"]["total_tasks"]

    await async_engine.dispose()
