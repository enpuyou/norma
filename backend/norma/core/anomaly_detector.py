"""Anomaly Detector — statistical outlier detection for cost, quality, and error rate.

Every alert includes:
  - The metric and its current value
  - The baseline value and the comparison window
  - Sample sizes for both windows
  - Whether any contract or model change was recorded in the window
  - What the data does NOT tell us
  - A suggested next action

We never say "anomaly detected, investigate." We always say what was measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AnomalyAlert:
    metric: str
    current_value: float
    baseline_value: float
    change_pct: float
    current_window: str        # e.g. "2026-03-03 to 2026-03-10"
    baseline_window: str
    current_n: int
    baseline_n: int
    contract_change_in_window: bool
    model_change_in_window: bool
    confidence: str             # high | medium | low
    what_this_is_not: str
    suggested_action: str


def detect_anomalies(
    metric_series: list[dict[str, Any]],
    metric_name: str,
    threshold_pct: float = 0.20,   # flag if change > 20%
) -> list[AnomalyAlert]:
    """
    Compare the most recent window to the prior window.
    Returns a list of AnomalyAlert objects for any metric that crossed the threshold.

    metric_series: list of {timestamp, value, contract_version, model_version}
    """
    # TODO Phase 5: implement with real run data
    return []


def format_alert_for_vp(alert: AnomalyAlert) -> str:
    """Plain-English alert for VP mode."""
    direction = "increased" if alert.change_pct > 0 else "decreased"
    return (
        f"{alert.metric.replace('_', ' ').title()} {direction} "
        f"{abs(alert.change_pct):.0%} week-over-week "
        f"(from {alert.baseline_value:.2f} to {alert.current_value:.2f}, "
        f"n={alert.current_n} runs). "
        + ("No contract change recorded in this window." if not alert.contract_change_in_window else "")
    )


def format_alert_for_engineer(alert: AnomalyAlert) -> dict[str, Any]:
    """Structured alert dict for Engineer mode."""
    return {
        "metric": alert.metric,
        "current_value": alert.current_value,
        "baseline_value": alert.baseline_value,
        "change_pct": alert.change_pct,
        "current_window": alert.current_window,
        "baseline_window": alert.baseline_window,
        "current_n": alert.current_n,
        "baseline_n": alert.baseline_n,
        "contract_change_in_window": alert.contract_change_in_window,
        "model_change_in_window": alert.model_change_in_window,
        "confidence": alert.confidence,
        "what_this_is_not": alert.what_this_is_not,
        "suggested_action": alert.suggested_action,
    }
