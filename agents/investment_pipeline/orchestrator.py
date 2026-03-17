"""Investment Research Pipeline — 4-node LangGraph orchestrator demonstrating:
  - Multi-step agent workflows with real data flow
  - Cost tracking across different model tiers (gpt-4o vs gpt-4o-mini)
  - Quality variance between analysis steps
  - norma.ai governance monitoring

Pipeline: market_scanner → news_analyzer → risk_assessor → report_writer

Run from the norma dashboard (Execute → mode=full) or terminal:
    python agents/investment_pipeline/orchestrator.py "NVDA"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, TypedDict

_AGENTS_DIR = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _AGENTS_DIR.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from langgraph.graph import StateGraph, END
    _HAS_LANGGRAPH = True
except ImportError:
    _HAS_LANGGRAPH = False

try:
    from langchain_openai import ChatOpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

CONTRACT_YAML = """
agent_id: investment-pipeline-v1
authorities:
  tools:
    allow:
      - scan_market_data
      - fetch_news_summary
      - assess_risk_factors
      - draft_investment_report
      - read_public_filings
    deny:
      - read_restricted_portfolio
      - send_to_external_broker
      - modify_position_limits
  data:
    allow:
      - market_data/public/**
      - news/public/**
      - filings/sec/**
    deny:
      - portfolio/restricted/**
      - personnel/salaries/**

output_constraints:
  deny_patterns:
    - pii_regex
    - credential_regex

sla:
  max_cost_per_run: 2.00
  max_tool_calls_per_run: 20
  max_latency_ms: 120000

trust:
  clean_run_increment: 0.025
  violation_penalty: 0.20
  tier_thresholds:
    standard: { min_score: 0.65, min_clean_runs: 5 }
    trusted: { min_score: 0.82, min_clean_runs: 15 }
"""


class PipelineState(TypedDict):
    ticker: str
    market_data: str
    news_summary: str
    risk_assessment: str
    final_report: str
    error: str | None


def _make_graph() -> Any:
    """Build the LangGraph state machine for the investment pipeline."""
    if not _HAS_LANGGRAPH:
        raise RuntimeError("langgraph not installed. Run: pip install langgraph")

    llm_fast = None
    llm_smart = None
    if _HAS_OPENAI and os.environ.get("OPENAI_API_KEY"):
        try:
            llm_fast = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, max_tokens=500)
            llm_smart = ChatOpenAI(model="gpt-4o", temperature=0.2, max_tokens=1000)
        except Exception:
            pass

    def _call_llm(llm: Any, prompt: str, fallback: str) -> str:
        if llm is None:
            return fallback
        try:
            return llm.invoke(prompt).content
        except Exception as e:
            return f"{fallback}\n(Note: LLM error: {e})"

    def market_scanner(state: PipelineState) -> dict:
        ticker = state.get("ticker", "NVDA")
        result = _call_llm(
            llm_fast,
            f"You are a market data analyst. Provide a brief 3-sentence market overview for {ticker} "
            f"including recent price trend, trading volume, and market cap. Be factual and concise.",
            f"Market data for {ticker}: Price trending upward. Volume is above 30-day average. "
            f"Market cap is in the large-cap range. Sector: Technology."
        )
        return {"market_data": result}

    def news_analyzer(state: PipelineState) -> dict:
        ticker = state.get("ticker", "NVDA")
        result = _call_llm(
            llm_fast,
            f"You are a financial news analyst. Summarize the most relevant recent news for {ticker} "
            f"in 3 bullet points. Focus on earnings, product launches, and regulatory news.",
            f"News for {ticker}:\n"
            f"• Q4 earnings beat analyst consensus by 8% on strong data center revenue\n"
            f"• New GPU architecture announced targeting AI training workloads\n"
            f"• No regulatory concerns noted in recent SEC filings"
        )
        return {"news_summary": result}

    def risk_assessor(state: PipelineState) -> dict:
        ticker = state.get("ticker", "NVDA")
        market = state.get("market_data", "")
        news = state.get("news_summary", "")
        result = _call_llm(
            llm_fast,
            f"You are a risk analyst. Based on this market data:\n{market}\n\nAnd news:\n{news}\n\n"
            f"Assess the top 3 risk factors for {ticker} investment. Format as numbered list.",
            f"Risk factors for {ticker}:\n"
            f"1. Valuation risk: P/E ratio elevated relative to sector median\n"
            f"2. Competitive risk: AMD and Intel accelerating AI chip development\n"
            f"3. Regulatory risk: Export controls may limit international revenue"
        )
        return {"risk_assessment": result}

    def report_writer(state: PipelineState) -> dict:
        ticker = state.get("ticker", "NVDA")
        market = state.get("market_data", "")
        news = state.get("news_summary", "")
        risks = state.get("risk_assessment", "")
        # Uses gpt-4o (higher quality, higher cost) for final report
        result = _call_llm(
            llm_smart,
            f"You are a senior investment analyst. Write a professional investment summary for {ticker}.\n\n"
            f"Market Data:\n{market}\n\nNews:\n{news}\n\nRisks:\n{risks}\n\n"
            f"Write a 3-paragraph investment thesis: (1) opportunity, (2) risks, (3) recommendation. "
            f"This is for institutional use only. Do not include specific price targets.",
            f"Investment Summary: {ticker}\n\n"
            f"Opportunity: {ticker} demonstrates strong momentum in the AI infrastructure buildout cycle. "
            f"Recent earnings confirmation of data center revenue growth supports the bull thesis.\n\n"
            f"Risks: Elevated valuation multiples and increased competition from AMD create headwinds. "
            f"Export control policy uncertainty remains a key watch item.\n\n"
            f"Recommendation: The risk/reward profile favors a hold/accumulate position for long-term "
            f"institutional investors. Position sizing should reflect concentration risk in semiconductor sector."
        )
        return {"final_report": result}

    graph = StateGraph(PipelineState)
    graph.add_node("market_scanner", market_scanner)
    graph.add_node("news_analyzer", news_analyzer)
    graph.add_node("risk_assessor", risk_assessor)
    graph.add_node("report_writer", report_writer)

    graph.set_entry_point("market_scanner")
    graph.add_edge("market_scanner", "news_analyzer")
    graph.add_edge("news_analyzer", "risk_assessor")
    graph.add_edge("risk_assessor", "report_writer")
    graph.add_edge("report_writer", END)

    return graph.compile()


def run_agent(task_input: str | None = None) -> dict:
    """Run the investment pipeline. task_input should be a ticker symbol."""
    ticker = (task_input or "NVDA").strip().upper()
    if not ticker or len(ticker) > 10:
        ticker = "NVDA"

    try:
        graph = _make_graph()
        result = graph.invoke({"ticker": ticker, "market_data": "", "news_summary": "",
                               "risk_assessment": "", "final_report": "", "error": None})
        return {
            "ticker": ticker,
            "market_data": result.get("market_data", ""),
            "news_summary": result.get("news_summary", ""),
            "risk_assessment": result.get("risk_assessment", ""),
            "final_report": result.get("final_report", ""),
            "status": "success",
        }
    except Exception as e:
        # Fallback: return mock pipeline result when LangGraph unavailable
        return {
            "ticker": ticker,
            "market_data": f"Market scan for {ticker}: Strong uptrend on high volume.",
            "news_summary": f"News for {ticker}: Beat earnings estimates, new product launch.",
            "risk_assessment": "Risks: Valuation, competition, regulatory.",
            "final_report": f"Investment thesis for {ticker}: Favorable risk/reward for institutional investors.",
            "status": "success_fallback",
            "note": str(e),
        }


if __name__ == "__main__":
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    result = run_agent(ticker)
    print(f"\n{'='*60}")
    print(f"INVESTMENT RESEARCH: {result['ticker']}")
    print('='*60)
    print(f"\nFinal Report:\n{result['final_report']}")
    print(f"\nStatus: {result['status']}")
