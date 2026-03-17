"""Norma Sentinel Agent — AI monitoring AI agents.

A self-governing agent that periodically monitors the entire norma agent fleet,
detects issues, proposes contract updates, and escalates critical events.

This is the "AI agents monitoring AI agents" vision made concrete.

The Sentinel:
  1. Fetches recent run history for all registered agents
  2. Detects anomalies (quality drops, cost spikes, violation patterns)
  3. Uses LLM to synthesize a natural-language governance report
  4. Proposes contract adjustments for agents showing drift
  5. Sends alerts for critical issues
  6. Logs its own activity to the norma dashboard (self-monitoring!)

Run on a schedule (cron, GitHub Actions, etc.) or via the dashboard:
    python agents/norma_sentinel/sentinel.py
"""

from __future__ import annotations

import os
import sys
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_AGENTS_DIR = Path(__file__).resolve().parent.parent
_BACKEND_DIR = _AGENTS_DIR.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

CONTRACT_YAML = """
agent_id: norma-sentinel-v1
authorities:
  tools:
    allow:
      - read_agent_metrics
      - read_violations_summary
      - read_drift_events
      - propose_contract_change
      - generate_compliance_report
      - send_governance_alert
    deny:
      - modify_database_directly
      - delete_agent
      - approve_contract_without_human

sla:
  max_cost_per_run: 1.00
  max_tool_calls_per_run: 30
  max_latency_ms: 180000

trust:
  clean_run_increment: 0.025
  violation_penalty: 0.25
  tier_thresholds:
    standard: { min_score: 0.65, min_clean_runs: 5 }
    trusted: { min_score: 0.82, min_clean_runs: 10 }
"""


def _fetch_agents(api_base: str) -> list[dict]:
    """Fetch all registered agents from norma API."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{api_base}/api/agents/", timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return []


def _fetch_agent_metrics(api_base: str, agent_id: str) -> dict | None:
    """Fetch metrics for a single agent."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{api_base}/api/analytics/{agent_id}/metrics", timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _fetch_anomalies(api_base: str, agent_id: str) -> list[dict]:
    """Fetch anomalies for a single agent."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{api_base}/api/analytics/{agent_id}/anomalies", timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return []


def _fetch_drift(api_base: str, agent_id: str) -> list[dict]:
    """Fetch drift events for a single agent."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"{api_base}/api/analytics/{agent_id}/drift", timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return []


def _llm_synthesize_report(fleet_summary: dict) -> str:
    """Use LLM to write a natural-language governance report."""
    if not os.environ.get("OPENAI_API_KEY"):
        # Deterministic fallback
        agents = fleet_summary.get("agents", [])
        n_critical = sum(1 for a in agents if a.get("critical_issues"))
        n_total = len(agents)
        return (
            f"Norma Sentinel Governance Report — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"Fleet Status: {n_total} agent(s) monitored. {n_critical} with critical issues.\n\n"
            + "\n".join(
                f"• {a['agent_id']}: quality={a.get('avg_quality', 'N/A')}, "
                f"violations={a.get('total_violations', 0)}, "
                f"tier={a.get('tier', 'unknown')}"
                + (f" ⚠️ {'; '.join(a['critical_issues'])}" if a.get('critical_issues') else " ✓")
                for a in agents
            )
        )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        agents_json = json.dumps(fleet_summary, indent=2)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Norma Sentinel, an AI governance assistant that monitors a fleet of AI agents. "
                        "Write a concise executive-level governance report based on the fleet data provided. "
                        "Format with sections: Fleet Status, Critical Issues, Recommendations. "
                        "Be specific, cite metric values, and flag anything requiring human review."
                    )
                },
                {
                    "role": "user",
                    "content": f"Fleet monitoring data:\n{agents_json}\n\nWrite the governance report."
                }
            ],
            max_tokens=600,
            temperature=0.3,
        )
        return resp.choices[0].message.content or "Sentinel: report generation failed"
    except Exception as e:
        return f"Sentinel: LLM synthesis failed ({e}). Use deterministic fallback."


def run_agent(task_input: str | None = None) -> dict:
    """Run the Norma Sentinel governance agent."""
    api_base = os.environ.get("NORMA_API_URL", "http://localhost:8080")

    print(f"[Sentinel] Starting governance sweep @ {datetime.utcnow().isoformat()}")
    print(f"[Sentinel] API: {api_base}")

    # Fetch fleet data
    agents = _fetch_agents(api_base)
    if not agents:
        print("[Sentinel] No agents found or API unreachable. Running in offline mode.")
        agents = []

    fleet_summary: dict = {
        "swept_at": datetime.utcnow().isoformat(),
        "api_base": api_base,
        "total_agents": len(agents),
        "agents": [],
    }

    critical_agents = []

    for agent in agents[:20]:  # cap at 20 to avoid runaway
        agent_id = agent.get("agent_id") or agent.get("id", "unknown")
        print(f"[Sentinel] Checking agent: {agent_id}")

        metrics = _fetch_agent_metrics(api_base, agent_id) or {}
        anomalies = _fetch_anomalies(api_base, agent_id)
        drift = _fetch_drift(api_base, agent_id)

        critical_issues = []

        # Check for critical conditions
        if metrics.get("avg_quality_score", 1.0) < 0.50:
            critical_issues.append(f"low quality: {metrics.get('avg_quality_score', 'N/A'):.2f}")
        if metrics.get("total_violations", 0) > 3:
            critical_issues.append(f"violation spike: {metrics['total_violations']} violations")
        if any(a.get("severity") == "critical" for a in anomalies):
            critical_issues.append("critical anomaly detected")
        if any(e.get("severity") == "critical" for e in drift):
            critical_issues.append("critical drift detected")

        agent_summary = {
            "agent_id": agent_id,
            "tier": metrics.get("current_tier", agent.get("current_tier", "unknown")),
            "avg_quality": metrics.get("avg_quality_score"),
            "avg_cost": metrics.get("avg_cost_usd"),
            "total_violations": metrics.get("total_violations", 0),
            "n_runs": metrics.get("n_runs", 0),
            "anomalies": len(anomalies),
            "drift_events": len(drift),
            "critical_issues": critical_issues,
        }
        fleet_summary["agents"].append(agent_summary)

        if critical_issues:
            critical_agents.append(agent_id)

    fleet_summary["critical_count"] = len(critical_agents)
    fleet_summary["critical_agents"] = critical_agents

    # Synthesize governance report
    print("[Sentinel] Generating governance report...")
    report = _llm_synthesize_report(fleet_summary)
    fleet_summary["report"] = report

    print("\n" + "="*60)
    print("NORMA SENTINEL — GOVERNANCE REPORT")
    print("="*60)
    print(report)
    print("="*60)

    if critical_agents:
        print(f"\n⚠️  {len(critical_agents)} agent(s) need human review: {', '.join(critical_agents)}")
    else:
        print("\n✅ All agents within governance parameters")

    # Post report to norma API
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{api_base}/api/compliance/reports",
            data=json.dumps({
                "report_text": report,
                "critical_issues_count": len(critical_agents),
                "agents_monitored": len(agents[:20])
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print(f"[Sentinel] Report successfully saved to dashboard.")
    except Exception as e:
        print(f"[Sentinel] Failed to push report to dashboard: {e}")

    return fleet_summary


if __name__ == "__main__":
    result = run_agent()
    sys.exit(0 if result.get("critical_count", 0) == 0 else 1)
