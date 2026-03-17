from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

from norma.api.agents import get_agent_metric_trends
from norma.api.runs import get_run_metrics
from norma.integrations.session import CircuitBreakerError, NormaAgentSession
from norma.models.agent import Agent
from norma.models.budget import Budget
from norma.models.run import Run
from norma.models.span import Span


CONTRACT_YAML = yaml.dump(
    {
        "agent_id": "phase3-agent",
        "authorities": {
            "tools": {"allow": ["list_reports"], "deny": []},
            "data": {"allow": ["data/public/*"], "deny": ["data/confidential/*"]},
        },
        "sla": {
            "max_latency_ms": 5000,
            "max_cost_per_run": 10.0,
            "max_tool_calls_per_run": 20,
        },
        "trust": {
            "clean_run_increment": 0.025,
            "violation_penalty": 0.25,
            "tier_thresholds": {
                "standard": {"min_score": 0.65, "min_clean_runs": 10},
                "trusted": {"min_score": 0.82, "min_clean_runs": 20},
            },
        },
    }
)


def _seed_agent(db_url: str, agent_id: str = "phase3-agent") -> None:
    engine = create_engine(db_url)
    with SyncSession(engine) as db:
        if not db.get(Agent, agent_id):
            db.add(
                Agent(
                    agent_id=agent_id,
                    name="Phase 3 Agent",
                    type="single",
                    trust_score=0.40,
                    enabled=True,
                )
            )
            db.commit()
    engine.dispose()


@pytest.mark.asyncio
async def test_run_metrics_endpoint_includes_phase3_fields(scenario_db: str) -> None:
    _seed_agent(scenario_db)

    with NormaAgentSession(
        agent_id="phase3-agent",
        contract_yaml=CONTRACT_YAML,
        db_url=scenario_db,
        check_enabled=False,
    ) as sess:
        sess.record_llm_call(
            model="gpt-4o",
            input_data={"prompt": "Summarize Q4 earnings"},
            output_text="Revenue increased and margin expanded.",
            tokens_in=1200,
            tokens_out=300,
        )

    sync_engine = create_engine(scenario_db)
    with SyncSession(sync_engine) as db:
        run_id = db.query(Run).filter(Run.agent_id == "phase3-agent").order_by(Run.id.desc()).first().id
    sync_engine.dispose()

    async_engine = create_async_engine(scenario_db.replace("sqlite:///", "sqlite+aiosqlite:///"))
    SessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        metrics = await get_run_metrics(run_id, db)

    await async_engine.dispose()

    assert metrics["token_metrics"]["input_tokens"] == 1200
    assert metrics["token_metrics"]["output_tokens"] == 300
    assert metrics["cost_metrics"]["total_cost_usd"] > 0
    assert metrics["context_metrics"]["avg_context_utilization_ratio"] is not None
    assert metrics["quality_metrics"]["avg_llm_quality_subscore"] is not None


@pytest.mark.asyncio
async def test_agent_trends_endpoint_returns_context_series(scenario_db: str) -> None:
    _seed_agent(scenario_db)

    sync_engine = create_engine(scenario_db)
    with SyncSession(sync_engine) as db:
        run = Run(
            agent_id="phase3-agent",
            contract_version="1.0",
            input_tokens=100,
            output_tokens=20,
            cost_usd=0.001,
            latency_ms=150,
            quality_score=0.82,
            trust_score_after=0.43,
            completion_status="success",
            timestamp=datetime.now(timezone.utc),
        )
        db.add(run)
        db.flush()
        db.add(
            Span(
                span_id="abc123def4567890",
                trace_id=run.id,
                parent_span_id=None,
                span_type="llm_call",
                name="gpt-4o",
                status="ok",
                start_time=datetime.now(timezone.utc),
                end_time=datetime.now(timezone.utc),
                tokens_in=100,
                tokens_out=20,
                cost_usd=0.001,
                latency_ms=100,
                attributes=json.dumps({"context_utilization_ratio": 0.15, "quality_subscore": 0.9}),
            )
        )
        db.commit()
    sync_engine.dispose()

    async_engine = create_async_engine(scenario_db.replace("sqlite:///", "sqlite+aiosqlite:///"))
    SessionLocal = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as db:
        trends = await get_agent_metric_trends("phase3-agent", days=30, db=db)

    await async_engine.dispose()

    assert trends["agent_id"] == "phase3-agent"
    assert len(trends["points"]) >= 1
    assert trends["points"][0]["avg_context_utilization_ratio"] is not None


def test_budget_hard_limit_blocks_new_run(scenario_db: str) -> None:
    _seed_agent(scenario_db)

    engine = create_engine(scenario_db)
    with SyncSession(engine) as db:
        db.add(
            Budget(
                agent_id="phase3-agent",
                period="monthly",
                max_cost_usd=0.01,
                max_runs=10,
                enabled=True,
            )
        )
        db.add(
            Run(
                agent_id="phase3-agent",
                contract_version="1.0",
                cost_usd=0.02,
                completion_status="success",
                timestamp=datetime.utcnow(),
            )
        )
        db.commit()
    engine.dispose()

    with pytest.raises(CircuitBreakerError):
        with NormaAgentSession(
            agent_id="phase3-agent",
            contract_yaml=CONTRACT_YAML,
            db_url=scenario_db,
            check_enabled=False,
        ):
            pass
