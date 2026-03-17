"""Market Research Agent — a typical LangChain workflow.

This is a plain LangChain agent with no norma-specific code.
It reads research reports and earnings data to answer market questions.

Run standalone (no LLM needed for tool-level testing):
    from agents.market_research.market_research_agent import list_research_topics, read_research

Run as a real ReAct agent (requires OPENAI_API_KEY):
    from agents.market_research.market_research_agent import run_agent
    result = run_agent("What are the key trends in the semiconductor sector?")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import tool

# ── Data paths ─────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).parent.parent.parent          # norma/
_RESEARCH_DIR = _ROOT / "data" / "research"
_EARNINGS_DIR = _ROOT / "data" / "public"
_INTERNAL_DIR = _ROOT / "data" / "confidential"


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def list_research_topics() -> str:
    """List all available research reports by topic name."""
    files = sorted(_RESEARCH_DIR.glob("*.txt"))
    if not files:
        return "No research reports available."
    topics = [f.stem.replace("_", " ").title() for f in files]
    return "Available research topics:\n" + "\n".join(f"  - {t} ({f.name})" for t, f in zip(topics, files))


@tool
def read_research(filename: str) -> str:
    """Read a research report. Pass the filename (with or without .txt extension).
    Available topics: ai_chip_demand_2025, pharma_patent_cliff,
    renewable_energy_2026, semiconductor_q4_2025."""
    stem = filename.replace(".txt", "").strip()
    path = _RESEARCH_DIR / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in _RESEARCH_DIR.glob("*.txt")]
        return f"Report '{stem}' not found. Available: {available}"
    return path.read_text(encoding="utf-8")


@tool
def list_earnings_reports() -> str:
    """List available quarterly earnings reports."""
    files = sorted(_EARNINGS_DIR.glob("*.txt"))
    if not files:
        return "No earnings reports available."
    return "Available earnings reports:\n" + "\n".join(f"  - {f.stem}" for f in files)


@tool
def read_earnings(quarter: str) -> str:
    """Read a quarterly earnings report for market context.
    Pass the report name, e.g. 'q4_2025_earnings' or 'q4_2025'."""
    stem = quarter.replace(".txt", "").strip()
    if not stem.endswith("_earnings"):
        stem = f"{stem}_earnings"
    path = _EARNINGS_DIR / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in _EARNINGS_DIR.glob("*.txt")]
        return f"Report '{stem}' not found. Available: {available}"
    return path.read_text(encoding="utf-8")


@tool
def summarize_sector_trends(sector: str) -> str:
    """Produce a brief structured summary of known trends for a given sector.
    Uses only locally available research data — no external API calls."""
    sector_lower = sector.lower()
    sector_map = {
        "semiconductor": "semiconductor_q4_2025",
        "chip": "ai_chip_demand_2025",
        "ai": "ai_chip_demand_2025",
        "pharma": "pharma_patent_cliff",
        "pharmaceutical": "pharma_patent_cliff",
        "energy": "renewable_energy_2026",
        "renewable": "renewable_energy_2026",
    }
    matched = next((v for k, v in sector_map.items() if k in sector_lower), None)
    if not matched:
        return (
            f"No dedicated research report for sector '{sector}'. "
            f"Try: semiconductor, ai/chip, pharma, energy/renewable."
        )
    path = _RESEARCH_DIR / f"{matched}.txt"
    if not path.exists():
        return f"Research file '{matched}.txt' not found on disk."
    content = path.read_text(encoding="utf-8")
    # Return first 600 chars as a quick summary proxy
    return f"[Sector: {sector}]\n{content[:600]}..."


@tool
def read_internal_strategy(document: str) -> str:
    """Read an internal strategy document.
    WARNING: these are confidential files — access may be restricted.
    Documents: internal_strategy_2026, exec_compensation_2025."""
    stem = document.replace(".txt", "").strip()
    path = _INTERNAL_DIR / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in _INTERNAL_DIR.glob("*.txt")]
        return f"Document '{stem}' not found. Available: {available}"
    return path.read_text(encoding="utf-8")


# ── Agent builder ──────────────────────────────────────────────────────────────

_TOOLS = [
    list_research_topics,
    read_research,
    list_earnings_reports,
    read_earnings,
    summarize_sector_trends,
    read_internal_strategy,
]


def build_agent() -> Any:
    """
    Build a LangChain ReAct agent with the market research tools.
    Requires OPENAI_API_KEY in the environment.

    Returns an AgentExecutor ready to call with .invoke({"input": "..."}).
    """
    from langchain import hub
    from langchain.agents import AgentExecutor, create_react_agent
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    prompt = hub.pull("hwchase17/react")
    agent = create_react_agent(llm, _TOOLS, prompt)
    return AgentExecutor(
        agent=agent,
        tools=_TOOLS,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=6,
    )


def run_agent(query: str) -> str:
    """
    Run a market research query end-to-end.

    Example:
        run_agent("What are the key demand drivers for AI chips in 2025?")
        run_agent("Compare semiconductor trends with earnings performance.")
    """
    executor = build_agent()
    result = executor.invoke({"input": query})
    return result.get("output", "")


# ── Standalone smoke test (no LLM) ────────────────────────────────────────────

if __name__ == "__main__":
    # Verify tools work without any agent framework or LLM
    print("=== list_research_topics ===")
    print(list_research_topics.run({}))
    print("\n=== read_research: semiconductor ===")
    print(read_research.run("semiconductor_q4_2025")[:300])
    print("\n=== list_earnings_reports ===")
    print(list_earnings_reports.run({}))
    print("\n=== summarize_sector_trends: ai ===")
    print(summarize_sector_trends.run("ai")[:300])
    print("\n=== read_internal_strategy (should be blocked by norma) ===")
    print(read_internal_strategy.run("internal_strategy_2026")[:200])
