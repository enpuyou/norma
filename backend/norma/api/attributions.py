"""Attributions API — fault attribution for multi-agent pipeline failures."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from norma.database import get_db
from norma.models.attribution import AttributionReport
from norma.models.run import Run

router = APIRouter()


@router.get("")
async def list_attributions(
    agent_id: str | None = None,
    limit: int = 50,
    aggregate: bool = True,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return attribution reports, optionally filtered by agent, newest first."""
    stmt = (
        select(AttributionReport)
        .join(Run, Run.id == AttributionReport.run_id)
        .order_by(AttributionReport.run_id.desc())
        .limit(limit)
    )
    if agent_id:
        stmt = stmt.where(Run.agent_id == agent_id)

    result = await db.execute(stmt)
    reports = result.scalars().all()

    if not aggregate:
        return [
            {
                "ticket_id": r.run_id,
                "most_likely_node": r.most_likely_node,
                "confidence": r.confidence,
                "evidence": r.evidence,
            }
            for r in reports
        ]

    grouped: dict[str, dict] = {}
    for report in reports:
        key = report.most_likely_node
        if key not in grouped:
            grouped[key] = {
                "most_likely_node": report.most_likely_node,
                "confidence_sum": 0.0,
                "confidence_count": 0,
                "occurrence_count": 0,
                "ticket_ids": [],
                "latest_ticket_id": report.run_id,
                "evidence": report.evidence,
            }
        entry = grouped[key]
        entry["confidence_sum"] += float(report.confidence or 0.0)
        entry["confidence_count"] += 1
        entry["occurrence_count"] += 1
        entry["ticket_ids"].append(report.run_id)
        if report.run_id > entry["latest_ticket_id"]:
            entry["latest_ticket_id"] = report.run_id
            entry["evidence"] = report.evidence

    sorted_groups = sorted(
        grouped.values(),
        key=lambda item: (item["occurrence_count"], item["latest_ticket_id"]),
        reverse=True,
    )

    return [
        {
            "ticket_id": item["latest_ticket_id"],
            "most_likely_node": item["most_likely_node"],
            "confidence": round(item["confidence_sum"] / item["confidence_count"], 4) if item["confidence_count"] else 0.0,
            "evidence": item["evidence"],
            "occurrence_count": item["occurrence_count"],
            "ticket_ids": item["ticket_ids"],
            "latest_ticket_id": item["latest_ticket_id"],
        }
        for item in sorted_groups
    ]
