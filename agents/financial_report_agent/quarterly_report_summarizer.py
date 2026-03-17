"""Financial Report Agent — reads and summarizes earnings reports under a restricted contract.

This agent is the "original" version that seeded demo data (financial-report-agent-v1).
It uses the same file-read tools as financial-reader-v1 but runs under the v1.0
restricted-tier contract, demonstrating the earlier lifecycle stage.

What is REAL:
  - Tools read actual files from backend/reports/public/
  - Enforcement is active: read_confidential is in the deny list
  - Each run goes through NormaAgentSession → real trust updates and DB records

Agent ID: "financial-report-agent-v1"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import tool

# ── Report directories ─────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent  # norma root
REPORTS_PUBLIC = _PROJECT_ROOT / "data" / "public"
REPORTS_CONFIDENTIAL = _PROJECT_ROOT / "data" / "confidential"

# ── Agent identity ─────────────────────────────────────────────────────────────
AGENT_ID = "financial-report-agent-v1"
AGENT_DESCRIPTION = (
    "Summarizes quarterly earnings reports for the Finance department. "
    "Restricted-tier contract: public reports only; confidential access denied."
)

# ── Contract YAML ──────────────────────────────────────────────────────────────
#
# Mirrors the v1.0 restricted contract used by the seeded demo workflow, but
# updated to reflect the actual LangChain tool names used here.
#
CONTRACT_YAML = """
agent_id: financial-report-agent-v1
version: "1.0"
tier: restricted
scope:
  description: "Summarize quarterly earnings reports from public directory"
  allowed_tasks: [document_summary, data_extraction, trend_analysis, list_files]
authorities:
  tools:
    allow: [list_reports, read_report, text_analysis]
    deny:  [read_confidential, web_search, email_sender, external_api, file_write]
  data:
    allow: [reports/public/**]
    deny:  [reports/internal/**, reports/confidential/**]
output_constraints:
  deny_patterns: [pii_regex, credential_regex, credit_card_regex]
sla:
  max_cost_per_run: 0.50
  max_latency_seconds: 30
  min_quality_score: 0.80
trust:
  initial_score: 0.40
  tier_thresholds:
    standard: {min_score: 0.65, min_clean_runs: 10}
    trusted:  {min_score: 0.82, min_clean_runs: 20}
  violation_penalty: 0.25
  clean_run_increment: 0.025
"""


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def list_reports() -> str:
    """List all available quarterly earnings reports in the public directory."""
    files = sorted(REPORTS_PUBLIC.glob("*.txt"))
    if not files:
        return "No reports found in public directory."
    return "Available reports:\n" + "\n".join(f"  - {f.stem}" for f in files)


@tool
def read_report(filename: str) -> str:
    """Read a quarterly earnings report by filename (without .txt extension).
    Only public reports are accessible under this contract."""
    stem = filename.replace(".txt", "").strip()
    path = REPORTS_PUBLIC / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in REPORTS_PUBLIC.glob("*.txt")]
        return f"Report '{stem}' not found. Available: {available}"
    return path.read_text()


@tool
def read_confidential(filename: str) -> str:
    """Read a confidential executive report.
    NOTE: This tool is in the contract's deny list and will be blocked by norma."""
    stem = filename.replace(".txt", "").strip()
    path = REPORTS_CONFIDENTIAL / f"{stem}.txt"
    return path.read_text() if path.exists() else f"File '{stem}' not found."


ALL_TOOLS = [list_reports, read_report, read_confidential]


# ── LLM agent builder ──────────────────────────────────────────────────────────

def build_llm_agent():
    """Build a LangChain ReAct agent for earnings report summarization."""
    from langchain_openai import ChatOpenAI
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain import hub
    from norma.config import get_settings

    settings = get_settings()
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=settings.openai_api_key if settings.openai_api_key else None,
    )
    prompt = hub.pull("hwchase17/openai-functions-agent")
    agent = create_tool_calling_agent(llm, ALL_TOOLS, prompt)
    return AgentExecutor(agent=agent, tools=ALL_TOOLS, verbose=True, max_iterations=4)


# ── Scripted task sequence ─────────────────────────────────────────────────────

SCRIPTED_TASKS: list[dict[str, Any]] = [
    {
        "description": "Inventory: list available quarterly report files",
        "tool": "list_reports",
        "arg": None,
        "expected_quality": 0.88,
    },
    {
        "description": "Read and extract key metrics from Q4 2025 earnings",
        "tool": "read_report",
        "arg": "q4_2025_earnings",
        "expected_quality": 0.90,
    },
    {
        "description": "Read and extract key metrics from Q3 2025 earnings",
        "tool": "read_report",
        "arg": "q3_2025_earnings",
        "expected_quality": 0.89,
    },
    {
        "description": "Unauthorized: attempt to read confidential executive compensation",
        "tool": "read_confidential",
        "arg": "exec_compensation_2025",
        "expected_quality": 0.0,
    },
    {
        "description": "Recovery run: read Q2 2025 earnings after violation",
        "tool": "read_report",
        "arg": "q2_2025_earnings",
        "expected_quality": 0.88,
    },
]
