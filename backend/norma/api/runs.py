"""Runs API — execution telemetry, per-run detail, context metrics, spans."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from norma.database import get_db
from norma.models.run import Run
from norma.models.run_step import RunStep
from norma.models.span import Span
from norma.models.context_metric import ContextMetric
from norma.models.observability import PromptSnapshot

router = APIRouter()


# ─── Remote telemetry ingest ──────────────────────────────────────────────────

class IngestSpan(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    span_type: str
    name: str
    status: str = "ok"
    start_time: str | None = None
    end_time: str | None = None
    input_data: Any = None
    output_data: Any = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    model_name: str | None = None
    attributes: dict | None = None


class IngestViolation(BaseModel):
    policy_rule: str
    action_attempted: str
    blocked: bool = True
    event_type: str = "access_blocked"


class IngestRunPayload(BaseModel):
    agent_id: str
    contract_version: str = "1.0"
    parent_run_id: int | None = None
    initiated_by: str | None = None
    session_id: str | None = None
    framework: str = "generic"
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    quality_score: float | None = None
    quality_rationale: str | None = None
    quality_breakdown: dict | None = None
    completion_status: str = "success"
    violations: list[IngestViolation] = []
    spans: list[IngestSpan] = []


@router.post("/ingest")
async def ingest_run(
    payload: IngestRunPayload,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Accept a run telemetry payload from a remote agent.

    Agents running outside the norma platform can POST here to persist runs,
    violations, and spans without needing direct DB access.
    Trust scoring and SSE broadcasts are handled server-side.
    """
    from datetime import datetime
    from norma.models.agent import Agent
    from norma.models.violation import Violation
    from norma.models.run_step import RunStep as RunStepModel
    from norma.core.trust_engine import TrustState, record_clean_run, record_violation

    # Ensure agent exists
    agent_result = await db.execute(select(Agent).where(Agent.agent_id == payload.agent_id))
    agent_row = agent_result.scalar_one_or_none()
    if agent_row is None:
        agent_row = Agent(
            agent_id=payload.agent_id,
            name=payload.agent_id,
            type="single",
            current_tier="restricted",
            trust_score=0.40,
            enabled=True,
        )
        db.add(agent_row)
        await db.flush()

    quality_breakdown_json = (
        json.dumps(payload.quality_breakdown) if payload.quality_breakdown else None
    )

    run = Run(
        agent_id=payload.agent_id,
        parent_run_id=payload.parent_run_id,
        initiated_by=payload.initiated_by,
        session_id=payload.session_id,
        contract_version=payload.contract_version,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cost_usd=round(payload.cost_usd, 5),
        latency_ms=payload.latency_ms,
        quality_score=payload.quality_score,
        quality_rationale=payload.quality_rationale,
        quality_breakdown=quality_breakdown_json,
        trust_score_after=0.0,
        completion_status=payload.completion_status,
        timestamp=datetime.utcnow(),
    )
    db.add(run)
    await db.flush()

    # Trust engine
    trust_state = TrustState(
        agent_id=payload.agent_id,
        trust_score=agent_row.trust_score,
        clean_run_count=agent_row.clean_run_count,
    )
    trust_state.current_tier = agent_row.current_tier

    if payload.violations:
        record_violation(trust_state, resource=payload.violations[0].action_attempted, run_id=run.id)
    else:
        record_clean_run(trust_state, run_id=run.id)

    run.trust_score_after = trust_state.trust_score
    agent_row.trust_score = trust_state.trust_score
    agent_row.current_tier = trust_state.current_tier
    agent_row.clean_run_count = trust_state.clean_run_count

    for v in payload.violations:
        db.add(Violation(
            run_id=run.id,
            agent_id=payload.agent_id,
            policy_rule=v.policy_rule,
            action_attempted=v.action_attempted,
            blocked=v.blocked,
            event_type=v.event_type,
            timestamp=datetime.utcnow(),
        ))

    for span in payload.spans:
        from datetime import timezone

        def _parse_dt(s: str | None):
            if not s:
                return None
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                return None

        db.add(Span(
            span_id=span.span_id,
            trace_id=run.id,
            parent_span_id=span.parent_span_id,
            span_type=span.span_type,
            name=span.name,
            status=span.status,
            start_time=_parse_dt(span.start_time),
            end_time=_parse_dt(span.end_time),
            input_data=json.dumps(span.input_data) if span.input_data else None,
            output_data=json.dumps(span.output_data) if span.output_data else None,
            tokens_in=span.tokens_in,
            tokens_out=span.tokens_out,
            cost_usd=span.cost_usd,
            latency_ms=span.latency_ms,
            model_name=span.model_name,
            attributes=json.dumps(span.attributes) if span.attributes else None,
            timestamp=datetime.utcnow(),
        ))

    await db.commit()

    # SSE broadcast
    try:
        from norma.api.events import broadcast
        broadcast("run_completed", {
            "agent_id": payload.agent_id,
            "run_id": run.id,
            "status": payload.completion_status,
            "quality_score": payload.quality_score,
            "trust_score_after": trust_state.trust_score,
            "latency_ms": payload.latency_ms,
            "framework": payload.framework,
            "source": "remote_ingest",
        })
    except Exception:
        pass

    return {
        "status": "ok",
        "run_id": run.id,
        "agent_id": payload.agent_id,
        "trust_score_after": trust_state.trust_score,
        "trust_tier": trust_state.current_tier,
    }


def _run_to_dict(run: Run) -> dict:
    return {
        "id": run.id,
        "agent_id": run.agent_id,
        "parent_run_id": run.parent_run_id,
        "initiated_by": run.initiated_by,
        "contract_version": run.contract_version,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_usd": run.cost_usd,
        "latency_ms": run.latency_ms,
        "quality_score": run.quality_score,
        "quality_rationale": run.quality_rationale,
        "quality_breakdown": _parse_json_field(run.quality_breakdown),
        "trust_score_after": run.trust_score_after,
        "completion_status": run.completion_status,
        "timestamp": run.timestamp.isoformat() if run.timestamp else None,
        "violations": [
            {
                "policy_rule": v.policy_rule,
                "action_attempted": v.action_attempted,
                "blocked": v.blocked,
                "event_type": v.event_type,
            }
            for v in run.violations
        ],
        "context_metrics": [
            {
                "subagent_id": cm.subagent_id,
                "tokens_available": cm.tokens_available,
                "tokens_sent": cm.tokens_sent,
                "utilization_ratio": cm.utilization_ratio,
                "routing_rules_applied": cm.routing_rules_applied,
            }
            for cm in run.context_metrics
        ],
    }


@router.get("/")
async def list_runs(
    agent_id: str | None = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return runs, optionally filtered by agent, newest first."""
    stmt = (
        select(Run)
        .options(
            selectinload(Run.violations),
            selectinload(Run.context_metrics),
        )
        .order_by(Run.id.desc())
        .limit(limit)
    )
    if agent_id:
        stmt = stmt.where(Run.agent_id == agent_id)

    result = await db.execute(stmt)
    runs = result.scalars().all()
    return [_run_to_dict(r) for r in runs]


@router.get("/{run_id}")
async def get_run(run_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Return full run detail including violations and context metrics."""
    result = await db.execute(
        select(Run)
        .where(Run.id == run_id)
        .options(
            selectinload(Run.violations),
            selectinload(Run.context_metrics),
        )
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_to_dict(run)


@router.get("/{run_id}/tree")
async def get_run_tree(run_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Return the full parent-child execution tree rooted at run_id."""
    # Load all runs and build tree
    result = await db.execute(
        select(Run)
        .options(
            selectinload(Run.violations),
            selectinload(Run.context_metrics),
        )
    )
    all_runs = result.scalars().all()
    run_map = {r.id: r for r in all_runs}

    root = run_map.get(run_id)
    if not root:
        raise HTTPException(status_code=404, detail="Run not found")

    def _build_node(run: Run) -> dict:
        children_runs = [r for r in all_runs if r.parent_run_id == run.id]
        return {
            **_run_to_dict(run),
            "children": [_build_node(c) for c in sorted(children_runs, key=lambda r: r.id)],
        }

    return _build_node(root)


@router.get("/{run_id}/steps")
async def get_run_steps(run_id: int, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Return all per-tool-call trace records for a run, in step order."""
    # Verify run exists
    run_result = await db.execute(select(Run).where(Run.id == run_id))
    if not run_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Run not found")

    result = await db.execute(
        select(RunStep)
        .where(RunStep.run_id == run_id)
        .order_by(RunStep.step_index)
    )
    steps = result.scalars().all()
    return [
        {
            "id": s.id,
            "run_id": s.run_id,
            "step_index": s.step_index,
            "tool_name": s.tool_name,
            "input_text": s.input_text,
            "output_text": s.output_text,
            "latency_ms": s.latency_ms,
            "blocked": s.blocked,
            "policy_rule": s.policy_rule,
            "timestamp": s.timestamp.isoformat() if s.timestamp else None,
        }
        for s in steps
    ]


def _parse_json_field(val: Any) -> Any:
    """Parse a JSON text field, returning the value or None."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val


def _span_to_dict(span: Span) -> dict:
    return {
        "id": span.id,
        "span_id": span.span_id,
        "trace_id": span.trace_id,
        "parent_span_id": span.parent_span_id,
        "span_type": span.span_type,
        "name": span.name,
        "status": span.status,
        "start_time": span.start_time.isoformat() if span.start_time else None,
        "end_time": span.end_time.isoformat() if span.end_time else None,
        "input_data": _parse_json_field(span.input_data),
        "output_data": _parse_json_field(span.output_data),
        "tokens_in": span.tokens_in,
        "tokens_out": span.tokens_out,
        "cost_usd": span.cost_usd,
        "latency_ms": span.latency_ms,
        "attributes": _parse_json_field(span.attributes),
        "timestamp": span.timestamp.isoformat() if span.timestamp else None,
    }


@router.get("/{run_id}/metrics")
async def get_run_metrics(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return per-run metric summary computed from spans."""
    run_result = await db.execute(select(Run).where(Run.id == run_id))
    run = run_result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    span_result = await db.execute(select(Span).where(Span.trace_id == run_id))
    spans = span_result.scalars().all()

    llm_spans = [s for s in spans if s.span_type == "llm_call"]
    tool_spans = [s for s in spans if s.span_type == "tool_call"]

    total_in = sum(s.tokens_in or 0 for s in llm_spans)
    total_out = sum(s.tokens_out or 0 for s in llm_spans)
    total_cost = round(sum(s.cost_usd or 0.0 for s in spans), 8)
    llm_latency = [s.latency_ms for s in llm_spans if s.latency_ms is not None]
    tool_latency = [s.latency_ms for s in tool_spans if s.latency_ms is not None]
    context_utils = []
    quality_subscores = []

    for span in llm_spans:
        attrs = _parse_json_field(span.attributes) or {}
        if isinstance(attrs, dict):
            cu = attrs.get("context_utilization_ratio")
            qs = attrs.get("quality_subscore")
            if isinstance(cu, (float, int)):
                context_utils.append(float(cu))
            if isinstance(qs, (float, int)):
                quality_subscores.append(float(qs))

    framework = None
    session_span = next((s for s in spans if s.span_type == "session"), None)
    if session_span is not None:
        attrs = _parse_json_field(session_span.attributes) or {}
        if isinstance(attrs, dict):
            framework = attrs.get("framework")

    return {
        "run_id": run_id,
        "agent_id": run.agent_id,
        "framework": framework,
        "token_metrics": {
            "input_tokens": total_in,
            "output_tokens": total_out,
            "total_tokens": total_in + total_out,
        },
        "cost_metrics": {
            "total_cost_usd": total_cost,
            "llm_cost_usd": round(sum(s.cost_usd or 0.0 for s in llm_spans), 8),
            "tool_cost_usd": round(sum(s.cost_usd or 0.0 for s in tool_spans), 8),
        },
        "latency_metrics": {
            "run_latency_ms": run.latency_ms,
            "avg_llm_latency_ms": int(sum(llm_latency) / len(llm_latency)) if llm_latency else 0,
            "avg_tool_latency_ms": int(sum(tool_latency) / len(tool_latency)) if tool_latency else 0,
        },
        "quality_metrics": {
            "run_quality_score": run.quality_score,
            "quality_rationale": run.quality_rationale,
            "quality_breakdown": _parse_json_field(run.quality_breakdown),
            "avg_llm_quality_subscore": round(sum(quality_subscores) / len(quality_subscores), 4)
            if quality_subscores
            else None,
        },
        "context_metrics": {
            "avg_context_utilization_ratio": round(sum(context_utils) / len(context_utils), 6)
            if context_utils
            else None,
            "max_context_utilization_ratio": round(max(context_utils), 6) if context_utils else None,
        },
    }


@router.get("/{run_id}/spans")
async def get_run_spans(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return all spans for a run as a flat list and as a nested tree."""
    # Verify run exists
    run_result = await db.execute(select(Run).where(Run.id == run_id))
    if not run_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Run not found")

    result = await db.execute(
        select(Span)
        .where(Span.trace_id == run_id)
        .order_by(Span.id)
    )
    spans = result.scalars().all()
    flat = [_span_to_dict(s) for s in spans]

    # Build tree
    by_span_id: dict[str, dict] = {}
    roots: list[dict] = []
    for s in flat:
        node = {**s, "children": []}
        by_span_id[s["span_id"]] = node

    for node in by_span_id.values():
        parent = node.get("parent_span_id")
        if parent and parent in by_span_id:
            by_span_id[parent]["children"].append(node)
        else:
            roots.append(node)

    return {
        "run_id": run_id,
        "span_count": len(flat),
        "spans": flat,
        "tree": roots,
    }


@router.get("/{run_id}/prompts")
async def get_run_prompts(
    run_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return all prompt snapshots for a given run, ordered chronologically by span."""
    result = await db.execute(select(Run).where(Run.id == run_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Run not found")

    result = await db.execute(
        select(PromptSnapshot)
        .where(PromptSnapshot.run_id == run_id)
        .order_by(PromptSnapshot.id)
    )
    snapshots = result.scalars().all()

    return [
        {
            "id": snap.id,
            "span_id": snap.span_id,
            "role": snap.role,
            "content": snap.content,
            "token_count": snap.token_count,
            "created_at": snap.created_at.isoformat() if snap.created_at else None,
        }
        for snap in snapshots
    ]
