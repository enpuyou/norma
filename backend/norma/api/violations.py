"""Violations API — enforcement event log and compliance audit."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from norma.database import get_db
from norma.models.violation import Violation

router = APIRouter()


def _review_status_from_scope(scope: str | None) -> str | None:
    if not scope:
        return None
    if scope.startswith("review:acknowledged"):
        return "acknowledged"
    if scope.startswith("review:dismissed_false_positive"):
        return "dismissed_false_positive"
    return None


def _violation_to_dict(v: Violation) -> dict:
    review_status = _review_status_from_scope(v.scope)
    return {
        "id": v.id,
        "run_id": v.run_id,
        "agent_id": v.agent_id,
        "policy_rule": v.policy_rule,
        "action_attempted": v.action_attempted,
        "blocked": v.blocked,
        "event_type": v.event_type,
        "scope": v.scope,
        "review_status": review_status,
        "timestamp": v.timestamp.isoformat() if v.timestamp else None,
    }


@router.get("/")
async def list_violations(
    agent_id: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return recent enforcement events, optionally filtered by agent."""
    stmt = (
        select(Violation)
        .order_by(Violation.id.desc())
        .limit(limit)
    )
    if agent_id:
        stmt = stmt.where(Violation.agent_id == agent_id)

    result = await db.execute(stmt)
    violations = result.scalars().all()
    return [_violation_to_dict(v) for v in violations]


@router.get("/{agent_id}/audit")
async def audit_log(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Full compliance audit log for an agent — all violations with run context."""
    result = await db.execute(
        select(Violation)
        .where(Violation.agent_id == agent_id)
        .order_by(Violation.id.desc())
    )
    violations = result.scalars().all()

    return {
        "agent_id": agent_id,
        "total_violations": len(violations),
        "entries": [_violation_to_dict(v) for v in violations],
    }


@router.post("/{violation_id}/review")
async def review_violation(
    violation_id: int,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mark a violation as acknowledged or dismissed as false positive."""
    decision = (payload.get("decision") or "").strip()
    reviewer = (payload.get("reviewer") or "dashboard-user").strip()
    note = (payload.get("note") or "").strip()

    if decision not in {"acknowledged", "dismissed_false_positive"}:
        raise HTTPException(
            status_code=422,
            detail="decision must be one of: acknowledged, dismissed_false_positive",
        )

    result = await db.execute(select(Violation).where(Violation.id == violation_id))
    violation = result.scalar_one_or_none()
    if not violation:
        raise HTTPException(status_code=404, detail="Violation not found")

    stamp = datetime.now(timezone.utc).isoformat()
    note_part = note.replace("|", "/") if note else ""
    violation.scope = f"review:{decision}|by:{reviewer}|at:{stamp}|note:{note_part}"
    await db.commit()

    return {
        "status": "updated",
        "violation_id": violation_id,
        "decision": decision,
        "reviewer": reviewer,
        "timestamp": stamp,
    }
