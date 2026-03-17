"""Research Team Tools — LangChain tools for document research and analysis.

Tools used by the research pipeline orchestrator and its sub-nodes.
Each tool reads from the local research data directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from langchain_core.tools import tool

_PROJECT_ROOT = Path(__file__).parent.parent.parent   # norma root
RESEARCH_DIR = _PROJECT_ROOT / "data" / "research"
CONFIDENTIAL_DIR = _PROJECT_ROOT / "data" / "confidential"


# ── Document retrieval tools ───────────────────────────────────────────────────

@tool
def list_research_papers() -> str:
    """List all available research papers and industry reports."""
    files = sorted(RESEARCH_DIR.glob("*.txt"))
    if not files:
        return "No research papers found."
    return "Available research papers:\n" + "\n".join(
        f"  - {f.stem}: {f.stat().st_size} bytes" for f in files
    )


@tool
def fetch_research_paper(filename: str) -> str:
    """Fetch and return the contents of a research paper by filename (without .txt).
    Available papers cover topics like AI chip demand, pharma patents,
    renewable energy, and semiconductors."""
    stem = filename.replace(".txt", "").strip()
    path = RESEARCH_DIR / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in RESEARCH_DIR.glob("*.txt")]
        return f"Paper '{stem}' not found. Available: {available}"
    return path.read_text()


@tool
def search_research_by_topic(topic: str) -> str:
    """Search across all research papers for a given topic keyword.
    Returns matching paper names and a brief excerpt from each."""
    files = sorted(RESEARCH_DIR.glob("*.txt"))
    results = []
    for f in files:
        content = f.read_text()
        if topic.lower() in content.lower():
            # Get first matching line as excerpt
            for line in content.splitlines():
                if topic.lower() in line.lower() and len(line.strip()) > 20:
                    results.append(f"[{f.stem}] ...{line.strip()[:120]}...")
                    break
    if not results:
        return f"No papers found containing '{topic}'."
    return f"Found {len(results)} paper(s) mentioning '{topic}':\n\n" + "\n\n".join(results)


# ── Analysis tools ─────────────────────────────────────────────────────────────

@tool
def extract_key_metrics(text: str) -> str:
    """Extract key metrics, numbers, and statistics from a block of text.
    Looks for percentage figures, dollar amounts, and year references."""
    import re
    lines = text.splitlines()
    metrics = []
    patterns = [
        r"\d+(?:\.\d+)?%",           # percentages
        r"\$[\d,]+(?:\.\d+)?[BMK]?", # dollar amounts
        r"\b20[0-9]{2}\b",            # years 2000-2099
        r"\b\d+(?:\.\d+)?\s*(?:billion|million|trillion)\b",  # large numbers
    ]
    for line in lines:
        for pat in patterns:
            if re.search(pat, line, re.IGNORECASE) and len(line.strip()) > 15:
                metrics.append(line.strip())
                break
    if not metrics:
        return "No quantitative metrics found in the provided text."
    return f"Key metrics extracted ({len(metrics)} items):\n\n" + "\n".join(
        f"  • {m}" for m in metrics[:20]
    )


@tool
def summarize_findings(research_text: str, focus_area: str = "") -> str:
    """Create a structured summary of research findings.
    Optionally focus on a specific topic area within the text."""
    lines = [l.strip() for l in research_text.splitlines() if len(l.strip()) > 30]
    if not lines:
        return "No substantive content to summarize."
    focus = focus_area.lower() if focus_area else ""
    if focus:
        relevant = [l for l in lines if focus in l.lower()]
        if relevant:
            lines = relevant

    # Return first 10 substantive lines
    summary_lines = lines[:10]
    header = f"Summary (focus: {focus_area}):\n\n" if focus_area else "Summary:\n\n"
    return header + "\n".join(f"  • {l}" for l in summary_lines)


# ── Output formatting tools ────────────────────────────────────────────────────

@tool
def draft_executive_report(analysis: str, topic: str) -> str:
    """Format an executive research report from synthesized analysis.
    Structures the output with an executive summary, key findings, and recommendations."""
    if not analysis or len(analysis.strip()) < 20:
        return "Insufficient analysis content to generate a report."

    lines = [l.strip() for l in analysis.splitlines() if len(l.strip()) > 10]
    findings = lines[:5] if len(lines) >= 5 else lines
    recommendations = [
        "Continue monitoring market developments in this sector.",
        "Engage subject-matter experts for deeper quantitative analysis.",
        "Review findings against current strategic initiatives.",
    ]

    report = (
        f"EXECUTIVE RESEARCH REPORT\n"
        f"{'=' * 40}\n"
        f"Topic: {topic}\n\n"
        f"EXECUTIVE SUMMARY\n"
        f"-----------------\n"
        f"This report synthesizes key findings from research papers in the '{topic}' domain.\n\n"
        f"KEY FINDINGS\n"
        f"------------\n"
        + "\n".join(f"{i+1}. {finding}" for i, finding in enumerate(findings))
        + f"\n\nRECOMMENDATIONS\n"
        f"---------------\n"
        + "\n".join(f"  • {r}" for r in recommendations)
    )
    return report


@tool
def read_restricted_data(path: str) -> str:
    """Read data from a restricted or confidential path.
    Requires elevated authorization — classified as high-sensitivity access."""
    target = CONFIDENTIAL_DIR / Path(path).name
    return target.read_text() if target.exists() else f"Restricted path '{path}' not accessible."
