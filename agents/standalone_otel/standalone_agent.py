"""Standalone Terminal Monitoring Agent — demonstrates external agent monitoring.

This agent runs autonomously from the terminal and reports all of its activity
back to the norma dashboard via the HTTP telemetry ingest API.

No need to be registered in norma first — the agent auto-registers on first run.

Usage:
    # Simple terminal run
    python agents/standalone_otel/standalone_agent.py

    # With specific task
    python agents/standalone_otel/standalone_agent.py "Analyze Q4 reports"

    # Against a remote norma instance
    NORMA_API_URL=https://my-norma.example.com python agents/standalone_otel/standalone_agent.py

What this demonstrates:
  - Any agent running anywhere (terminal, cron, Lambda, CI/CD) can report to norma
  - Runs show up in the dashboard with full span detail
  - No code changes needed to the existing agent logic — just add the reporter
"""

from __future__ import annotations

import os
import sys
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_AGENTS_DIR = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _AGENTS_DIR.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

AGENT_ID = "standalone-terminal-v1"
NORMA_API_URL = os.environ.get("NORMA_API_URL", "http://localhost:8080")


class NormaHTTPReporter:
    """Lightweight HTTP reporter that sends spans to the norma ingest endpoint.

    This is the "external monitoring" solution: no SDK import required,
    just HTTP POST to /api/telemetry/ingest.
    """

    def __init__(self, agent_id: str, api_url: str) -> None:
        self.agent_id = agent_id
        self.api_url = api_url
        self.run_id: str = uuid.uuid4().hex
        self.spans: list[dict] = []
        self.start_time = time.time()

    def record_span(
        self,
        name: str,
        span_type: str = "tool_call",
        status: str = "ok",
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost_usd: float | None = None,
        latency_ms: int | None = None,
        model_name: str | None = None,
        input_data: str | None = None,
        output_data: str | None = None,
    ) -> None:
        """Record a span for this run."""
        span: dict[str, Any] = {
            "span_id": uuid.uuid4().hex[:16],
            "span_type": span_type,
            "name": name,
            "status": status,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "input_data": input_data,
            "output_data": output_data,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "model_name": model_name,
        }
        self.spans.append(span)

    def flush(
        self,
        quality_score: float | None = None,
        status: str = "success",
    ) -> dict | None:
        """Send all recorded spans to norma via HTTP ingest."""
        elapsed_ms = int((time.time() - self.start_time) * 1000)
        total_cost = sum(s.get("cost_usd") or 0.0 for s in self.spans)
        total_in = sum(s.get("tokens_in") or 0 for s in self.spans)
        total_out = sum(s.get("tokens_out") or 0 for s in self.spans)

        payload = {
            "agent_id": self.agent_id,
            "framework": "custom",
            "initiated_by": "api",
            "run_status": status,
            "quality_score": quality_score,
            "cost_usd": round(total_cost, 6) if total_cost > 0 else None,
            "latency_ms": elapsed_ms,
            "input_tokens": total_in if total_in > 0 else None,
            "output_tokens": total_out if total_out > 0 else None,
            "spans": self.spans,
        }

        try:
            import urllib.request
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{self.api_url}/api/telemetry/ingest",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                print(f"[norma] Telemetry sent → run_id={result.get('run_id')}, "
                      f"spans={result.get('spans_accepted')}")
                return result
        except Exception as e:
            print(f"[norma] Warning: Could not send telemetry: {e}")
            print(f"[norma] (Dashboard may not be running at {self.api_url})")
            return None


def run_agent(task_input: str | None = None) -> dict:
    """Run the standalone agent with terminal monitoring via HTTP ingest."""
    task = task_input or "Analyze Q4 2025 earnings performance across major tech companies"
    print(f"\n[{AGENT_ID}] Starting task: {task}")
    print(f"[{AGENT_ID}] Reporting to: {NORMA_API_URL}")

    reporter = NormaHTTPReporter(AGENT_ID, NORMA_API_URL)
    result_text = ""

    # Step 1: Data loading
    t0 = time.time()
    print("[Agent] Step 1: Loading market data...")
    time.sleep(0.1)  # simulate work
    data_result = f"Loaded Q4 data for AAPL, MSFT, GOOGL, NVDA. 4 companies, 12 metrics per company."
    reporter.record_span(
        name="load_market_data",
        span_type="tool_call",
        latency_ms=int((time.time() - t0) * 1000),
        input_data=task,
        output_data=data_result,
        status="ok",
    )
    result_text += data_result + "\n"

    # Step 2: Analysis (simulate LLM call)
    t0 = time.time()
    print("[Agent] Step 2: Running analysis...")
    time.sleep(0.15)
    analysis_result = (
        "Q4 2025 Analysis:\n"
        "• NVDA: +142% YoY, data center revenue $18.4B, AI chip demand outpacing supply\n"
        "• MSFT: +16% YoY, Azure cloud +31%, Copilot monetization beginning\n"
        "• AAPL: +4% YoY, iPhone stable, services +12%, Vision Pro contribution minimal\n"
        "• GOOGL: +13% YoY, Search stable, Cloud +35%, YouTube monetization improving"
    )
    reporter.record_span(
        name="analyze_earnings",
        span_type="llm_call",
        model_name="gpt-4o-mini",
        tokens_in=850,
        tokens_out=180,
        cost_usd=0.000236,
        latency_ms=int((time.time() - t0) * 1000),
        input_data=data_result,
        output_data=analysis_result,
        status="ok",
    )
    result_text += analysis_result + "\n"

    # Step 3: Report generation
    t0 = time.time()
    print("[Agent] Step 3: Generating report...")
    time.sleep(0.1)
    report = (
        "Executive Summary: Strong Q4 across all major tech holdings. "
        "AI infrastructure buildout continues to drive outperformance at NVDA and cloud players. "
        "Portfolio weighting toward AI-adjacent positions justified by fundamentals. "
        "No near-term rebalancing recommended."
    )
    reporter.record_span(
        name="generate_report",
        span_type="llm_call",
        model_name="gpt-4o",
        tokens_in=1200,
        tokens_out=95,
        cost_usd=0.00647,
        latency_ms=int((time.time() - t0) * 1000),
        input_data=analysis_result,
        output_data=report,
        status="ok",
    )
    result_text += report

    # Send telemetry
    print("\n[Agent] Sending telemetry to norma dashboard...")
    ingest_result = reporter.flush(quality_score=0.88, status="success")

    return {
        "agent_id": AGENT_ID,
        "task": task,
        "result": result_text,
        "spans_recorded": len(reporter.spans),
        "norma_run_id": ingest_result.get("run_id") if ingest_result else None,
    }


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) or None
    result = run_agent(task)
    print("\n" + "="*60)
    print("RESULT:")
    print("="*60)
    print(result["result"])
    if result.get("norma_run_id"):
        print(f"\n📊 View in dashboard: {NORMA_API_URL.replace('8080', '3000')}/agents/{AGENT_ID}")
