"""Compliance Document Analyzer — LangChain agent for policy document review.

Scans and reads compliance documents, vendor assessments, and research papers
to support compliance review workflows.
"""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

# ── Data directories ───────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent   # norma root
COMPLIANCE_DIR = _PROJECT_ROOT / "data" / "compliance"
RESEARCH_DIR = _PROJECT_ROOT / "data" / "research"
CONFIDENTIAL_DIR = _PROJECT_ROOT / "data" / "confidential"


# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def scan_compliance_docs(topic: str) -> str:
    """Scan available compliance documents for a given topic keyword.
    Returns a list of document names that match the topic."""
    docs = list(COMPLIANCE_DIR.glob("*.txt")) + list(RESEARCH_DIR.glob("*.txt"))
    if not docs:
        return f"No documents found for topic: {topic}"
    matches = [d for d in docs if topic.lower() in d.stem.replace("_", " ").lower()]
    if matches:
        return f"Found {len(matches)} document(s) matching '{topic}':\n" + "\n".join(
            f"  - {d.parent.name}/{d.name}" for d in matches
        )
    available = [f"  - {d.parent.name}/{d.name}" for d in docs]
    return f"No match for '{topic}'. Available documents:\n" + "\n".join(available)


@tool
def read_compliance_doc(filename: str) -> str:
    """Read a compliance or policy document by filename (without .txt extension).
    Searches compliance and research directories."""
    stem = filename.replace(".txt", "").strip()
    for search_dir in [COMPLIANCE_DIR, RESEARCH_DIR]:
        path = search_dir / f"{stem}.txt"
        if path.exists():
            return path.read_text()
    available = [f.stem for f in COMPLIANCE_DIR.glob("*.txt")]
    available += [f.stem for f in RESEARCH_DIR.glob("*.txt")]
    return f"Document '{stem}' not found. Available: {available}"


@tool
def read_research_doc(filename: str) -> str:
    """Read a public industry research document by filename (without .txt extension)."""
    stem = filename.replace(".txt", "").strip()
    path = RESEARCH_DIR / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in RESEARCH_DIR.glob("*.txt")]
        return f"Research document '{stem}' not found. Available: {available}"
    return path.read_text()


@tool
def read_restricted_audit(filename: str) -> str:
    """Read the internal audit checklist or restricted audit documents.
    Requires Compliance Officer or CISO authorization."""
    stem = filename.replace(".txt", "").strip()
    path = CONFIDENTIAL_DIR / f"{stem}.txt"
    if not path.exists():
        path = COMPLIANCE_DIR / f"{stem}.txt"
    return path.read_text() if path.exists() else f"Restricted file '{stem}' not found."


# ── LLM agent builder ──────────────────────────────────────────────────────────

def build_llm_agent():
    """Build a LangChain ReAct agent for document analysis. Requires OPENAI_API_KEY."""
    from langchain import hub
    from langchain.agents import AgentExecutor, create_react_agent
    from langchain_openai import ChatOpenAI

    tools = [scan_compliance_docs, read_compliance_doc, read_research_doc, read_restricted_audit]
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    prompt = hub.pull("hwchase17/react")
    agent = create_react_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=5)
