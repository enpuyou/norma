"""Research team agent shim — norma governance infrastructure.

The canonical agent lives in agents/research_team/.
This shim provides CONTRACT_YAML, ALL_TOOLS, and AGENT_ID for use by
norma-watch, onboarding, and the graph endpoint.

The agent file itself knows nothing about norma — only this shim does.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # norma/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agents.research_team.tools import (  # noqa: E402
    list_research_papers,
    fetch_research_paper,
    search_research_by_topic,
    extract_key_metrics,
    summarize_findings,
    draft_executive_report,
    read_restricted_data,
)
from agents.research_team.orchestrator import build_agent  # noqa: E402

AGENT_ID = "research-team"
AGENT_DESCRIPTION = (
    "Multi-agent research pipeline: fetches industry research papers, "
    "extracts key metrics, summarizes findings, and drafts executive reports. "
    "Three-node LangGraph workflow: Fetcher → Analyzer → Writer."
)

ALL_TOOLS = [
    list_research_papers,
    fetch_research_paper,
    search_research_by_topic,
    extract_key_metrics,
    summarize_findings,
    draft_executive_report,
    read_restricted_data,
]

# Contract v1.0 — restricted tier, read_restricted_data denied
CONTRACT_YAML = """
agent_id: research-team
version: "1.0"
tier: restricted
scope:
  description: "Research pipeline: fetch papers, extract metrics, draft executive reports"
  allowed_tasks:
    - document_retrieval
    - metric_extraction
    - research_summarization
    - report_drafting
    - topic_search
authorities:
  tools:
    allow:
      - list_research_papers
      - fetch_research_paper
      - search_research_by_topic
      - extract_key_metrics
      - summarize_findings
      - draft_executive_report
    deny:
      - read_restricted_data
  data:
    allow:
      - data/research/**
    deny:
      - data/confidential/**
      - data/internal/**
output_constraints:
  deny_patterns:
    - pii_regex
    - credential_regex
    - credit_card_regex
sla:
  max_cost_per_run: 2.00
  max_latency_seconds: 120
  min_quality_score: 0.75
  max_tool_calls_per_run: 20
trust:
  initial_score: 0.40
  tier_thresholds:
    standard:
      min_score: 0.65
      min_clean_runs: 5
    trusted:
      min_score: 0.82
      min_clean_runs: 10
  violation_penalty: 0.25
  clean_run_increment: 0.05
"""

# Contract v2.0 — standard tier, read_restricted_data still denied but broader data access
CONTRACT_YAML_V2 = """
agent_id: research-team
version: "2.0"
tier: standard
scope:
  description: "Research pipeline with expanded data access for verified research team"
  allowed_tasks:
    - document_retrieval
    - metric_extraction
    - research_summarization
    - report_drafting
    - topic_search
    - cross_domain_analysis
authorities:
  tools:
    allow:
      - list_research_papers
      - fetch_research_paper
      - search_research_by_topic
      - extract_key_metrics
      - summarize_findings
      - draft_executive_report
    deny:
      - read_restricted_data
  data:
    allow:
      - data/research/**
      - data/compliance/**
    deny:
      - data/confidential/**
output_constraints:
  deny_patterns:
    - pii_regex
    - credential_regex
    - credit_card_regex
sla:
  max_cost_per_run: 5.00
  max_latency_seconds: 180
  min_quality_score: 0.78
  max_tool_calls_per_run: 30
trust:
  initial_score: 0.40
  tier_thresholds:
    standard:
      min_score: 0.65
      min_clean_runs: 5
    trusted:
      min_score: 0.82
      min_clean_runs: 10
  violation_penalty: 0.25
  clean_run_increment: 0.05
"""

__all__ = [
    "AGENT_ID",
    "AGENT_DESCRIPTION",
    "ALL_TOOLS",
    "CONTRACT_YAML",
    "CONTRACT_YAML_V2",
    "build_agent",
]
