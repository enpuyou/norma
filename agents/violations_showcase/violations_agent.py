"""Violations Showcase Agent — demonstrates norma.ai enforcement in action.

This agent intentionally attempts 5 different types of policy violations to
demonstrate how norma's contract enforcement blocks each one in real-time.

Run it from the norma dashboard (Execute → mode=full) or from terminal:
    python agents/violations_showcase/violations_agent.py

The contract `violations_contract.yaml` explicitly denies all 5 tools.
When run, the dashboard will show 5 blocked enforcement events.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

# ─── Path setup ───────────────────────────────────────────────────────────────
_AGENTS_DIR = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _AGENTS_DIR.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
if str(_AGENTS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_AGENTS_DIR.parent))

# ─── Tool definitions ─────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "access_sso_credentials",
        "description": "Access SSO credentials and authentication tokens from the identity vault",
        "data_path": "vault/sso/credentials",
        "attempt_description": "Exfiltrate SSO credentials",
    },
    {
        "name": "send_data_to_external_endpoint",
        "description": "Send customer PII data to an external HTTP endpoint",
        "data_path": None,
        "attempt_description": "Exfiltrate PII to external service",
    },
    {
        "name": "modify_production_database",
        "description": "Execute raw SQL statements against the production database",
        "data_path": "database/production/write",
        "attempt_description": "Write to production database",
    },
    {
        "name": "delete_audit_logs",
        "description": "Permanently delete audit trail logs from the compliance system",
        "data_path": "compliance/audit_logs/delete",
        "attempt_description": "Destroy audit trail",
    },
    {
        "name": "access_payment_gateway_keys",
        "description": "Retrieve payment gateway API keys and merchant credentials",
        "data_path": "financial/payment_gateway/api_keys",
        "attempt_description": "Access payment gateway secrets",
    },
]

CONTRACT_YAML = """
agent_id: violations-showcase-v1
authorities:
  tools:
    allow: []
    deny:
      - access_sso_credentials
      - send_data_to_external_endpoint
      - modify_production_database
      - delete_audit_logs
      - access_payment_gateway_keys
  data:
    allow: []
    deny:
      - vault/**
      - database/production/**
      - compliance/audit_logs/**
      - financial/**

output_constraints:
  deny_patterns:
    - pii_regex
    - credential_regex

sla:
  max_cost_per_run: 5.0
  max_tool_calls_per_run: 10
  max_latency_ms: 60000

trust:
  clean_run_increment: 0.025
  violation_penalty: 0.30
  tier_thresholds:
    standard: { min_score: 0.65, min_clean_runs: 10 }
    trusted: { min_score: 0.82, min_clean_runs: 20 }
"""


def run_agent(task_input: str | None = None) -> dict[str, Any]:
    """Run the violations showcase agent.

    Attempts all 5 denied tools and records each blocked enforcement event.
    Returns a summary of what was attempted and what was blocked.
    """
    from norma.integrations.session import NormaAgentSession

    db_url = os.environ.get("DATABASE_URL", "sqlite:///./norma.db").replace("+aiosqlite", "")
    remote_url = os.environ.get("NORMA_REMOTE_URL")

    results = []

    with NormaAgentSession(
        agent_id="violations-showcase-v1",
        contract_yaml=CONTRACT_YAML,
        db_url=None if remote_url else db_url,
        remote_url=remote_url,
        check_enabled=False,
    ) as sess:
        for tool in TOOLS:
            print(f"\n[norma] Attempting: {tool['name']}")
            allowed, msg = sess.check_and_enforce_tool(
                tool_name=tool["name"],
                raw_input=tool.get("data_path") or f"attempting {tool['name']}",
            )
            status = "BLOCKED" if not allowed else "ALLOWED"
            print(f"  → {status}: {msg or 'no policy rule triggered (unexpected)'}")
            results.append({
                "tool": tool["name"],
                "attempt": tool["attempt_description"],
                "blocked": not allowed,
                "policy_message": msg,
            })

            time.sleep(0.05)

        # Record a low-quality output to show quality scoring in action
        sess.record_tool_call(
            tool_name="narrate_violations",
            input_text="Summarize what I tried to do",
            output_text=(
                "I attempted to access SSO credentials, exfiltrate PII, modify the production "
                "database, delete audit logs, and access payment gateway keys. "
                "All 5 attempts were blocked by norma.ai contract enforcement."
            ),
            latency_ms=50,
            blocked=False,
        )

    blocked_count = sum(1 for r in results if r["blocked"])
    print(f"\n✅ Run complete: {blocked_count}/{len(results)} tool calls blocked by norma enforcement")
    return {
        "agent_id": "violations-showcase-v1",
        "total_attempts": len(results),
        "blocked": blocked_count,
        "results": results,
    }


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or "Demonstrate all policy violations"
    result = run_agent(task)
    import json
    print(json.dumps(result, indent=2))
