"""Telemetry Ingest API — external agents push spans via HTTP.

Allows any agent running outside the norma web server to report runs and spans
to the dashboard by posting to POST /api/telemetry/ingest.

Authentication: optional API key via X-Norma-Key header (when enable_api_key_auth=True).
No API key requirement in dev mode.

Payload schema:
    {
        "agent_id": str,
        "framework": str,                    # "langchain" | "openai_agents" | "openai_func" | "custom"
        "contract_version": str | null,
        "initiated_by": str | null,          # "user" | "api" | "orchestrator:..."
        "session_id": str | null,
        "parent_run_id": int | null,
        "run_status": str,                   # "success" | "failed" | "timeout"
        "quality_score": float | null,
        "cost_usd": float | null,
        "latency_ms": int | null,
        "input_tokens": int | null,
        "output_tokens": int | null,
        "spans": [
            {
                "span_id": str | null,
                "parent_span_id": str | null,
                "span_type": str,            # "llm_call" | "tool_call" | "agent_handoff" | ...
                "name": str,
                "status": str,               # "ok" | "error" | "blocked"
                "start_time": str | null,    # ISO8601
                "end_time": str | null,
                "input_data": str | null,
                "output_data": str | null,
                "tokens_in": int | null,
                "tokens_out": int | null,
                "cost_usd": float | null,
                "latency_ms": int | null,
                "model_name": str | null,
                "attributes": dict | null,
            }
        ],
    }
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from norma.config import get_settings
from norma.database import get_db
from norma.models.agent import Agent
from norma.models.run import Run
from norma.models.span import Span

log = structlog.get_logger()
router = APIRouter()


# ─── Request models ───────────────────────────────────────────────────────────

class SpanPayload(BaseModel):
    span_id: str | None = None
    parent_span_id: str | None = None
    span_type: str = "tool_call"
    name: str
    status: str = "ok"
    start_time: str | None = None
    end_time: str | None = None
    input_data: str | None = None
    output_data: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    model_name: str | None = None
    attributes: dict[str, Any] | None = None


class IngestPayload(BaseModel):
    agent_id: str
    framework: str = "custom"
    contract_version: str | None = None
    initiated_by: str | None = "api"
    session_id: str | None = None
    parent_run_id: int | None = None
    run_status: str = "success"
    quality_score: float | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    spans: list[SpanPayload] = []


class IngestResponse(BaseModel):
    run_id: int
    spans_accepted: int
    agent_id: str
    status: str


# ─── Auth helper ──────────────────────────────────────────────────────────────

def _check_api_key(request: Request) -> None:
    settings = get_settings()
    if not settings.enable_api_key_auth:
        return  # dev mode — no auth required
    key = request.headers.get("X-Norma-Key", "").strip()
    if not key:
        raise HTTPException(status_code=401, detail="X-Norma-Key header required")
    import json
    try:
        valid_keys = json.loads(settings.api_keys_json)
    except Exception:
        valid_keys = {}
    if key not in valid_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")


# ─── Auto-create agent if not registered ─────────────────────────────────────

async def _ensure_agent(agent_id: str, framework: str, db: AsyncSession) -> Agent:
    result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        agent = Agent(
            agent_id=agent_id,
            name=agent_id.replace("-", " ").title(),
            type="single",
            agent_type="standard",
            framework=framework,
            current_tier="restricted",
            trust_score=0.40,
            enabled=True,
        )
        db.add(agent)
        await db.flush()
        log.info("norma: auto-created agent from telemetry ingest", agent_id=agent_id)
    return agent


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse)
async def ingest_telemetry(
    payload: IngestPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> IngestResponse:
    """Ingest telemetry from an external agent and persist as Run + Spans.

    External agents can call this endpoint from anywhere (terminal, cron job,
    cloud function) and their runs will appear in the norma dashboard.
    """
    _check_api_key(request)

    agent = await _ensure_agent(payload.agent_id, payload.framework, db)

    # Create the Run row
    run = Run(
        agent_id=agent.agent_id,
        parent_run_id=payload.parent_run_id,
        initiated_by=payload.initiated_by or "api",
        contract_version=payload.contract_version or "external",
        session_id=payload.session_id,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cost_usd=payload.cost_usd,
        latency_ms=payload.latency_ms,
        quality_score=payload.quality_score,
        completion_status=payload.run_status,
    )
    db.add(run)
    await db.flush()  # get run.id

    # Create Span rows
    spans_added = 0
    for sp in payload.spans:
        def _parse_dt(s: str | None) -> datetime | None:
            if not s:
                return None
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None

        import json as _json
        attributes_str: str | None = None
        if sp.attributes:
            try:
                attrs = dict(sp.attributes)
                if sp.model_name:
                    attrs["model_name"] = sp.model_name
                attributes_str = _json.dumps(attrs)
            except Exception:
                attributes_str = None
        elif sp.model_name:
            attributes_str = _json.dumps({"model_name": sp.model_name})

        span = Span(
            span_id=sp.span_id or uuid.uuid4().hex[:16],
            trace_id=run.id,
            parent_span_id=sp.parent_span_id,
            span_type=sp.span_type,
            name=sp.name,
            status=sp.status,
            start_time=_parse_dt(sp.start_time) or datetime.utcnow(),
            end_time=_parse_dt(sp.end_time),
            input_data=sp.input_data,
            output_data=sp.output_data,
            tokens_in=sp.tokens_in,
            tokens_out=sp.tokens_out,
            cost_usd=sp.cost_usd,
            latency_ms=sp.latency_ms,
            attributes=attributes_str,
        )
        db.add(span)
        spans_added += 1

    await db.commit()

    log.info(
        "norma: telemetry ingested",
        agent_id=payload.agent_id,
        run_id=run.id,
        spans=spans_added,
        status=payload.run_status,
    )

    return IngestResponse(
        run_id=run.id,
        spans_accepted=spans_added,
        agent_id=payload.agent_id,
        status="ok",
    )


@router.get("/ingest/status")
async def ingest_status() -> dict:
    """Health check for the telemetry ingest endpoint."""
    settings = get_settings()
    return {
        "status": "ok",
        "auth_required": settings.enable_api_key_auth,
        "endpoint": "POST /api/telemetry/ingest",
    }
