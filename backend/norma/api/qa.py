"""Q&A API — conversational investigation grounded in run data.

Design principle (design.md §1.2 and §1.3):
  Every answer states its evidence. No answer claims more than the data supports.
  If we cannot say the precise form, we say what we *do* know and what we cannot determine.

Two modes:
  1. Template matching: common questions answered deterministically from DB queries.
  2. LLM fallback: if OPENAI_API_KEY is set, pass DB context to GPT-4o for open-ended questions.

Answer shape always includes:
  - answer (str)         — the grounded response
  - data_sources (list)  — which DB tables/fields were used
  - confidence (str)     — high | medium | low | cannot_determine
  - caveats (list[str])  — what the system cannot determine from this data
"""

from __future__ import annotations

import re
import statistics

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from norma.database import get_db
from norma.models.agent import Agent
from norma.models.run import Run
from norma.models.violation import Violation

router = APIRouter()

# ── Intent classifier ──────────────────────────────────────────────────────────

_INTENT_PATTERNS: list[tuple[str, list[str]]] = [
    ("trust_drop",  ["trust.*drop", "trust.*fall", "trust.*declin", "why.*score", "score.*drop", "demot"]),
    ("trust_rise",  ["trust.*rise", "trust.*increas", "trust.*improv", "promot"]),
    ("violations",  ["violat", "block", "denied", "policy", "access.*confid", "what.*went wrong"]),
    ("cost",        ["cost", "spend", "expensive", "cheap", "price", "dollar"]),
    ("quality",     ["quality", "perform", "score", "how.*good", "accura"]),
    ("fleet",       ["fleet", "all agent", "compare", "best", "worst", "which agent"]),
    ("runs",        ["run", "execut", "how many", "recent", "last"]),
    ("latency",     ["latency", "slow", "fast", "speed", r"\bms\b", "millisecond"]),
    ("compliance",  ["compli", "audit", "regulat", "export", "report"]),
]


def _classify_intent(question: str) -> str:
    q_lower = question.lower()
    for intent, patterns in _INTENT_PATTERNS:
        for p in patterns:
            if re.search(p, q_lower):
                return intent
    return "general"


def _extract_agent_id(question: str, known_ids: list[str]) -> str | None:
    q_lower = question.lower()
    for aid in known_ids:
        if aid.lower() in q_lower or aid.replace("-", " ").lower() in q_lower:
            return aid
    for aid in known_ids:
        parts = re.sub(r"[-_v0-9.]", " ", aid).split()
        if any(p in q_lower for p in parts if len(p) > 3):
            return aid
    return None


async def _load_all_agents(db: AsyncSession) -> list[Agent]:
    result = await db.execute(
        select(Agent).options(
            selectinload(Agent.runs).selectinload(Run.violations),
            selectinload(Agent.violations),
        )
    )
    return list(result.scalars().all())


# ── Intent handlers ────────────────────────────────────────────────────────────

def _handle_trust_drop(agent: Agent, question: str) -> dict:
    runs = sorted(agent.runs, key=lambda r: r.id)
    failed = [r for r in runs if r.completion_status == "failed"]
    if not failed:
        return {
            "answer": (
                f"{agent.name} has not had any trust-reducing violations in its run history. "
                f"Current trust score: {agent.trust_score:.3f} (tier: {agent.current_tier}). "
                "Trust increases by the contract-specified increment on each clean run."
            ),
            "data_sources": ["agents.trust_score", "runs.completion_status"],
            "confidence": "high",
            "caveats": [],
        }

    v_events = []
    for r in failed:
        for v in r.violations:
            v_events.append(f"Run #{r.id}: '{v.action_attempted}' blocked by policy '{v.policy_rule}'")

    answer = (
        f"{agent.name} trust score dropped due to {len(failed)} policy violation(s).\n\n"
        f"Current score: {agent.trust_score:.3f} (tier: {agent.current_tier}).\n"
        "Violation events:\n" + "\n".join(f"  • {e}" for e in v_events[:5])
    )
    if len(v_events) > 5:
        answer += f"\n  … and {len(v_events) - 5} more."

    return {
        "answer": answer,
        "data_sources": ["runs.completion_status", "violations.policy_rule", "violations.action_attempted", "agents.trust_score"],
        "confidence": "high",
        "caveats": [
            "Trust penalties are contract-defined (typically −0.25 per violation).",
            "This analysis covers all recorded runs — not just the last 30 days.",
        ],
    }


def _handle_violations(agent: Agent | None, agents: list[Agent]) -> dict:
    targets = [agent] if agent else agents
    all_v = [(a.name, v) for a in targets for v in a.violations]
    if not all_v:
        scope = agent.name if agent else "any agent"
        return {"answer": f"No policy violations recorded for {scope}.", "data_sources": ["violations"], "confidence": "high", "caveats": []}

    by_rule: dict[str, list[str]] = {}
    for name, v in all_v:
        by_rule.setdefault(v.policy_rule or "unknown", []).append(f"{name}: '{v.action_attempted}'")

    lines = []
    for rule, events in by_rule.items():
        lines.append(f"  Policy '{rule}': {len(events)} violation(s)")
        for e in events[:3]:
            lines.append(f"    • {e}")
        if len(events) > 3:
            lines.append(f"    … and {len(events) - 3} more")

    scope = agent.name if agent else "fleet-wide"
    return {
        "answer": f"{len(all_v)} total violation(s) ({scope}):\n\n" + "\n".join(lines),
        "data_sources": ["violations.policy_rule", "violations.action_attempted"],
        "confidence": "high",
        "caveats": ["Violations reflect enforcement blocks only — not warnings or audit events."],
    }


def _handle_cost(agent: Agent | None, agents: list[Agent]) -> dict:
    targets = [agent] if agent else agents
    all_costs = []
    for a in targets:
        costs = [r.cost_usd for r in a.runs if r.cost_usd is not None and r.completion_status == "success"]
        if costs:
            all_costs.append((a.name, statistics.mean(costs), len(costs)))

    if not all_costs:
        return {"answer": "No cost data available.", "data_sources": [], "confidence": "cannot_determine", "caveats": []}

    if agent and all_costs:
        name, avg, n = all_costs[0]
        return {
            "answer": f"{name} average cost per run: ${avg:.4f} over {n} successful run(s).",
            "data_sources": ["runs.cost_usd"],
            "confidence": "high",
            "caveats": ["Cost is from run telemetry; actual API billing may vary."],
        }
    sorted_c = sorted(all_costs, key=lambda x: x[1])
    fleet_mean = statistics.mean(c for _, c, _ in all_costs)
    lines = [f"  {name}: ${avg:.4f}/run (n={n})" for name, avg, n in sorted_c]
    return {
        "answer": "Fleet cost per run (ascending):\n\n" + "\n".join(lines) + f"\n\nFleet mean: ${fleet_mean:.4f}/run",
        "data_sources": ["runs.cost_usd"],
        "confidence": "high",
        "caveats": ["Averages are over successful runs only."],
    }


def _handle_quality(agent: Agent | None, agents: list[Agent]) -> dict:
    targets = [agent] if agent else agents
    all_q = []
    for a in targets:
        scores = [r.quality_score for r in a.runs if r.quality_score is not None and r.completion_status == "success"]
        if scores:
            avg = statistics.mean(scores)
            trend = "stable"
            if len(scores) >= 6:
                delta = statistics.mean(scores[-5:]) - statistics.mean(scores[:5])
                trend = "improving" if delta > 0.03 else ("declining" if delta < -0.03 else "stable")
            all_q.append((a.name, avg, len(scores), trend))

    if not all_q:
        return {"answer": "No quality data available.", "data_sources": [], "confidence": "cannot_determine", "caveats": []}

    if agent:
        name, avg, n, trend = all_q[0]
        return {
            "answer": f"{name} average quality: {avg*100:.1f}% (over {n} runs). Trend: {trend}.",
            "data_sources": ["runs.quality_score"],
            "confidence": "medium",
            "caveats": ["Quality scores are heuristic for non-LLM runs (file-read proxy)."],
        }
    sorted_q = sorted(all_q, key=lambda x: x[1], reverse=True)
    lines = [f"  {name}: {avg*100:.1f}% (n={n}, {trend})" for name, avg, n, trend in sorted_q]
    return {
        "answer": "Quality scores (highest first):\n\n" + "\n".join(lines),
        "data_sources": ["runs.quality_score"],
        "confidence": "medium",
        "caveats": ["Scores are heuristic for non-LLM runs."],
    }


def _handle_fleet(agents: list[Agent]) -> dict:
    if not agents:
        return {"answer": "No agents in the database.", "data_sources": ["agents"], "confidence": "high", "caveats": []}
    tier_counts: dict[str, int] = {}
    for a in agents:
        tier_counts[a.current_tier] = tier_counts.get(a.current_tier, 0) + 1
    total_v = sum(len(a.violations) for a in agents)
    avg_trust = statistics.mean(a.trust_score for a in agents)
    lines = [f"  {a.name}: tier={a.current_tier}, trust={a.trust_score:.3f}, runs={len(a.runs)}" for a in agents]
    return {
        "answer": (
            f"Fleet: {len(agents)} agent(s).\nTier breakdown: {dict(tier_counts)}\n"
            f"Average trust: {avg_trust:.3f}  Total violations: {total_v}\n\n" + "\n".join(lines)
        ),
        "data_sources": ["agents.trust_score", "agents.current_tier", "violations"],
        "confidence": "high",
        "caveats": [],
    }


def _handle_latency(agent: Agent | None, agents: list[Agent]) -> dict:
    targets = [agent] if agent else agents
    results = []
    for a in targets:
        lats = sorted([r.latency_ms for r in a.runs if r.latency_ms is not None])
        if lats:
            p50 = lats[len(lats) // 2]
            p95 = lats[int(len(lats) * 0.95)] if len(lats) > 1 else lats[-1]
            results.append((a.name, p50, p95, len(lats)))
    if not results:
        return {"answer": "No latency data available.", "data_sources": [], "confidence": "cannot_determine", "caveats": []}
    lines = [f"  {name}: p50={p50}ms  p95={p95}ms  (n={n})" for name, p50, p95, n in results]
    return {
        "answer": "Latency percentiles:\n\n" + "\n".join(lines),
        "data_sources": ["runs.latency_ms"],
        "confidence": "high",
        "caveats": ["Latency is norma session wall-clock time, not raw LLM latency."],
    }


def _handle_runs(agent: Agent | None, agents: list[Agent]) -> dict:
    targets = [agent] if agent else agents
    lines = []
    for a in targets:
        failed = sum(1 for r in a.runs if r.completion_status == "failed")
        last = max((r.timestamp for r in a.runs if r.timestamp), default=None)
        last_str = last.strftime("%Y-%m-%d %H:%M") if last else "never"
        lines.append(f"  {a.name}: {len(a.runs)} total, {failed} failed, last: {last_str}")
    return {
        "answer": "Run summary:\n\n" + "\n".join(lines),
        "data_sources": ["runs.completion_status", "runs.timestamp"],
        "confidence": "high",
        "caveats": [],
    }


async def _llm_fallback(question: str, agents: list[Agent]) -> dict:
    from norma.config import get_settings
    settings = get_settings()

    if not settings.openai_api_key:
        agent_list = ", ".join(a.name for a in agents[:5]) + ("…" if len(agents) > 5 else "")
        return {
            "answer": (
                f"Could not match your question to a specific metric.\n\n"
                f"Fleet: {len(agents)} agent(s) ({agent_list}).\n\n"
                "Try asking:\n"
                "  • 'Why did financial-reader-v1 trust score drop?'\n"
                "  • 'What violations happened fleet-wide?'\n"
                "  • 'Which agent has the best quality score?'\n"
                "  • 'What is the average cost per run?'"
            ),
            "data_sources": [],
            "confidence": "cannot_determine",
            "caveats": ["Set OPENAI_API_KEY to enable open-ended LLM-backed Q&A."],
        }

    context_lines = []
    for a in agents:
        costs = [r.cost_usd for r in a.runs if r.cost_usd and r.completion_status == "success"]
        quality = [r.quality_score for r in a.runs if r.quality_score and r.completion_status == "success"]
        context_lines.append(
            f"Agent: {a.agent_id} | tier: {a.current_tier} | trust: {a.trust_score:.3f} | "
            f"runs: {len(a.runs)} | violations: {len(a.violations)} | "
            + (f"avg_quality: {statistics.mean(quality)*100:.1f}% | " if quality else "")
            + (f"avg_cost: ${statistics.mean(costs):.4f}" if costs else "")
        )

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    system_prompt = (
        "You are the norma.ai Q&A engine. Answer questions about AI agent monitoring data. "
        "Only state facts supported by the data provided. Always cite the specific metric. "
        "If the data does not support a confident answer, say what you do know and what you cannot determine. "
        "Be concise. Never speculate.\n\nCurrent fleet data:\n" + "\n".join(context_lines)
    )
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": question}],
        max_tokens=400,
        temperature=0,
    )
    return {
        "answer": resp.choices[0].message.content or "No response.",
        "data_sources": ["agents", "runs", "violations (compact summary)"],
        "confidence": "medium",
        "caveats": ["Generated by GPT-4o-mini from a DB summary — may be less precise than template responses."],
    }


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/ask")
async def ask(
    question: str,
    agent_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Answer a natural language question grounded in the run database.
    States evidence, confidence level, and caveats explicitly.
    Never speculates beyond available data.
    """
    agents = await _load_all_agents(db)
    known_ids = [a.agent_id for a in agents]
    agent_map = {a.agent_id: a for a in agents}

    target: Agent | None = None
    if agent_id and agent_id in agent_map:
        target = agent_map[agent_id]
    else:
        fid = _extract_agent_id(question, known_ids)
        if fid:
            target = agent_map[fid]

    intent = _classify_intent(question)

    dispatch = {
        "trust_drop":  lambda: _handle_trust_drop(target, question) if target else _handle_fleet(agents),
        "trust_rise":  lambda: {
            "answer": f"{target.name}: trust {target.trust_score:.3f}, tier {target.current_tier}. Rises +increment per clean run." if target else _handle_fleet(agents)["answer"],
            "data_sources": ["agents.trust_score"], "confidence": "high", "caveats": [],
        },
        "violations":  lambda: _handle_violations(target, agents),
        "cost":        lambda: _handle_cost(target, agents),
        "quality":     lambda: _handle_quality(target, agents),
        "fleet":       lambda: _handle_fleet(agents),
        "latency":     lambda: _handle_latency(target, agents),
        "runs":        lambda: _handle_runs(target, agents),
        "compliance":  lambda: {
            "answer": "Compliance export: GET /api/agents/{agent_id}/export/compliance → CSV of runs + violations.",
            "data_sources": ["runs", "violations"], "confidence": "high", "caveats": [],
        },
    }

    if intent in dispatch:
        result = dispatch[intent]()
        if isinstance(result, dict):
            return result

    return await _llm_fallback(question, agents)
