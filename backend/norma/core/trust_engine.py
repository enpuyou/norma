"""Trust Engine — score tracking, tier transitions, and contract proposal generation.

Core formulas (from design doc):
  trust_score += clean_run_increment  per clean run
  trust_score -= violation_penalty    on any policy violation
  trust_score  = clamp(trust_score, 0.0, 1.0)

Tier thresholds (default):
  restricted → standard : score >= 0.65 AND clean_runs >= 10  → proposes v+1 (human approval required)
  standard   → trusted  : score >= 0.82 AND clean_runs >= 20  → proposes v+1 (human approval required)
  standard/trusted → restricted : on any violation            → immediate, no approval required
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TrustState:
    agent_id: str
    trust_score: float = 0.40
    current_tier: str = "restricted"
    clean_run_count: int = 0
    pending_contract_version: str | None = None
    audit_log: list[dict[str, Any]] = field(default_factory=list)

    # Config (loaded from active contract)
    clean_run_increment: float = 0.025
    violation_penalty: float = 0.25
    tier_thresholds: dict[str, dict[str, float]] = field(
        default_factory=lambda: {
            "standard": {"min_score": 0.65, "min_clean_runs": 10},
            "trusted":  {"min_score": 0.82, "min_clean_runs": 20},
        }
    )


def record_clean_run(state: TrustState, run_id: int) -> TrustState:
    """Increment trust score after a clean run. Propose tier upgrade if thresholds met."""
    state.trust_score = min(1.0, state.trust_score + state.clean_run_increment)
    state.clean_run_count += 1

    _check_tier_upgrade(state, run_id)
    return state


def record_violation(state: TrustState, resource: str, run_id: int) -> TrustState:
    """Apply violation penalty and revert tier."""
    prev_score = state.trust_score
    prev_tier  = state.current_tier

    state.trust_score = max(0.0, state.trust_score - state.violation_penalty)

    if state.current_tier != "restricted":
        state.current_tier = "restricted"
        state.audit_log.append({
            "event_type": "tier_revocation",
            "run_id": run_id,
            "from_tier": prev_tier,
            "to_tier": "restricted",
            "trust_score_before": prev_score,
            "trust_score_after": state.trust_score,
        })
        state.audit_log.append({
            "event_type": "access_revoked",
            "run_id": run_id,
            "scope": "internal",
            "reason": f"Tier reverted to restricted. Resource attempted: {resource}",
        })

    return state


def approve_pending_contract(state: TrustState, approver: str) -> TrustState:
    """Human approves proposed tier expansion — contract becomes active."""
    if state.pending_contract_version is None:
        raise ValueError("No pending contract version to approve.")
    state.audit_log.append({
        "event_type": "contract_approved",
        "version": state.pending_contract_version,
        "approved_by": approver,
    })
    # Actual tier change happens here (after approval)
    _apply_tier_upgrade(state)
    state.pending_contract_version = None
    return state


def _check_tier_upgrade(state: TrustState, run_id: int) -> None:
    """Propose a tier upgrade if thresholds are met (does NOT upgrade until approved)."""
    if state.current_tier == "restricted":
        t = state.tier_thresholds.get("standard", {})
        if (
            state.trust_score >= t.get("min_score", 0.65)
            and state.clean_run_count >= t.get("min_clean_runs", 10)
            and state.pending_contract_version is None
        ):
            state.pending_contract_version = _next_version("standard")
            state.audit_log.append({
                "event_type": "tier_upgrade_proposed",
                "proposed_tier": "standard",
                "proposed_version": state.pending_contract_version,
                "trust_score": state.trust_score,
                "clean_runs": state.clean_run_count,
                "run_id": run_id,
            })

    elif state.current_tier == "standard":
        t = state.tier_thresholds.get("trusted", {})
        if (
            state.trust_score >= t.get("min_score", 0.82)
            and state.clean_run_count >= t.get("min_clean_runs", 20)
            and state.pending_contract_version is None
        ):
            state.pending_contract_version = _next_version("trusted")
            state.audit_log.append({
                "event_type": "tier_upgrade_proposed",
                "proposed_tier": "trusted",
                "proposed_version": state.pending_contract_version,
                "trust_score": state.trust_score,
                "clean_runs": state.clean_run_count,
                "run_id": run_id,
            })


def _apply_tier_upgrade(state: TrustState) -> None:
    """Apply the pending tier upgrade (called only after human approval)."""
    if state.current_tier == "restricted":
        state.current_tier = "standard"
    elif state.current_tier == "standard":
        state.current_tier = "trusted"


def _next_version(tier: str) -> str:
    """Stub — real impl reads current version from DB and increments."""
    return f"pending-{tier}"
