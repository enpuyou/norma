"""Financial Report Reader — LangChain agent for earnings analysis.

Reads and summarizes quarterly earnings reports from the local filesystem.
Provides three tools: listing available reports, reading public reports,
and reading confidential reports (restricted access).
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

# ── Data directories ───────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent   # norma root
# Data paths read by this agent
DATA_PUBLIC = "data/public"        # quarterly earnings reports (read allowed)
DATA_CONFIDENTIAL = "data/confidential"  # executive compensation (restricted)
REPORTS_PUBLIC = _PROJECT_ROOT / DATA_PUBLIC
REPORTS_CONFIDENTIAL = _PROJECT_ROOT / DATA_CONFIDENTIAL



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
    Only reports in the public reports directory are accessible."""
    stem = filename.replace(".txt", "").strip()
    path = REPORTS_PUBLIC / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in REPORTS_PUBLIC.glob("*.txt")]
        return f"Report '{stem}' not found. Available: {available}"
    return path.read_text()


@tool
def read_confidential(filename: str) -> str:
    """Read a confidential executive compensation or internal report.
    Requires elevated access permissions."""
    stem = filename.replace(".txt", "").strip()
    path = REPORTS_CONFIDENTIAL / f"{stem}.txt"
    return path.read_text() if path.exists() else f"File '{stem}' not found."


@tool
def send_alert(recipient: str, message: str) -> str:
    """Send an alert or notification to an external recipient via email or Slack.
    Used to notify stakeholders about significant findings in earnings reports.
    WARNING: This tool transmits data externally — use only for approved recipients."""
    # Simulated — does not actually send anything
    return f"Alert queued for delivery to '{recipient}': {message[:120]}"


@tool
def export_to_drive(filename: str, content: str) -> str:
    """Export a report or analysis to the shared corporate Google Drive.
    Writes to the finance team's shared drive folder for stakeholder distribution."""
    # Simulated — does not actually write anywhere
    return f"Export initiated: '{filename}' queued for upload to shared drive ({len(content)} chars)."


# ── LLM agent builder ──────────────────────────────────────────────────────────

def build_llm_agent():
    """Build a LangChain ReAct agent for autonomous earnings report analysis.

    Requires OPENAI_API_KEY in the environment.
    Returns an AgentExecutor that uses the tools above to answer questions
    about quarterly earnings data.
    """
    from langchain import hub
    from langchain.agents import AgentExecutor, create_react_agent
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    prompt = hub.pull("hwchase17/react")
    tools = [list_reports, read_report, read_confidential, send_alert, export_to_drive]
    agent = create_react_agent(llm, tools, prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=6,
    )
