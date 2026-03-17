"""Alerts API — violations surfaced as dashboard alerts."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from norma.database import get_db
from norma.models.violation import Violation
from norma.models.agent import Agent

router = APIRouter()

_SEVERITY_MAP = {
    "access_blocked": "critical",
    "tier_revocation": "critical",
    "access_revoked": "warning",
    "output_blocked": "warning",
}

_VP_MSG = {
    "access_blocked": (
        "An agent attempted to access a restricted resource and was blocked. "
        "No data was exposed. Review whether this access pattern reflects a "
        "legitimate task expansion or a contract drift."
    ),
    "tier_revocation": (
        "This agent violated its contract and has been demoted. "
        "Human approval required before re-promotion."
    ),
    "access_revoked": (
        "Agent scope was narrowed after a boundary test. Monitor for recurrence."
    ),
    "output_blocked": (
        "Agent output contained a policy-denied pattern and was redacted before delivery."
    ),
}

_ENG_MSG = {
    "access_blocked": (
        "Policy rule `{rule}` triggered. Action: `{action}`. "
        "The agent requested a resource in a deny-listed path. "
        "Check workflow logic around step that produced this call."
    ),
    "tier_revocation": (
        "Trust score fell below tier floor after rule `{rule}` fired. "
        "Penalty applied. Re-seeding trust requires {n} consecutive clean runs."
    ),
    "access_revoked": (
        "Scope narrowed: rule `{rule}` matched `{action}`. Investigate prompt / tool-chain routing."
    ),
    "output_blocked": (
        "Output filter matched rule `{rule}`. Raw output redacted. Check LLM instruction adherence."
    ),
}


@router.get("")
async def list_alerts(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Return all violations as structured dashboard alerts, newest first."""
    result = await db.execute(
        select(Violation)
        .options(selectinload(Violation.agent))
        .order_by(Violation.id.desc())
    )
    violations = result.scalars().all()

    alerts: list[dict] = []
    for v in violations:
        evt = v.event_type or "access_blocked"
        severity = _SEVERITY_MAP.get(evt, "warning")
        vp_msg = _VP_MSG.get(evt, "A policy violation was recorded.")
        eng_tmpl = _ENG_MSG.get(evt, "Rule `{rule}` triggered for `{action}`.")
        eng_msg = eng_tmpl.format(rule=v.policy_rule, action=v.action_attempted, n=10)

        alerts.append({
            "id": str(v.id),
            "agent_id": v.agent_id,
            "agent_name": v.agent.name if v.agent else v.agent_id,
            "severity": severity,
            "metric": v.policy_rule,
            "current_value": v.action_attempted[:80],
            "baseline": "—",
            "change_pct": 0,
            "window": "realtime",
            "sample_n": 1,
            "contract_change_in_window": False,
            "model_change_in_window": False,
            "vp_message": vp_msg,
            "engineer_message": eng_msg,
            "timestamp": v.timestamp.isoformat() if v.timestamp else "",
        })

    return alerts
