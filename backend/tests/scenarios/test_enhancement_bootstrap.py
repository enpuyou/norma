from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

from norma.api.agents import apply_enhancement_to_contract
from norma.models.agent import Agent
from norma.models.contract import Contract


def _seed_agent_without_contract(db_url: str, agent_id: str = "enhancement-bootstrap-agent") -> None:
    engine = create_engine(db_url)
    with SyncSession(engine) as db:
        if not db.get(Agent, agent_id):
            db.add(
                Agent(
                    agent_id=agent_id,
                    name="Enhancement Bootstrap Agent",
                    type="single",
                    trust_score=0.40,
                    enabled=True,
                )
            )
            db.commit()
    engine.dispose()


@pytest.mark.asyncio
async def test_enhancement_apply_bootstraps_contract_when_missing(scenario_db: str) -> None:
    agent_id = "enhancement-bootstrap-agent"
    _seed_agent_without_contract(scenario_db, agent_id=agent_id)

    async_engine = create_async_engine(scenario_db.replace("sqlite:///", "sqlite+aiosqlite:///"))
    SessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        result = await apply_enhancement_to_contract(
            agent_id=agent_id,
            payload={
                "yaml_snippet": "enforcement:\n  deny:\n  - reports/confidential/**",
                "recommendation_type": "violation_pattern",
                "applied_by": "admin",
            },
            db=db,
        )

    assert result["status"] == "applied"
    assert result["created_new_proposal"] is True
    assert result["bootstrapped_contract"] is True
    assert result["contract_version"] == "1.0"

    verify_engine = create_engine(scenario_db)
    with SyncSession(verify_engine) as verify_db:
        contracts = verify_db.query(Contract).filter(Contract.agent_id == agent_id).all()
        assert len(contracts) == 1
        assert contracts[0].version == "1.0"
        assert "reports/confidential/**" in contracts[0].yaml_content
    verify_engine.dispose()

    await async_engine.dispose()
