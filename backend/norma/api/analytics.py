"""Analytics API — performance metrics, version comparison, anomaly alerting, recommendations.

All insights state the specific metric, a confidence level,
and what cannot be determined from the available data.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from norma.database import get_db
from norma.models.agent import Agent
from norma.models.contract import Contract
from norma.models.run import Run
from norma.models.span import Span

router = APIRouter()


def _to_utc_iso(dt: datetime) -> str:
    """Serialize a datetime to UTC ISO-8601 with Z suffix.

    SQLite stores datetimes as naive UTC. We attach UTC tzinfo so browsers
    parse the timestamp correctly instead of treating it as local time.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


async def _load_agent(agent_id: str, db: AsyncSession) -> Agent:
    result = await db.execute(
        select(Agent)
        .where(Agent.agent_id == agent_id)
        .options(
            selectinload(Agent.runs).selectinload(Run.violations),
            selectinload(Agent.contracts),
            selectinload(Agent.violations),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/{agent_id}/metrics")
async def get_metrics(
    agent_id: str,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregated performance metrics: quality-adjusted cost, trust trajectory, latency."""
    agent = await _load_agent(agent_id, db)
    runs = sorted(agent.runs, key=lambda r: r.id)
    successful = [r for r in runs if r.completion_status == "success"]
    failed = [r for r in runs if r.completion_status == "failed"]

    quality_scores = [r.quality_score for r in successful if r.quality_score is not None]
    costs = [r.cost_usd for r in successful if r.cost_usd is not None]
    latencies = sorted([r.latency_ms for r in runs if r.latency_ms is not None])
    trust_series = [r.trust_score_after for r in runs if r.trust_score_after is not None]

    avg_quality = statistics.mean(quality_scores) if quality_scores else 0.0
    avg_cost = statistics.mean(costs) if costs else 0.0
    quality_adj_cost = avg_cost / avg_quality if avg_quality > 0 else 0.0

    mid = len(costs) // 2
    cost_wow = None
    if len(costs) >= 4:
        m1 = statistics.mean(costs[:mid])
        m2 = statistics.mean(costs[mid:])
        cost_wow = (m2 - m1) / m1 if m1 > 0 else None

    trust_start = trust_series[0] if trust_series else agent.trust_score
    trust_end = trust_series[-1] if trust_series else agent.trust_score

    # Build version checkpoints: contract changes + model/code changes
    # Primary: activated contracts (have explicit activation timestamp)
    # Fallback: detect contract_version transitions across runs (ordered by time)
    activated_contracts = sorted(
        [c for c in agent.contracts if c.activated_at is not None],
        key=lambda c: c.activated_at,
    )
    version_checkpoints = [
        {
            "timestamp": _to_utc_iso(c.activated_at),
            "contract_version": c.version,
            "approved_by": c.approved_by,
            "change_type": "contract",
            "display_label": f"contract v{c.version}",
        }
        for c in activated_contracts
    ]

    # If fewer checkpoints than distinct versions seen in runs, fill in from run history
    runs_with_ts = [r for r in runs if r.timestamp and r.contract_version]
    if runs_with_ts:
        runs_with_ts_sorted = sorted(runs_with_ts, key=lambda r: r.timestamp)
        seen_versions_in_checkpoints = {cp["contract_version"] for cp in version_checkpoints}
        prev_version: str | None = None
        for r in runs_with_ts_sorted:
            v = r.contract_version
            if v != prev_version and v not in seen_versions_in_checkpoints:
                version_checkpoints.append({
                    "timestamp": _to_utc_iso(r.timestamp),
                    "contract_version": v,
                    "approved_by": None,
                    "change_type": "contract",
                    "display_label": f"contract v{v}",
                })
                seen_versions_in_checkpoints.add(v)
            prev_version = v

    # Detect model changes: query the first llm_call span per run, detect transitions
    # Use all runs with timestamps (not just those with contract_version) so model
    # changes are picked up even when contract_version is unset.
    all_runs_with_ts = [r for r in runs if r.timestamp]
    run_ids = [r.id for r in all_runs_with_ts] if all_runs_with_ts else []
    if run_ids:
        model_rows = await db.execute(
            select(Span.trace_id, Span.name, Span.start_time)
            .where(
                Span.trace_id.in_(run_ids),
                Span.span_type == "llm_call",
            )
            .order_by(Span.trace_id, Span.id)
        )
        # Build trace_id (= run.id) → first model name used
        run_model: dict[int, tuple[str, object]] = {}
        for row in model_rows:
            if row.trace_id not in run_model:
                run_model[row.trace_id] = (row.name, row.start_time)

        # Walk runs in time order, emit checkpoint on first model change
        prev_model: str | None = None
        runs_with_ts_sorted2 = sorted(all_runs_with_ts, key=lambda r: r.timestamp)
        for r in runs_with_ts_sorted2:
            model_info = run_model.get(r.id)  # r.id == trace_id
            if model_info:
                model_name, _ = model_info
                if model_name != prev_model and prev_model is not None:
                    version_checkpoints.append({
                        "timestamp": _to_utc_iso(r.timestamp),
                        "contract_version": r.contract_version or "?",
                        "approved_by": None,
                        "change_type": "model",
                        "display_label": model_name,
                    })
                prev_model = model_name

    # Add code version change checkpoint when agent has a detected change
    # last_seen_at is set to now() by check-changes when code_status becomes "changed"
    if agent.code_status == "changed" and agent.last_seen_at is not None:
        code_ts = _to_utc_iso(agent.last_seen_at)
        # Only add if not already represented
        existing_ts = {cp["timestamp"] for cp in version_checkpoints}
        if code_ts not in existing_ts:
            version_checkpoints.append({
                "timestamp": code_ts,
                "contract_version": agent.contracts[-1].version if agent.contracts else "?",
                "approved_by": None,
                "change_type": "code",
                "display_label": f"code v{agent.agent_code_version}",
            })

    # Re-sort all checkpoints by timestamp
    version_checkpoints.sort(key=lambda cp: cp["timestamp"] or "")

    return {
        "agent_id": agent_id,
        "window_days": days,
        "n_runs": len(runs),
        "n_successful": len(successful),
        "n_failed": len(failed),
        "completion_rate": round(len(successful) / len(runs), 4) if runs else 0.0,
        "avg_quality_score": round(avg_quality, 4),
        "avg_cost_usd": round(avg_cost, 5),
        "quality_adj_cost": round(quality_adj_cost, 5),
        "cost_change_wow": round(cost_wow, 4) if cost_wow is not None else None,
        "latency_p50_ms": latencies[len(latencies) // 2] if latencies else 0,
        "latency_p95_ms": latencies[int(len(latencies) * 0.95)] if len(latencies) > 1 else (latencies[-1] if latencies else 0),
        "trust_start": round(trust_start, 4),
        "trust_end": round(trust_end, 4),
        "trust_delta": round(trust_end - trust_start, 4),
        "current_tier": agent.current_tier,
        "total_violations": len(agent.violations),
        "version_checkpoints": version_checkpoints,
    }


@router.get("/{agent_id}/compare")
async def compare_versions(
    agent_id: str,
    v1: str,
    v2: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Before/after metric comparison between two contract versions."""
    agent = await _load_agent(agent_id, db)
    runs = sorted(agent.runs, key=lambda r: r.id)

    def _metrics(subset: list) -> dict:
        suc = [r for r in subset if r.completion_status == "success"]
        quality = [r.quality_score for r in suc if r.quality_score is not None]
        costs = [r.cost_usd for r in suc if r.cost_usd is not None]
        lats = sorted([r.latency_ms for r in subset if r.latency_ms is not None])
        viols = sum(1 for r in subset if r.completion_status == "failed")
        return {
            "n_runs": len(subset),
            "n_successful": len(suc),
            "violations": viols,
            "avg_quality": round(statistics.mean(quality), 4) if quality else None,
            "avg_cost": round(statistics.mean(costs), 5) if costs else None,
            "latency_p50": lats[len(lats) // 2] if lats else None,
        }

    v1_runs = [r for r in runs if r.contract_version == v1]
    v2_runs = [r for r in runs if r.contract_version == v2]

    note = None
    if not v1_runs and not v2_runs:
        mid = len(runs) // 2
        v1_runs = runs[:mid]
        v2_runs = runs[mid:]
        note = f"No runs for versions {v1!r}/{v2!r}. Showing first-half vs second-half as proxy."

    m1 = _metrics(v1_runs)
    m2 = _metrics(v2_runs)

    def _delta(a, b):
        if a is None or b is None or a == 0:
            return None
        return round((b - a) / a, 4)

    return {
        "agent_id": agent_id,
        "v1": v1,
        "v2": v2,
        "v1_metrics": m1,
        "v2_metrics": m2,
        "deltas": {
            "quality": _delta(m1["avg_quality"], m2["avg_quality"]),
            "cost": _delta(m1["avg_cost"], m2["avg_cost"]),
            "violations": (m2["violations"] or 0) - (m1["violations"] or 0),
            "latency_p50": _delta(m1["latency_p50"], m2["latency_p50"]),
        },
        "note": note,
        "data_basis": "runs.contract_version, runs.quality_score, runs.cost_usd, violations",
        "caveat": "Delta significance not computed — sample sizes may be too small for statistical conclusions.",
    }


@router.get("/{agent_id}/anomalies")
async def get_anomalies(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Statistical outlier detection. Returns anomalies with metric, window, sample_n, severity."""
    agent = await _load_agent(agent_id, db)
    runs = sorted(agent.runs, key=lambda r: r.id)

    if len(runs) < 6:
        return []

    anomalies: list[dict] = []
    mid = len(runs) // 2
    first_half = runs[:mid]
    second_half = runs[mid:]

    # Cost anomaly
    c1 = [r.cost_usd for r in first_half if r.cost_usd is not None]
    c2 = [r.cost_usd for r in second_half if r.cost_usd is not None]
    if c1 and c2:
        m1, m2 = statistics.mean(c1), statistics.mean(c2)
        change_pct = (m2 - m1) / m1 if m1 > 0 else 0.0
        if abs(change_pct) >= 0.15:
            version_changed = any(r.contract_version != runs[0].contract_version for r in second_half)
            anomalies.append({
                "type": "cost_change",
                "severity": "warning" if abs(change_pct) < 0.40 else "critical",
                "metric": "runs.cost_usd",
                "baseline": round(m1, 5),
                "current": round(m2, 5),
                "change_pct": round(change_pct * 100, 1),
                "window": f"runs 1-{mid} vs {mid + 1}-{len(runs)}",
                "sample_n_baseline": len(c1),
                "sample_n_current": len(c2),
                "message": (
                    f"Avg cost {'increased' if change_pct > 0 else 'decreased'} "
                    f"{abs(change_pct) * 100:.1f}% "
                    f"(${m1:.4f} to ${m2:.4f}, n={len(c1)}/{len(c2)}). "
                    + (
                        "Contract version changed in this window."
                        if version_changed
                        else "No contract version change detected."
                    )
                ),
            })

    # Quality drop
    q1 = [r.quality_score for r in first_half if r.quality_score is not None and r.completion_status == "success"]
    q2 = [r.quality_score for r in second_half if r.quality_score is not None and r.completion_status == "success"]
    if q1 and q2:
        m1, m2 = statistics.mean(q1), statistics.mean(q2)
        change_pct = (m2 - m1) / m1 if m1 > 0 else 0.0
        if change_pct < -0.05:
            anomalies.append({
                "type": "quality_drop",
                "severity": "warning" if abs(change_pct) < 0.15 else "critical",
                "metric": "runs.quality_score",
                "baseline": round(m1, 4),
                "current": round(m2, 4),
                "change_pct": round(change_pct * 100, 1),
                "window": f"runs 1-{mid} vs {mid + 1}-{len(runs)}",
                "sample_n_baseline": len(q1),
                "sample_n_current": len(q2),
                "message": (
                    f"Avg quality dropped {abs(change_pct) * 100:.1f}% "
                    f"({m1 * 100:.1f}% to {m2 * 100:.1f}%, n={len(q1)}/{len(q2)})."
                ),
            })

    # Violation spike
    v1_count = sum(1 for r in first_half if r.completion_status == "failed")
    v2_count = sum(1 for r in second_half if r.completion_status == "failed")
    if v2_count > 0 and (v1_count == 0 or v2_count > v1_count * 1.5):
        anomalies.append({
            "type": "violation_spike",
            "severity": "critical" if v2_count >= 2 else "warning",
            "metric": "violations",
            "baseline": v1_count,
            "current": v2_count,
            "change_pct": None,
            "window": f"runs 1-{mid} vs {mid + 1}-{len(runs)}",
            "sample_n_baseline": mid,
            "sample_n_current": len(runs) - mid,
            "message": (
                f"Policy violations: {v1_count} in first {mid} runs, "
                f"{v2_count} in following {len(runs) - mid} runs. "
                "Review tool usage against active contract."
            ),
        })

    return anomalies


@router.get("/{agent_id}/recommendations")
async def get_recommendations(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Data-grounded recommendations with evidence, confidence, and specific CTA."""
    agent = await _load_agent(agent_id, db)
    runs = sorted(agent.runs, key=lambda r: r.id)
    successful = [r for r in runs if r.completion_status == "success"]
    violations = agent.violations

    recommendations: list[dict] = []

    quality_scores = [r.quality_score for r in successful if r.quality_score is not None]
    avg_quality = statistics.mean(quality_scores) if quality_scores else 0.0

    # restricted -> standard
    if (
        agent.current_tier == "restricted"
        and len(successful) >= 5
        and agent.trust_score >= 0.60
        and avg_quality >= 0.80
        and len(violations) == 0
    ):
        recommendations.append({
            "type": "tier_promotion",
            "priority": "high",
            "title": f"Promote {agent.name} to standard tier",
            "evidence": (
                f"Trust {agent.trust_score:.3f} (threshold 0.60), "
                f"{len(successful)} clean runs (threshold 5), "
                f"avg quality {avg_quality * 100:.1f}% (threshold 80%), 0 violations."
            ),
            "action": "approve_contract_proposal",
            "confidence": "high",
            "data_sources": ["agents.trust_score", "runs.quality_score", "violations"],
            "cta": "Review & approve pending contract",
            "contract_version": agent.pending_contract_version or "1.0",
        })
    # standard -> trusted
    elif (
        agent.current_tier == "standard"
        and len(successful) >= 10
        and agent.trust_score >= 0.80
        and avg_quality >= 0.85
        and len(violations) == 0
    ):
        recommendations.append({
            "type": "tier_promotion",
            "priority": "medium",
            "title": f"Promote {agent.name} to trusted tier",
            "evidence": (
                f"Trust {agent.trust_score:.3f} (threshold 0.80), "
                f"{len(successful)} clean runs (threshold 10), "
                f"avg quality {avg_quality * 100:.1f}% (threshold 85%), 0 violations."
            ),
            "action": "approve_contract_proposal",
            "confidence": "medium",
            "data_sources": ["agents.trust_score", "runs.quality_score", "violations"],
            "cta": "Promote to trusted",
        })

    # Recent violation
    recent_violations = [r for r in runs[-10:] if r.completion_status == "failed"]
    if recent_violations:
        recommendations.append({
            "type": "review_reinstate",
            "priority": "high",
            "title": f"Review {agent.name} after recent violation",
            "evidence": (
                f"{len(recent_violations)} violation(s) in last {min(10, len(runs))} runs. "
                f"Trust: {agent.trust_score:.3f}. Tier: {agent.current_tier}."
            ),
            "action": "review_contract",
            "confidence": "high",
            "data_sources": ["violations.policy_rule", "agents.trust_score"],
            "cta": "Review enforcement log",
        })

    # Stale agent
    last_run = max((r.timestamp for r in runs if r.timestamp), default=None)
    if last_run and (datetime.utcnow() - last_run).days >= 7 and len(runs) > 0:
        recommendations.append({
            "type": "decommission_candidate",
            "priority": "low",
            "title": f"No activity from {agent.name} in 7+ days",
            "evidence": f"Last run: {last_run.strftime('%Y-%m-%d')}. Total runs: {len(runs)}.",
            "action": "investigate_or_retire",
            "confidence": "low",
            "data_sources": ["runs.timestamp"],
            "cta": "Investigate or retire",
        })

    # Rising cost
    costs = [r.cost_usd for r in successful if r.cost_usd is not None]
    if len(costs) >= 6:
        mid = len(costs) // 2
        m1 = statistics.mean(costs[:mid])
        m2 = statistics.mean(costs[mid:])
        change_pct = (m2 - m1) / m1 if m1 > 0 else 0
        if change_pct >= 0.20:
            recommendations.append({
                "type": "cost_investigation",
                "priority": "medium",
                "title": f"Cost per run rising for {agent.name}",
                "evidence": (
                    f"Avg cost increased {change_pct * 100:.1f}% "
                    f"(${m1:.4f} to ${m2:.4f}) across {len(costs)} runs."
                ),
                "action": "review_context_routing",
                "confidence": "medium",
                "data_sources": ["runs.cost_usd"],
                "cta": "Check context routing settings",
            })

    return recommendations


@router.get("/{agent_id}/export")
async def export_summary(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-click compliance summary: contract history, violation log, quality metrics."""
    agent = await _load_agent(agent_id, db)
    runs = sorted(agent.runs, key=lambda r: r.id)
    successful = [r for r in runs if r.completion_status == "success"]

    quality = [r.quality_score for r in successful if r.quality_score is not None]
    costs = [r.cost_usd for r in successful if r.cost_usd is not None]
    contracts = sorted(agent.contracts, key=lambda c: c.id if c.id else 0)

    return {
        "agent_id": agent_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_runs": len(runs),
        "total_violations": len(agent.violations),
        "avg_quality_score": round(statistics.mean(quality), 4) if quality else None,
        "avg_cost_usd": round(statistics.mean(costs), 5) if costs else None,
        "current_tier": agent.current_tier,
        "current_trust_score": agent.trust_score,
        "contracts": [
            {"version": c.version, "is_active": c.is_active, "approved_by": c.approved_by}
            for c in contracts
        ],
        "violations": [
            {
                "policy_rule": v.policy_rule,
                "action_attempted": v.action_attempted,
                "blocked": v.blocked,
                "timestamp": v.timestamp.isoformat() if v.timestamp else None,
            }
            for v in agent.violations
        ],
    }


@router.get("/{agent_id}/drift")
async def get_drift(
    agent_id: str,
    window_days: int = 7,
    sigma: float = 2.0,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Detect behavioral drift across rolling time windows.

    Compares quality scores, cost per run, and tool call frequencies between
    two consecutive windows of `window_days` each. Flags drift when metrics
    shift > `sigma` standard deviations from the baseline window.

    Returns list of drift events sorted by severity (critical first).
    """
    from sqlalchemy.orm import selectinload as _sl
    from norma.models.span import Span
    from norma.core.drift_detector import detect_drift_from_dicts

    # Load agent with runs + spans
    result = await db.execute(
        select(Agent)
        .where(Agent.agent_id == agent_id)
        .options(
            _sl(Agent.runs).selectinload(Run.spans),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    runs_data = [
        {
            "id": r.id,
            "quality_score": r.quality_score,
            "cost_usd": r.cost_usd,
            "latency_ms": r.latency_ms,
            "completion_status": r.completion_status,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        }
        for r in agent.runs
    ]

    spans_data = [
        {
            "id": s.id,
            "trace_id": s.trace_id,
            "span_type": s.span_type,
            "name": s.name,
            "tokens_in": s.tokens_in,
            "tokens_out": s.tokens_out,
            "cost_usd": s.cost_usd,
            "latency_ms": s.latency_ms,
            "model_name": s.model_name,
        }
        for r in agent.runs
        for s in r.spans
    ]

    events = detect_drift_from_dicts(
        runs=runs_data,
        spans=spans_data,
        window_days=window_days,
        sigma_threshold=sigma,
    )
    return events
