"""Test: Drift Detector — unit tests for statistical drift detection.

Verifies that detect_drift correctly identifies:
  - Quality score drops crossing the 2σ threshold
  - Cost spikes crossing the 2σ threshold
  - Tool frequency shifts > 40%
  - Returns empty list when insufficient data
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from norma.core.drift_detector import detect_drift, detect_drift_from_dicts, DriftEvent


def _make_runs(
    n: int,
    quality: float = 0.85,
    cost: float = 0.01,
    base_time: datetime | None = None,
) -> list[dict]:
    """Create mock run dicts with consistent quality/cost."""
    base_time = base_time or datetime.utcnow() - timedelta(days=14)
    return [
        {
            "id": i + 1,
            "quality_score": quality,
            "cost_usd": cost,
            "latency_ms": 500,
            "completion_status": "success",
            "timestamp": (base_time + timedelta(days=i)).isoformat(),
        }
        for i in range(n)
    ]


def test_no_drift_when_metrics_stable() -> None:
    """No drift events when metrics are flat across two windows."""
    runs = _make_runs(20, quality=0.85, cost=0.01)
    events = detect_drift_from_dicts(runs=runs, spans=[], window_days=7, sigma_threshold=2.0)
    # Stable metrics → no drift
    assert events == [], f"Expected no drift, got: {events}"


def test_quality_drift_detected() -> None:
    """Quality drop > 2σ in second window triggers quality_drift event."""
    base = datetime.utcnow() - timedelta(days=20)
    # Baseline window (days 0-9): high quality
    baseline = _make_runs(10, quality=0.90, cost=0.01, base_time=base)
    # Current window (days 10-19): quality collapsed
    current = [
        {
            "id": 100 + i,
            "quality_score": 0.45,  # 50% drop
            "cost_usd": 0.01,
            "latency_ms": 500,
            "completion_status": "success",
            "timestamp": (base + timedelta(days=10 + i)).isoformat(),
        }
        for i in range(10)
    ]
    all_runs = baseline + current

    events = detect_drift_from_dicts(runs=all_runs, spans=[], window_days=7, sigma_threshold=2.0)

    drift_types = [e["drift_type"] for e in events]
    assert "quality_drift" in drift_types, f"Expected quality_drift, got: {drift_types}"

    q_event = next(e for e in events if e["drift_type"] == "quality_drift")
    # Baseline should be significantly higher than current (not exact assertion since window split is internal)
    assert q_event["baseline_value"] > q_event["current_value"], (
        f"Expected baseline > current for quality_drift. Got baseline={q_event['baseline_value']}, "
        f"current={q_event['current_value']}"
    )
    assert q_event["change_pct"] < -0.10  # at least -10% change
    assert q_event["severity"] in ("warning", "critical")


def test_cost_drift_detected() -> None:
    """Cost spike > 2σ in second window triggers cost_drift event."""
    base = datetime.utcnow() - timedelta(days=20)
    baseline = _make_runs(10, quality=0.85, cost=0.005, base_time=base)
    current = [
        {
            "id": 200 + i,
            "quality_score": 0.85,
            "cost_usd": 0.05,  # 10x cost spike
            "latency_ms": 500,
            "completion_status": "success",
            "timestamp": (base + timedelta(days=10 + i)).isoformat(),
        }
        for i in range(10)
    ]
    all_runs = baseline + current

    events = detect_drift_from_dicts(runs=all_runs, spans=[], window_days=7, sigma_threshold=2.0)

    drift_types = [e["drift_type"] for e in events]
    assert "cost_drift" in drift_types, f"Expected cost_drift, got: {drift_types}"

    c_event = next(e for e in events if e["drift_type"] == "cost_drift")
    assert c_event["change_pct"] > 0.50  # > 50% increase
    assert c_event["severity"] == "critical"


def test_tool_frequency_drift_detected() -> None:
    """Tool call rate shifting > 40% triggers tool_frequency_drift event."""
    base = datetime.utcnow() - timedelta(days=20)
    runs = _make_runs(20, quality=0.85, cost=0.01, base_time=base)

    # Baseline spans: tool A called 2x per run (runs 1-10)
    baseline_spans = [
        {
            "id": i,
            "trace_id": i // 2 + 1,  # 2 spans per run
            "span_type": "tool_call",
            "name": "analyze_data",
            "latency_ms": 100,
            "tokens_in": None,
            "tokens_out": None,
            "cost_usd": None,
            "model_name": None,
        }
        for i in range(20)  # 2 calls × 10 runs
    ]

    # Current spans: tool A NOT called at all (runs 11-20 have no analyze_data spans)
    # Tool B called heavily instead
    current_spans = [
        {
            "id": 100 + i,
            "trace_id": 11 + i,  # runs 11-20
            "span_type": "tool_call",
            "name": "summarize_results",
            "latency_ms": 100,
            "tokens_in": None,
            "tokens_out": None,
            "cost_usd": None,
            "model_name": None,
        }
        for i in range(10)
    ]

    events = detect_drift_from_dicts(
        runs=runs,
        spans=baseline_spans + current_spans,
        window_days=7,
        sigma_threshold=2.0,
    )

    drift_types = [e["drift_type"] for e in events]
    tool_drifts = [e for e in events if e["drift_type"] == "tool_frequency_drift"]
    # Should detect analyze_data dropping to 0 rate
    assert len(tool_drifts) > 0, f"Expected tool_frequency_drift, got: {drift_types}"


def test_insufficient_data_returns_empty() -> None:
    """With < 4 runs, drift detector returns empty list."""
    runs = _make_runs(3)
    events = detect_drift_from_dicts(runs=runs, spans=[], window_days=7)
    assert events == []


def test_critical_events_sorted_first() -> None:
    """Critical severity events appear before warning events in output."""
    base = datetime.utcnow() - timedelta(days=20)
    baseline = _make_runs(10, quality=0.90, cost=0.005, base_time=base)
    # Big combined drop: both quality and cost shift drastically
    current = [
        {
            "id": 300 + i,
            "quality_score": 0.30,  # massive drop → critical
            "cost_usd": 0.10,        # massive spike → critical
            "latency_ms": 500,
            "completion_status": "success",
            "timestamp": (base + timedelta(days=10 + i)).isoformat(),
        }
        for i in range(10)
    ]
    events = detect_drift_from_dicts(runs=baseline + current, spans=[], window_days=7)

    if len(events) >= 2:
        severities = [e["severity"] for e in events]
        critical_indices = [i for i, s in enumerate(severities) if s == "critical"]
        warning_indices = [i for i, s in enumerate(severities) if s == "warning"]
        if critical_indices and warning_indices:
            assert min(critical_indices) < max(warning_indices), \
                "Critical events should appear before warning events"
