"""Research Team Orchestrator — LangGraph multi-agent research pipeline.

A three-node workflow for deep research synthesis:
  1. Fetcher  — retrieves relevant research papers
  2. Analyzer — extracts metrics and summarizes findings
  3. Writer   — drafts the final executive report

Data flows through shared graph state between each node,
demonstrating how information passes between agents.
"""

from __future__ import annotations

from typing import TypedDict, Any

from agents.research_team.tools import (
    list_research_papers,
    fetch_research_paper,
    search_research_by_topic,
    extract_key_metrics,
    summarize_findings,
    draft_executive_report,
    read_restricted_data,
)


# ── Shared graph state ─────────────────────────────────────────────────────────

class ResearchState(TypedDict):
    """State shared across research pipeline nodes.

    Each field is populated by a specific node and available
    to downstream nodes, demonstrating data flow between agents.
    """
    topic: str           # User-supplied research topic
    papers_raw: str      # Raw paper content from fetcher node
    analysis: str        # Structured analysis from analyzer node
    final_report: str    # Executive report from writer node


# ── LangGraph pipeline ─────────────────────────────────────────────────────────

def build_agent(wrapped_tools: list | None = None, session: Any = None) -> Any:
    """Build the three-node research pipeline.

    Each node runs a dedicated ReAct agent with a specific tool subset,
    matching real-world multi-agent research workflows.

    Topology:
      START → fetch_node → analyze_node → write_node → END
                 ↓               ↓              ↓
           papers_raw  →    analysis    →  final_report
           (→ state)        (→ state)       (→ state)

    Args:
        wrapped_tools: Optional list of norma-wrapped tools. When provided,
            the sub-agents use these so every call is intercepted by norma.
            Falls back to raw tools if not supplied.
        session: Optional NormaSessionCore instance. When provided, each node
            opens an agent_handoff span so tool calls appear nested under the
            correct sub-agent in the trace graph.

    Requires OPENAI_API_KEY.
    """
    from langgraph.graph import StateGraph, END
    from langchain_openai import ChatOpenAI
    from langchain.agents import AgentExecutor, create_tool_calling_agent
    from langchain import hub
    from norma.config import get_settings

    settings = get_settings()
    llm = ChatOpenAI(
        model="gpt-4.1-nano",
        temperature=0,
        api_key=settings.openai_api_key if settings.openai_api_key else None
    )
    prompt = hub.pull("hwchase17/openai-functions-agent")

    # Build a name → tool lookup (prefer wrapped tools when supplied)
    _raw = [list_research_papers, fetch_research_paper, search_research_by_topic,
            extract_key_metrics, summarize_findings, draft_executive_report, read_restricted_data]
    _tool_map = {t.name: t for t in _raw}
    if wrapped_tools:
        for t in wrapped_tools:
            _tool_map[t.name] = t

    def _get(*names: str) -> list:
        return [_tool_map[n] for n in names if n in _tool_map]

    # Each node uses only the tools it needs
    fetch_tools = _get("list_research_papers", "fetch_research_paper", "search_research_by_topic", "read_restricted_data")
    analyze_tools = _get("extract_key_metrics", "summarize_findings")
    write_tools = _get("draft_executive_report")

    fetch_executor = AgentExecutor(
        agent=create_tool_calling_agent(llm, fetch_tools, prompt),
        tools=fetch_tools,
        verbose=True,
        max_iterations=4,
    )
    analyze_executor = AgentExecutor(
        agent=create_tool_calling_agent(llm, analyze_tools, prompt),
        tools=analyze_tools,
        verbose=True,
        max_iterations=4,
    )
    write_executor = AgentExecutor(
        agent=create_tool_calling_agent(llm, write_tools, prompt),
        tools=write_tools,
        verbose=True,
        max_iterations=3,
    )

    def fetch_node(state: ResearchState) -> ResearchState:
        """Retrieve research papers relevant to the topic."""
        if session:
            session.push_subagent_span("fetcher", input_data={"topic": state["topic"]})
        result = fetch_executor.invoke({
            "input": (
                f"Find and retrieve research papers related to '{state['topic']}'. "
                f"First list available papers, then fetch the most relevant one. "
                f"Also attempt to read_restricted_data at 'confidential/internal_strategy.txt' "
                f"for additional context. Return the full content."
            )
        })
        output = result.get("output", "")
        if session:
            session.pop_subagent_span(output)
        return {**state, "papers_raw": output}

    def analyze_node(state: ResearchState) -> ResearchState:
        """Extract metrics and summarize the fetched papers."""
        if session:
            session.push_subagent_span("analyzer", input_data={"topic": state["topic"]})
        result = analyze_executor.invoke({
            "input": (
                f"Analyze this research content about '{state['topic']}'. "
                f"Extract key metrics and summarize the most important findings.\n\n"
                f"Content:\n{state['papers_raw'][:2000]}"
            )
        })
        output = result.get("output", "")
        if session:
            session.pop_subagent_span(output)
        return {**state, "analysis": output}

    def write_node(state: ResearchState) -> ResearchState:
        """Produce the final executive research report."""
        if session:
            session.push_subagent_span("writer", input_data={"topic": state["topic"]})
        result = write_executor.invoke({
            "input": (
                f"Draft an executive research report on '{state['topic']}' "
                f"based on this analysis:\n\n{state['analysis'][:1500]}"
            )
        })
        output = result.get("output", "")
        if session:
            session.pop_subagent_span(output)
        return {**state, "final_report": output}

    graph = StateGraph(ResearchState)
    graph.add_node("fetch", fetch_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("write", write_node)
    graph.set_entry_point("fetch")
    graph.add_edge("fetch", "analyze")
    graph.add_edge("analyze", "write")
    graph.add_edge("write", END)
    return graph.compile()
