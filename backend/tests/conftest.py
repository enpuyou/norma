"""Shared pytest fixtures."""

import pytest


# ── DB fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def compliance_contract() -> dict:
    """A minimal contract dict for compliance engine tests."""
    return {
        "agent_id": "support-triage-v1",
        "authorities": {
            "tools": {
                "allow": ["knowledge_base_search", "ticket_read", "ticket_update"],
                "deny": ["ticket_delete", "account_modify", "refund_process", "payment_access"],
            },
            "data": {
                "allow": ["knowledge_base/**", "ticket_history/**"],
                "deny": ["payment_info/**", "internal_notes/**"],
            },
        },
        "output_constraints": {
            "deny_patterns": ["credit_card_regex", "ssn_regex"],
        },
        "sla": {"max_cost_per_run": 0.50, "max_latency_seconds": 10, "min_quality_score": 0.80},
    }
