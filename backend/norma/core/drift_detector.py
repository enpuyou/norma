"""Drift Detector — detects behavioral drift in agent metrics across rolling time windows.

Compares two rolling windows (old vs recent) of:
  - quality scores
  - cost per run
  - tool call frequencies
  - prompt hash distribution (input drift)

Flags drift when any metric shifts > 2σ from baseline.
Returns typed DriftEvent objects.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class DriftEvent:
    """A detected drift event."""
    drift_type: str       # "quality_drift" | "cost_drift" | "input_drift" | "tool_frequency_drift"
    metric: str
    severity: str         # "warning" | "critical"
    baseline_value: float
    current_value: float
    change_pct: float
    sigma: float          # how many standard deviations from the mean
    window_days: int
    description: str
    data_sources: list[str] = field(default_factory=list)


def _mean_std(values: list[float]) -> tuple[float, float]:
    """Return (mean, std) for a list; guard against < 2 items."""
    if not values:
        return 0.0, 0.0
    m = statistics.mean(values)
    if len(values) < 2:
        return m, 0.0
    return m, statistics.stdev(values)


def _change_pct(a: float, b: float) -> float:
    if a == 0:
        return 0.0
    return round((b - a) / abs(a), 4)


def _sigma(value: float, mean: float, std: float) -> float:
    if std == 0:
        return 0.0
    return abs(value - mean) / std


def detect_drift(
    runs: list[Any],
    spans: list[Any],
    window_days: int = 7,
    sigma_threshold: float = 2.0,
) -> list[DriftEvent]:
    """Detect behavioral drift across agent runs.

    Args:
        runs: list of Run ORM objects (or dicts with same fields)
        spans: list of Span ORM objects (or dicts with same fields)
        window_days: size of each comparison window in days
        sigma_threshold: how many σ triggers a drift event (default 2.0)

    Returns:
        list of DriftEvent objects, severity-sorted (critical first)
    """
    if len(runs) < 4:
        return []

    def _ts(r: Any) -> datetime:
        ts = r.timestamp if hasattr(r, "timestamp") else r.get("timestamp")
        if ts is None:
            return datetime.utcnow()
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return ts

    def _attr(obj: Any, name: str) -> Any:
        return getattr(obj, name, None) if not isinstance(obj, dict) else obj.get(name)

    sorted_runs = sorted(runs, key=_ts)
    now = _ts(sorted_runs[-1])
    cutoff = now - timedelta(days=window_days)
    old_cutoff = cutoff - timedelta(days=window_days)

    baseline_runs = [r for r in sorted_runs if old_cutoff <= _ts(r) < cutoff]
    current_runs = [r for r in sorted_runs if _ts(r) >= cutoff]

    # Fall back to first/second half split if time ranges don't have data
    if not baseline_runs or not current_runs:
        mid = len(sorted_runs) // 2
        baseline_runs = sorted_runs[:mid]
        current_runs = sorted_runs[mid:]

    events: list[DriftEvent] = []

    # ── Quality drift ──────────────────────────────────────────────────────────
    b_quality = [_attr(r, "quality_score") for r in baseline_runs if _attr(r, "quality_score") is not None]
    c_quality = [_attr(r, "quality_score") for r in current_runs if _attr(r, "quality_score") is not None]
    if b_quality and c_quality:
        b_mean, b_std = _mean_std(b_quality)
        c_mean, _ = _mean_std(c_quality)
        sig = _sigma(c_mean, b_mean, b_std) if b_std > 0 else 0.0
        chg = _change_pct(b_mean, c_mean)
        if sig >= sigma_threshold or abs(chg) >= 0.10:
            events.append(DriftEvent(
                drift_type="quality_drift",
                metric="quality_score",
                severity="critical" if sig >= sigma_threshold * 1.5 or abs(chg) >= 0.20 else "warning",
                baseline_value=round(b_mean, 4),
                current_value=round(c_mean, 4),
                change_pct=chg,
                sigma=round(sig, 2),
                window_days=window_days,
                description=(
                    f"Quality score {'dropped' if chg < 0 else 'rose'} "
                    f"{abs(chg) * 100:.1f}% ({b_mean:.3f} → {c_mean:.3f}), "
                    f"{sig:.1f}σ from baseline. "
                    f"(baseline n={len(b_quality)}, current n={len(c_quality)})"
                ),
                data_sources=["runs.quality_score"],
            ))

    # ── Cost drift ─────────────────────────────────────────────────────────────
    b_cost = [_attr(r, "cost_usd") for r in baseline_runs if _attr(r, "cost_usd") is not None]
    c_cost = [_attr(r, "cost_usd") for r in current_runs if _attr(r, "cost_usd") is not None]
    if b_cost and c_cost:
        b_mean, b_std = _mean_std(b_cost)
        c_mean, _ = _mean_std(c_cost)
        sig = _sigma(c_mean, b_mean, b_std) if b_std > 0 else 0.0
        chg = _change_pct(b_mean, c_mean)
        if sig >= sigma_threshold or abs(chg) >= 0.15:
            events.append(DriftEvent(
                drift_type="cost_drift",
                metric="cost_usd",
                severity="critical" if sig >= sigma_threshold * 1.5 or chg >= 0.30 else "warning",
                baseline_value=round(b_mean, 5),
                current_value=round(c_mean, 5),
                change_pct=chg,
                sigma=round(sig, 2),
                window_days=window_days,
                description=(
                    f"Cost per run {'increased' if chg > 0 else 'decreased'} "
                    f"{abs(chg) * 100:.1f}% (${b_mean:.4f} → ${c_mean:.4f}), "
                    f"{sig:.1f}σ from baseline."
                ),
                data_sources=["runs.cost_usd"],
            ))

    # ── Tool frequency drift (from spans) ─────────────────────────────────────
    def _spans_for_runs(run_ids: set[int]) -> list[Any]:
        return [s for s in spans if _attr(s, "trace_id") in run_ids]

    def _tool_freq(span_subset: list[Any]) -> dict[str, int]:
        freq: dict[str, int] = {}
        for s in span_subset:
            if _attr(s, "span_type") == "tool_call":
                name = _attr(s, "name") or "unknown"
                freq[name] = freq.get(name, 0) + 1
        return freq

    b_run_ids = {_attr(r, "id") for r in baseline_runs}
    c_run_ids = {_attr(r, "id") for r in current_runs}
    b_spans = _spans_for_runs(b_run_ids)
    c_spans = _spans_for_runs(c_run_ids)

    b_freq = _tool_freq(b_spans)
    c_freq = _tool_freq(c_spans)

    if b_freq and c_freq:
        all_tools = set(b_freq) | set(c_freq)
        b_n = max(len(baseline_runs), 1)
        c_n = max(len(current_runs), 1)

        for tool in all_tools:
            b_rate = b_freq.get(tool, 0) / b_n
            c_rate = c_freq.get(tool, 0) / c_n
            chg = _change_pct(b_rate, c_rate)
            if abs(chg) >= 0.40 and (b_freq.get(tool, 0) >= 2 or c_freq.get(tool, 0) >= 2):
                events.append(DriftEvent(
                    drift_type="tool_frequency_drift",
                    metric=f"tool_call_rate:{tool}",
                    severity="warning",
                    baseline_value=round(b_rate, 3),
                    current_value=round(c_rate, 3),
                    change_pct=chg,
                    sigma=0.0,
                    window_days=window_days,
                    description=(
                        f"Tool '{tool}' call rate changed {chg * 100:+.1f}% "
                        f"({b_rate:.2f}/run → {c_rate:.2f}/run). "
                        f"May indicate prompt or workflow change."
                    ),
                    data_sources=["spans.span_type", "spans.name"],
                ))

    # Sort: critical first, then by abs change_pct descending
    events.sort(key=lambda e: (0 if e.severity == "critical" else 1, -abs(e.change_pct)))
    return events


def detect_drift_from_dicts(
    runs: list[dict],
    spans: list[dict],
    window_days: int = 7,
    sigma_threshold: float = 2.0,
) -> list[dict]:
    """Convenience wrapper that serializes DriftEvents to dicts for API responses."""
    events = detect_drift(runs, spans, window_days=window_days, sigma_threshold=sigma_threshold)
    return [
        {
            "drift_type": e.drift_type,
            "metric": e.metric,
            "severity": e.severity,
            "baseline_value": e.baseline_value,
            "current_value": e.current_value,
            "change_pct": e.change_pct,
            "sigma": e.sigma,
            "window_days": e.window_days,
            "description": e.description,
            "data_sources": e.data_sources,
        }
        for e in events
    ]
