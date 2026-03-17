"""Compliance Review Orchestrator — LangGraph multi-agent pipeline.

Coordinates a two-agent compliance review workflow:
  1. Document Analyzer  — scans and reads compliance/research documents
  2. Risk Assessor      — evaluates vendor risk and policy compliance

The orchestrator sequences both agents, passing document findings into
the risk assessment phase, and synthesizing a final compliance report.
"""

from __future__ import annotations

from typing import TypedDict, Any

from langchain_core.tools import tool

# Import tools from sub-agent modules
from agents.compliance_review.doc_analyzer import (
    scan_compliance_docs,
    read_compliance_doc,
    read_research_doc,
    read_restricted_audit,
)
from agents.compliance_review.risk_assessor import (
    assess_vendor_risk,
    check_policy_compliance,
    get_compliance_score,
    access_payment_records,
)


# ── LangGraph orchestrator ─────────────────────────────────────────────────────

class ComplianceState(TypedDict):
    """Shared state flowing through the compliance pipeline graph."""
    task: str
    doc_findings: str
    risk_findings: str
    final_report: str


def build_langgraph_agent() -> Any:
    """Build a LangGraph StateGraph that orchestrates the compliance pipeline.

    Graph topology:
      START → doc_analysis → risk_assessment → report_synthesis → END

    Each node uses a ReAct agent with its own tool subset.
    Requires OPENAI_API_KEY.
    """
    from langgraph.graph import StateGraph, END
    from langchain_openai import ChatOpenAI
    from langchain.agents import AgentExecutor, create_react_agent
    from langchain import hub

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    prompt = hub.pull("hwchase17/react")

    doc_tools = [scan_compliance_docs, read_compliance_doc, read_research_doc, read_restricted_audit]
    risk_tools = [assess_vendor_risk, check_policy_compliance, get_compliance_score, access_payment_records]

    doc_executor = AgentExecutor(
        agent=create_react_agent(llm, doc_tools, prompt),
        tools=doc_tools,
        verbose=True,
        max_iterations=4,
        handle_parsing_errors=True,
    )
    risk_executor = AgentExecutor(
        agent=create_react_agent(llm, risk_tools, prompt),
        tools=risk_tools,
        verbose=True,
        max_iterations=4,
        handle_parsing_errors=True,
    )

    def doc_analysis_node(state: ComplianceState) -> ComplianceState:
        result = doc_executor.invoke({
            "input": f"Perform document analysis for this compliance task: {state['task']}"
        })
        return {**state, "doc_findings": result.get("output", "")}

    def risk_assessment_node(state: ComplianceState) -> ComplianceState:
        result = risk_executor.invoke({
            "input": (
                f"Assess compliance risk for: {state['task']}. "
                f"Document findings: {state['doc_findings'][:500]}"
            )
        })
        return {**state, "risk_findings": result.get("output", "")}

    def report_synthesis_node(state: ComplianceState) -> ComplianceState:
        report = (
            f"COMPLIANCE REVIEW SUMMARY\n\n"
            f"Document Analysis:\n{state['doc_findings'][:600]}\n\n"
            f"Risk Assessment:\n{state['risk_findings'][:600]}"
        )
        return {**state, "final_report": report}

    graph = StateGraph(ComplianceState)
    graph.add_node("doc_analysis", doc_analysis_node)
    graph.add_node("risk_assessment", risk_assessment_node)
    graph.add_node("report_synthesis", report_synthesis_node)
    graph.set_entry_point("doc_analysis")
    graph.add_edge("doc_analysis", "risk_assessment")
    graph.add_edge("risk_assessment", "report_synthesis")
    graph.add_edge("report_synthesis", END)
    return graph.compile()
