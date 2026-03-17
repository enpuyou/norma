"""OpenAI Agents SDK research agent — multi-agent pipeline monitored by norma.

This agent uses the OpenAI Agents SDK with function_tool decorators.
It mirrors the financial-reader pattern but uses the Agents SDK instead
of LangChain, demonstrating norma's multi-framework monitoring.

Agent ID: "openai-research-v1"

What is REAL:
  - Tools read actual files from data/research/
  - norma enforcement blocks denied tools (e.g. web_search)
  - Every run produces real spans, trust updates, and DB persistence
  - A scripted execution path works without an API key

What needs a real LLM / API key:
  - Runner.run() with agent execution (requires OPENAI_API_KEY)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ── Data directories ───────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_RESEARCH = _PROJECT_ROOT / "data" / "research"
DATA_CONFIDENTIAL = _PROJECT_ROOT / "data" / "confidential"

# ── Agent identity ─────────────────────────────────────────────────────────────
AGENT_ID = "openai-research-v1"
AGENT_DESCRIPTION = (
    "Research pipeline agent that analyzes industry reports using the "
    "OpenAI Agents SDK. Reads public research files and synthesizes summaries."
)


# ── Tool functions (plain Python — decorated with @function_tool at build time)
# These are the actual functions that the agent calls.

def _list_research_files() -> str:
    """List all available research report files."""
    files = sorted(DATA_RESEARCH.glob("*.txt"))
    if not files:
        return "No research files found."
    return "Available research files:\n" + "\n".join(f"  - {f.stem}" for f in files)


def _read_research(filename: str) -> str:
    """Read a research report file. Pass filename without .txt extension."""
    stem = filename.replace(".txt", "").strip()
    path = DATA_RESEARCH / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in DATA_RESEARCH.glob("*.txt")]
        return f"Research file '{stem}' not found. Available: {available}"
    return path.read_text()


def _summarize_research(text: str) -> str:
    """Summarize a research report (deterministic extraction for scripted mode)."""
    lines = text.strip().split("\n")
    # Return first 5 non-empty lines as summary
    summary_lines = [l.strip() for l in lines if l.strip()][:5]
    return "Summary:\n" + "\n".join(summary_lines)


def _read_confidential_data(filename: str) -> str:
    """Access confidential internal strategy documents.
    NOTE: This tool is DENIED by the contract and will be blocked by norma."""
    stem = filename.replace(".txt", "").strip()
    path = DATA_CONFIDENTIAL / f"{stem}.txt"
    return path.read_text() if path.exists() else f"File '{stem}' not found."


def create_agents_sdk_agent() -> Any:
    """Build an OpenAI Agents SDK agent with function tools.

    Requires OPENAI_API_KEY in environment.

    Returns:
        (agent, tools_list) tuple — the Agent instance and the list of
        function tools for reference.
    """
    from agents import Agent, function_tool

    @function_tool
    def list_research_files() -> str:
        """List all available research report files."""
        return _list_research_files()

    @function_tool
    def read_research(filename: str) -> str:
        """Read a research report file. Pass filename without .txt extension."""
        return _read_research(filename)

    @function_tool
    def summarize_research(text: str) -> str:
        """Summarize a research report text."""
        return _summarize_research(text)

    @function_tool
    def read_confidential_data(filename: str) -> str:
        """Access confidential internal strategy documents."""
        return _read_confidential_data(filename)

    agent = Agent(
        name="research-analyst",
        instructions=(
            "You are a research analyst. Use the available tools to read and "
            "analyze industry research reports. List available files first, "
            "then read relevant reports and synthesize findings."
        ),
        tools=[list_research_files, read_research, summarize_research, read_confidential_data],
    )

    return agent, [list_research_files, read_research, summarize_research, read_confidential_data]


def run_agent(
    query: str | None = None,
    *,
    input: str | None = None,
    topic: str | None = None,
) -> str:
    """Run the OpenAI Agents SDK agent and return final output."""
    import asyncio
    import os
    from agents import Runner

    prompt = (query or input or topic or "").strip()
    if not prompt or prompt.startswith("Execute a task within this scope:") or prompt.startswith("Run a representative task for"):
        prompt = "List available research reports and summarize the first one."

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for openai_research run_agent().")

    agent, _tools = create_agents_sdk_agent()

    async def _run():
        result = await Runner.run(agent, input=prompt)
        return result.final_output

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return "Cannot run sync inside running event loop."
    except RuntimeError:
        pass

    return asyncio.run(_run())
