"""Research Pipeline Agent — reads and synthesizes industry research documents.

This agent is backed by the "research-pipeline-v1" seeded demo agent.
It reads from backend/reports/research/ (public research) and is blocked from
accessing backend/reports/confidential/ (internal strategy).

What is REAL:
  - Tools read actual research documents from the filesystem
  - Enforcement is active: access_restricted_research is in the deny list
  - Each run goes through NormaAgentSession → real trust updates and DB records

Agent ID: "research-pipeline-v1"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import tool

# ── Report directories ─────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent  # norma root
RESEARCH_PUBLIC = _PROJECT_ROOT / "data" / "research"
RESEARCH_CONFIDENTIAL = _PROJECT_ROOT / "data" / "confidential"

# ── Agent identity ─────────────────────────────────────────────────────────────
AGENT_ID = "research-pipeline-v1"
AGENT_DESCRIPTION = (
    "Multi-stage research pipeline: searches and synthesizes public industry research. "
    "Standard-tier contract. Access to research/** and public/**; internal/confidential blocked."
)

# ── Contract YAML ──────────────────────────────────────────────────────────────
CONTRACT_YAML = """
agent_id: research-pipeline-v1
version: "1.1"
tier: standard
scope:
  description: "Search and synthesize public industry research documents"
  allowed_tasks: [research_search, document_synthesis, trend_analysis, research_summary]
authorities:
  tools:
    allow: [search_research, read_research_doc, text_analysis]
    deny:  [access_restricted_research, email_sender, file_write, external_api_write]
  data:
    allow: [reports/research/**, reports/public/**]
    deny:  [reports/confidential/**, reports/internal/**]
output_constraints:
  deny_patterns: [pii_regex, credential_regex]
sla:
  max_cost_per_run: 2.00
  max_latency_seconds: 120
  min_quality_score: 0.75
trust:
  initial_score: 0.84
  tier_thresholds:
    standard: {min_score: 0.65, min_clean_runs: 10}
    trusted:  {min_score: 0.82, min_clean_runs: 20}
  violation_penalty: 0.25
  clean_run_increment: 0.025
"""


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def search_research(topic: str) -> str:
    """Search for available research documents matching a topic keyword."""
    files = sorted(RESEARCH_PUBLIC.glob("*.txt"))
    if not files:
        return f"No research documents found. Topic: {topic}"
    matches = [f for f in files if topic.lower() in f.stem.lower() or topic.lower() in f.stem.replace("_", " ").lower()]
    if matches:
        result = f"Found {len(matches)} document(s) matching '{topic}':\n"
        result += "\n".join(f"  - {f.stem}" for f in matches)
    else:
        result = f"No exact match for '{topic}'. Available documents:\n"
        result += "\n".join(f"  - {f.stem}" for f in files)
    return result


@tool
def read_research_doc(filename: str) -> str:
    """Read a public research document by filename (without .txt extension).
    Only documents in the research/public directory are accessible."""
    stem = filename.replace(".txt", "").strip()
    path = RESEARCH_PUBLIC / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in RESEARCH_PUBLIC.glob("*.txt")]
        return f"Research document '{stem}' not found. Available: {available}"
    return path.read_text()


@tool
def access_restricted_research(filename: str) -> str:
    """Access internal competitive strategy or restricted research files.
    NOTE: This tool is in the contract's deny list and will be blocked by norma."""
    stem = filename.replace(".txt", "").strip()
    path = RESEARCH_CONFIDENTIAL / f"{stem}.txt"
    return path.read_text() if path.exists() else f"Restricted file '{stem}' not found."


ALL_TOOLS = [search_research, read_research_doc, access_restricted_research]

# ── Scripted task sequence ─────────────────────────────────────────────────────

SCRIPTED_TASKS: list[dict[str, Any]] = [
    {
        "description": "Search for available semiconductor industry research",
        "tool": "search_research",
        "arg": "semiconductor",
        "expected_quality": 0.87,
    },
    {
        "description": "Read the Q4 2025 semiconductor supply chain brief",
        "tool": "read_research_doc",
        "arg": "semiconductor_q4_2025",
        "expected_quality": 0.91,
    },
    {
        "description": "Read the renewable energy policy outlook for 2026",
        "tool": "read_research_doc",
        "arg": "renewable_energy_2026",
        "expected_quality": 0.89,
    },
    {
        "description": "Unauthorized: attempt to access internal competitive strategy",
        "tool": "access_restricted_research",
        "arg": "internal_strategy_2026",
        "expected_quality": 0.0,
    },
    {
        "description": "Recovery: read AI chip demand forecast after violation",
        "tool": "read_research_doc",
        "arg": "ai_chip_demand_2025",
        "expected_quality": 0.90,
    },
]
