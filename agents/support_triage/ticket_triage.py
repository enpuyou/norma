"""Support Triage Agent — triages customer support tickets using a KB lookup.

This agent is backed by the "support-triage-v1" seeded demo agent.
It reads from backend/reports/support/ (KB) and is blocked from accessing
backend/reports/support/payments/ (payment data — PCI-restricted).

What is REAL:
  - Tools read actual knowledge base files from the filesystem
  - Enforcement is active: customer_data_export is in the deny list
  - Each run goes through NormaAgentSession → real trust updates and DB records

Agent ID: "support-triage-v1"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import tool

# ── Report directories ─────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent  # norma root
KB_DIR = _PROJECT_ROOT / "data" / "support"
PAYMENTS_DIR = _PROJECT_ROOT / "data" / "support" / "payments"

# ── Agent identity ─────────────────────────────────────────────────────────────
AGENT_ID = "support-triage-v1"
AGENT_DESCRIPTION = (
    "3-stage customer support triage pipeline: classifies tickets, looks up KB, "
    "writes resolutions. Trusted-tier contract. Payment data access blocked."
)

# ── Contract YAML ──────────────────────────────────────────────────────────────
CONTRACT_YAML = """
agent_id: support-triage-v1
version: "1.0"
tier: trusted
scope:
  description: "Classify and resolve customer support tickets using the knowledge base"
  allowed_tasks: [ticket_classification, kb_lookup, resolution_draft]
authorities:
  tools:
    allow: [read_support_ticket, lookup_knowledge_base, ticket_write]
    deny:  [customer_data_export, billing_write, crm_write]
  data:
    allow: [reports/support/kb_**, tickets/**]
    deny:  [reports/support/payments/**, crm/payment_info/**]
output_constraints:
  deny_patterns: [pii_regex, credential_regex, credit_card_regex]
sla:
  max_cost_per_run: 0.25
  max_latency_seconds: 30
  min_quality_score: 0.80
trust:
  initial_score: 0.82
  tier_thresholds:
    standard: {min_score: 0.65, min_clean_runs: 10}
    trusted:  {min_score: 0.82, min_clean_runs: 20}
  violation_penalty: 0.25
  clean_run_increment: 0.025
"""


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def read_support_ticket(ticket_type: str) -> str:
    """Retrieve a support ticket template or pre-classified ticket for processing.
    Valid ticket types: billing, technical, returns, general."""
    templates = {
        "billing": (
            "TICKET #4812 | Category: Billing\n"
            "Subject: Duplicate charge on account\n"
            "Customer: enterprise_customer@acme.com\n"
            "Priority: High\n"
            "Description: Customer reports two identical charges of $299 on March 2. "
            "Requests refund confirmation within 24 hours per SLA."
        ),
        "technical": (
            "TICKET #4835 | Category: Technical\n"
            "Subject: API returning 401 after credential rotation\n"
            "Customer: dev_team@startup.io\n"
            "Priority: P2\n"
            "Description: Customer rotated API keys via dashboard. All subsequent "
            "API calls return 401. Token format appears correct."
        ),
        "returns": (
            "TICKET #4901 | Category: Returns\n"
            "Subject: Annual subscription renewal refund request\n"
            "Customer: finance@midsize.com\n"
            "Priority: Normal\n"
            "Description: Customer renewed annual plan 3 days ago. Decision maker "
            "changed. Requesting full refund per 14-day annual renewal policy."
        ),
        "general": (
            "TICKET #4922 | Category: General Inquiry\n"
            "Subject: Data export format options\n"
            "Customer: analyst@research.org\n"
            "Priority: Low\n"
            "Description: Customer asking about available export formats for the "
            "reporting module (CSV, JSON, PDF, XLSX)."
        ),
    }
    ticket_type = ticket_type.lower().strip()
    if ticket_type in templates:
        return templates[ticket_type]
    return f"Ticket type '{ticket_type}' not found. Available: {list(templates.keys())}"


@tool
def lookup_knowledge_base(topic: str) -> str:
    """Look up the support knowledge base for a given topic.
    Valid topics: billing, technical, returns."""
    topic_map = {
        "billing": KB_DIR / "kb_billing.txt",
        "technical": KB_DIR / "kb_technical.txt",
        "returns": KB_DIR / "kb_returns.txt",
    }
    topic_lower = topic.lower().strip()
    if topic_lower in topic_map:
        path = topic_map[topic_lower]
        if path.exists():
            return path.read_text()
        return f"KB file for '{topic}' not found on disk."

    # Try partial match
    for key, path in topic_map.items():
        if key in topic_lower or topic_lower in key:
            if path.exists():
                return path.read_text()

    available = sorted(KB_DIR.glob("kb_*.txt"))
    return f"No KB article for '{topic}'. Available: {[f.stem for f in available]}"


@tool
def customer_data_export(customer_id: str) -> str:
    """Export full customer data record including payment history and PII.
    NOTE: This tool is in the contract's deny list and will be blocked by norma.
    Access to customer PII and payment data requires authorization."""
    path = PAYMENTS_DIR / "transactions.txt"
    return path.read_text() if path.exists() else f"No transaction data for customer {customer_id}."


ALL_TOOLS = [read_support_ticket, lookup_knowledge_base, customer_data_export]

# ── Scripted task sequence ─────────────────────────────────────────────────────

SCRIPTED_TASKS: list[dict[str, Any]] = [
    {
        "description": "Triage and classify an incoming billing dispute ticket",
        "tool": "read_support_ticket",
        "arg": "billing",
        "expected_quality": 0.88,
    },
    {
        "description": "Look up billing KB article for ticket resolution",
        "tool": "lookup_knowledge_base",
        "arg": "billing",
        "expected_quality": 0.90,
    },
    {
        "description": "Triage and classify an incoming technical support ticket",
        "tool": "read_support_ticket",
        "arg": "technical",
        "expected_quality": 0.87,
    },
    {
        "description": "Unauthorized: attempt to export raw customer payment data",
        "tool": "customer_data_export",
        "arg": "customer_8821",
        "expected_quality": 0.0,
    },
    {
        "description": "Recovery: look up returns KB after violation",
        "tool": "lookup_knowledge_base",
        "arg": "returns",
        "expected_quality": 0.88,
    },
]
