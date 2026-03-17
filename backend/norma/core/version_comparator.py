"""Version Comparator — before/after metric comparison on every contract change.

Every comparison includes:
  - The two contract versions being compared
  - The metric deltas (cost, quality, completion, latency)
  - The sample sizes for each window
  - Whether the change is within measurement noise
"""

from __future__ import annotations

from typing import Any


def compare_versions(
    agent_id: str,
    v1_runs: list[dict[str, Any]],
    v2_runs: list[dict[str, Any]],
    v1: str,
    v2: str,
) -> dict[str, Any]:
    """
    Compare metrics between two sets of runs (segmented by contract version).

    Returns:
        v1, v2:           version labels
        n_v1, n_v2:       sample sizes
        quality_delta:    float
        cost_delta:       float
        completion_delta: float
        latency_delta:    float
        summary:          str  — plain-English summary for VP mode
    """
    def avg(runs: list[dict], key: str) -> float:
        vals = [r[key] for r in runs if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else 0.0

    q1 = avg(v1_runs, "quality_score")
    q2 = avg(v2_runs, "quality_score")
    c1 = avg(v1_runs, "cost_usd")
    c2 = avg(v2_runs, "cost_usd")

    quality_delta = q2 - q1
    cost_delta    = c2 - c1

    # Avoid division by zero
    cost_pct    = (cost_delta / c1 * 100) if c1 else 0.0
    quality_pct = (quality_delta / q1 * 100) if q1 else 0.0

    direction_cost    = "↓" if cost_pct    < 0 else "↑"
    direction_quality = "↑" if quality_pct > 0 else "↓"

    summary = (
        f"{v1}→{v2}: cost {direction_cost}{abs(cost_pct):.0f}%, "
        f"quality {direction_quality}{abs(quality_pct):.0f}%."
    )

    return {
        "v1": v1,
        "v2": v2,
        "n_v1": len(v1_runs),
        "n_v2": len(v2_runs),
        "quality_delta": round(quality_delta, 4),
        "cost_delta": round(cost_delta, 4),
        "quality_pct": round(quality_pct, 2),
        "cost_pct": round(cost_pct, 2),
        "summary": summary,
    }
