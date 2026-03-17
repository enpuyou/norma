"""Re-export shim — canonical agent source lives in agents/financial_reader/.

This shim provides backward-compatible imports for internal tests that use
NormaAgentSession directly with the financial_reader agent's tools.

The agent file is the canonical implementation. This shim does NOT expose
scripted tasks. The CONTRACT_YAML defined here belongs to norma's
test infrastructure, not to the agent itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path so `agents.*` is importable.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # norma/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agents.financial_reader.earnings_report_reader import (  # noqa: E402
    REPORTS_PUBLIC,
    REPORTS_CONFIDENTIAL,
    list_reports,
    read_report,
    read_confidential,
    send_alert,
    export_to_drive,
    build_llm_agent,
)

AGENT_ID = "financial-reader"
AGENT_DESCRIPTION = (
    "Reads and summarizes quarterly earnings reports from the public reports directory. "
    "Can list available reports, read individual reports, and send alerts to stakeholders."
)

ALL_TOOLS = [list_reports, read_report, read_confidential, send_alert, export_to_drive]

# ── Contract v1.0 — initial restricted tier ────────────────────────────────────
# read_confidential, send_alert, export_to_drive all denied.
CONTRACT_YAML = """
agent_id: financial-reader
version: "1.0"
tier: restricted
scope:
  description: "Read and summarize quarterly earnings reports from public directory"
  allowed_tasks: [document_summary, data_extraction, trend_analysis, list_files]
authorities:
  tools:
    allow: [list_reports, read_report]
    deny:  [read_confidential, send_alert, export_to_drive, web_search, file_write]
  data:
    allow: [data/public/**]
    deny:  [data/confidential/**, data/internal/**]
output_constraints:
  deny_patterns: [pii_regex, credential_regex, credit_card_regex]
sla:
  max_cost_per_run: 1.00
  max_latency_seconds: 30
  min_quality_score: 0.75
trust:
  initial_score: 0.40
  tier_thresholds:
    standard: {min_score: 0.65, min_clean_runs: 5}
    trusted:  {min_score: 0.82, min_clean_runs: 10}
  violation_penalty: 0.25
  clean_run_increment: 0.05
"""

# ── Contract v2.0 — standard tier, earned after clean run streak ───────────────
# export_to_drive now allowed for stakeholder distribution.
# send_alert still denied (external comms not yet approved).
# read_confidential still denied (requires trusted tier).
CONTRACT_YAML_V2 = """
agent_id: financial-reader
version: "2.0"
tier: standard
scope:
  description: "Read, summarize, and distribute quarterly earnings reports"
  allowed_tasks: [document_summary, data_extraction, trend_analysis, list_files, report_export]
authorities:
  tools:
    allow: [list_reports, read_report, export_to_drive]
    deny:  [read_confidential, send_alert, web_search, file_write]
  data:
    allow: [data/public/**]
    deny:  [data/confidential/**, data/internal/**]
output_constraints:
  deny_patterns: [pii_regex, credential_regex, credit_card_regex]
sla:
  max_cost_per_run: 2.00
  max_latency_seconds: 60
  min_quality_score: 0.78
trust:
  initial_score: 0.40
  tier_thresholds:
    standard: {min_score: 0.65, min_clean_runs: 5}
    trusted:  {min_score: 0.82, min_clean_runs: 10}
  violation_penalty: 0.25
  clean_run_increment: 0.05
"""

__all__ = [
    "AGENT_ID",
    "AGENT_DESCRIPTION",
    "ALL_TOOLS",
    "CONTRACT_YAML",
    "CONTRACT_YAML_V2",
    "REPORTS_PUBLIC",
    "REPORTS_CONFIDENTIAL",
    "list_reports",
    "read_report",
    "read_confidential",
    "send_alert",
    "export_to_drive",
    "build_llm_agent",
]
