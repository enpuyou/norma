"""Agents API — fleet view data from real execution telemetry."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import re
import statistics
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from norma.database import get_db
from norma.core.contract_engine import contract_summary_from_yaml
from norma.core.contract_generator import generate_contract_proposal
from norma.core.enhancement import apply_yaml_snippet, generate_enhancements
from norma.models.agent import Agent
from norma.models.budget import Budget
from norma.models.contract import Contract, ContractVersion
from norma.models.run import Run
from norma.models.span import Span
from norma.models.violation import Violation
from norma.integrations.session_core import AgentPausedError

router = APIRouter()

# ── External agent registry ────────────────────────────────────────────────────
# Agents are resolved via DB Agent.entry_point — no hardcoded registry.
# Any agent onboarded via POST /api/agents/onboard is automatically runnable.
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # norma/


def _resolve_agent_path(agent_id: str, entry_point: str | None) -> Path | None:
    """
    Resolve a runnable agent file path from the DB entry_point field.

    entry_point may be:
      - absolute path (stored by newer onboarding)
      - relative path from project root (stored by older onboarding)
    Returns None if entry_point is missing or file not found.
    """
    if not entry_point:
        return None
    p = Path(entry_point)
    if p.is_absolute():
        return p if p.exists() else None
    # Relative to project root
    abs_p = _PROJECT_ROOT / p
    return abs_p if abs_p.exists() else None


def _load_agent_module(agent_id: str, path: Path) -> ModuleType:
    """Load an external agent module from a filesystem path.

    Uses spec_from_file_location so the agent never needs to be on sys.path.
    Adds project root temporarily so orchestrators can import sibling modules.
    """
    if not path.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Agent file not found on disk: {path}",
        )
    if path.is_dir():
        # Backward compatibility for older onboard records that stored a directory
        # instead of a concrete Python entry file.
        original_dir = path
        candidates = [
            path / "main.py",
            path / "agent.py",
            path / "orchestrator.py",
            path / "pipeline.py",
            path / "__init__.py",
        ]
        path = next((candidate for candidate in candidates if candidate.is_file()), None)  # type: ignore[assignment]
        if path is None:
            dir_py_files = sorted(original_dir.glob("*.py"))
            path = dir_py_files[0] if dir_py_files else None  # type: ignore[assignment]
    if path is None or not path.is_file():
        raise HTTPException(
            status_code=500,
            detail=(
                "Agent entry point is a directory and no runnable Python file "
                f"was found: {path}"
            ),
        )
    import sys as _sys
    project_root_str = str(_PROJECT_ROOT)
    _added = project_root_str not in _sys.path
    if _added:
        _sys.path.insert(0, project_root_str)

    # Prevent PyPI `openai-agents` from shadowing the local `agents/` project folder
    # during module execution (e.g. `from agents.research_team.tools import ...`)
    stale_sdk = {}
    for k in list(_sys.modules.keys()):
        if k == "agents" or k.startswith("agents."):
            m = _sys.modules[k]
            # If the module came from site-packages (the SDK), move it out temporarily
            if m and getattr(m, "__file__", None) and "site-packages" in m.__file__:
                stale_sdk[k] = _sys.modules.pop(k)

    try:
        spec = importlib.util.spec_from_file_location(f"_ext_agent_{agent_id.replace('-', '_')}", path)
        if spec is None or spec.loader is None:
            raise HTTPException(
                status_code=500,
                detail=f"Unable to load module spec for agent '{agent_id}' from '{path}'",
            )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if _added and project_root_str in _sys.path:
            _sys.path.remove(project_root_str)
        # We do NOT automatically restore stale_sdk here.
        # If the local module loaded its own `agents` package, we leave it in sys.modules
        # so subsequent local agent loads succeed. The SDK will just be re-imported
        # by oai-research.py later dynamically if needed.
    return mod


def _discover_tools_from_module(mod: ModuleType) -> list:
    """
    Scan a loaded module's namespace for LangChain BaseTool instances.

    Returns all module-level BaseTool objects in definition order.
    Does NOT require an ALL_TOOLS constant in the module.
    """
    from langchain_core.tools import BaseTool
    return [
        obj
        for name, obj in vars(mod).items()
        if not name.startswith("_") and isinstance(obj, BaseTool)
    ]


def _module_task_hints(mod: ModuleType) -> list[dict]:
    """Return optional module task hints in a normalized safe shape.

    Supported module attributes:
      - TASK_HINTS
      - SCRIPTED_TASKS

    Each hint may include: description, tool, arg, expected_quality.
    Invalid entries are ignored.
    """
    raw = getattr(mod, "TASK_HINTS", None)
    if raw is None:
        raw = getattr(mod, "SCRIPTED_TASKS", None)
    if not isinstance(raw, list):
        return []

    normalized: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool_name = item.get("tool")
        if not isinstance(tool_name, str) or not tool_name:
            continue
        normalized.append(
            {
                "description": str(item.get("description") or f"Run tool: {tool_name}"),
                "tool": tool_name,
                "arg": item.get("arg"),
                "expected_quality": item.get("expected_quality", 1.0),
            }
        )
    return normalized


def _workflow_stage_names_from_file(path: Path | None) -> list[str]:
    """Infer workflow stage names from LangGraph add_node() declarations."""
    if path is None or not path.exists():
        return []
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    matches = re.findall(r"\.add_node\(\s*[\"']([^\"']+)[\"']\s*,", source)
    ordered_unique: list[str] = []
    seen: set[str] = set()
    for name in matches:
        if name not in seen:
            seen.add(name)
            ordered_unique.append(name)
    return ordered_unique


def _build_virtual_sub_agents(parent: Agent, entry_path: Path | None) -> list[dict]:
    """Build virtual sub-agent records from workflow stages when DB rows don't exist."""
    stage_names = _workflow_stage_names_from_file(entry_path)
    if not stage_names:
        return []
    return [
        {
            "agent_id": f"{parent.agent_id}:{stage}",
            "name": stage.replace("_", " ").title(),
            "trust_score": round(parent.trust_score, 4),
            "current_tier": parent.current_tier,
            "type": "subagent",
            "virtual": True,
        }
        for stage in stage_names
    ]


def _preview_jsonish(value: object, limit: int = 180) -> str | None:
    """Return a short string preview for span input/output payload fields."""
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            raw = json.dumps(parsed, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
    else:
        try:
            raw = json.dumps(value, ensure_ascii=False)
        except TypeError:
            raw = str(value)
    return raw if len(raw) <= limit else f"{raw[:limit]}…"


def _parse_jsonish_object(value: object) -> dict:
    """Best-effort JSON object parser for DB text fields."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _heuristic_phase_for_span(span: Span) -> tuple[str, str, str, str]:
    """Infer workflow phase for a span using deterministic keywords.

    Returns: (phase_id, phase_name, reason, confidence)
    """
    stype = str(getattr(span, "span_type", "") or "").lower()
    name = str(getattr(span, "name", "") or "").lower()
    io_blob = " ".join(
        [
            _preview_jsonish(getattr(span, "input_data", None), limit=120) or "",
            _preview_jsonish(getattr(span, "output_data", None), limit=120) or "",
        ]
    ).lower()
    combined = f"{stype} {name} {io_blob}"

    def _hit(words: tuple[str, ...]) -> bool:
        return any(w in combined for w in words)

    if stype in {"enforcement_check", "guardrail"} or _hit(("verify", "validate", "policy", "guard", "compliance", "audit", "check")):
        return ("verification", "Verification", "policy/validation keywords", "high")
    if _hit(("ingest", "load", "read", "fetch", "search", "query", "list", "retrieve", "scan")):
        return ("ingestion", "Ingestion", "data retrieval keywords", "high")
    if _hit(("analy", "classif", "score", "rank", "summar", "synth", "reason", "assess", "plan")):
        return ("analysis", "Analysis", "analysis keywords", "medium")
    if _hit(("write", "format", "report", "answer", "respond", "final", "deliver", "present")):
        return ("output", "Output", "output/response keywords", "medium")

    return ("processing", "Processing", "default fallback", "low")


async def _llm_phase_groups_for_spans(spans: list[Span]) -> dict | None:
    """Use LLM to infer phase groupings over execution spans.

    Returns a dict with keys:
      - phase_by_span: dict[str, dict]
      - phase_groups: list[dict]
      - source: str
    or None when unavailable.
    """
    if not spans:
        return None

    try:
        from norma.config import get_settings as _get_settings
        settings = _get_settings()
        if not settings.openai_api_key:
            return None

        from openai import AsyncOpenAI

        compact = []
        for s in spans[:120]:
            compact.append(
                {
                    "span_id": s.span_id,
                    "span_type": s.span_type,
                    "name": s.name,
                    "input": _preview_jsonish(s.input_data, limit=90),
                    "output": _preview_jsonish(s.output_data, limit=90),
                }
            )

        prompt = {
            "task": "Group execution spans into high-level workflow phases",
            "instructions": [
                "Use concise phase names like Ingestion, Verification, Analysis, Output, Orchestration.",
                "Return JSON only.",
                "Prefer 2-6 phases.",
                "Every span_id must appear in exactly one phase.",
            ],
            "spans": compact,
            "response_schema": {
                "phase_groups": [
                    {
                        "phase_id": "string-kebab-case",
                        "phase_name": "string",
                        "description": "string",
                        "confidence": "high|medium|low",
                        "span_ids": ["span_id"],
                    }
                ]
            },
        }

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=900,
            messages=[
                {"role": "system", "content": "You are a strict JSON generator for workflow phase labeling."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            return None

        # Be resilient to markdown code fences
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

        doc = json.loads(content)
        groups = doc.get("phase_groups") if isinstance(doc, dict) else None
        if not isinstance(groups, list) or not groups:
            return None

        phase_by_span: dict[str, dict] = {}
        normalized_groups: list[dict] = []
        for g in groups:
            if not isinstance(g, dict):
                continue
            pid = str(g.get("phase_id") or "phase").strip() or "phase"
            pname = str(g.get("phase_name") or pid.replace("-", " ").title()).strip()
            pdesc = str(g.get("description") or "").strip()
            pconf = str(g.get("confidence") or "medium").lower()
            if pconf not in {"high", "medium", "low"}:
                pconf = "medium"
            span_ids = g.get("span_ids") if isinstance(g.get("span_ids"), list) else []
            clean_ids = [str(sid) for sid in span_ids if isinstance(sid, (str, int))]
            if not clean_ids:
                continue
            normalized_groups.append(
                {
                    "phase_id": pid,
                    "phase_name": pname,
                    "description": pdesc,
                    "confidence": pconf,
                    "span_ids": clean_ids,
                }
            )
            for sid in clean_ids:
                phase_by_span[sid] = {
                    "phase_id": pid,
                    "phase_name": pname,
                    "description": pdesc,
                    "confidence": pconf,
                }

        if not normalized_groups:
            return None

        return {
            "phase_by_span": phase_by_span,
            "phase_groups": normalized_groups,
            "source": "llm",
        }
    except Exception:
        return None


def _heuristic_phase_groups_for_spans(spans: list[Span]) -> dict:
    """Deterministic phase grouping fallback for execution spans."""
    phase_by_span: dict[str, dict] = {}
    grouped: dict[str, dict] = {}

    for s in spans:
        pid, pname, reason, conf = _heuristic_phase_for_span(s)
        if pid not in grouped:
            grouped[pid] = {
                "phase_id": pid,
                "phase_name": pname,
                "description": reason,
                "confidence": conf,
                "span_ids": [],
            }
        grouped[pid]["span_ids"].append(s.span_id)
        phase_by_span[s.span_id] = {
            "phase_id": pid,
            "phase_name": pname,
            "description": reason,
            "confidence": conf,
        }

    return {
        "phase_by_span": phase_by_span,
        "phase_groups": list(grouped.values()),
        "source": "heuristic",
    }


def _default_llm_input(agent_id: str, contract_yaml: str, tools: list) -> str:
    """Infer a useful non-placeholder default input for mode=llm runs.

    We avoid generic text like "Perform your primary task." because some tools
    (e.g. topic search) treat it as a literal query and return empty results.
    """
    import yaml as _yaml_rt

    tool_names = [getattr(t, "name", "") for t in tools]
    contract_doc = _yaml_rt.safe_load(contract_yaml) or {}
    scope = contract_doc.get("scope", {})
    if isinstance(scope, dict):
        scope_desc = str(scope.get("description", "")).strip()
    elif isinstance(scope, str):
        scope_desc = scope.strip()
    else:
        scope_desc = ""

    joined = " ".join(tool_names).lower()
    if "research" in joined or "topic" in joined or "search" in joined:
        return "Analyze semiconductor supply chain trends in Q4 2025 and provide a concise summary."
    if "earnings" in joined or "report" in joined:
        return "Summarize Q4 2025 earnings highlights and key risks from available reports."
    if "support" in joined or "ticket" in joined:
        return "Triage a billing ticket and suggest the best resolution using the knowledge base."

    if scope_desc:
        return f"Execute a task within this scope: {scope_desc}"
    return f"Run a representative task for agent '{agent_id}' and provide a concise result."


def _infer_tool_default_arg(
    tool: object,
    *,
    agent_id: str,
    contract_yaml: str,
    task_hints: dict[str, dict],
    all_tools: list,
) -> object | None:
    """Infer a safe default argument for tools that require input.

    Prefers TASK_HINTS/SCRIPTED_TASKS args when available, then falls back to
    schema-driven inference based on common argument names.
    """
    tool_name = str(getattr(tool, "name", ""))
    hint = task_hints.get(tool_name, {})
    if "arg" in hint and hint.get("arg") is not None:
        return hint["arg"]

    schema = getattr(tool, "args", None)
    if not isinstance(schema, dict):
        return None

    required = schema.get("required") or []
    properties = schema.get("properties") or {}
    if not isinstance(required, list):
        required = []
    if not isinstance(properties, dict):
        properties = {}

    if not required:
        return None

    def _value_for(field_name: str) -> object:
        fname = str(field_name).lower()
        fmeta = properties.get(field_name, {}) if isinstance(properties, dict) else {}
        fdesc = str((fmeta or {}).get("description", "")).lower() if isinstance(fmeta, dict) else ""
        combined = f"{fname} {fdesc}"

        if any(k in combined for k in ("topic", "query", "keyword", "search")):
            return "semiconductor"
        if any(k in combined for k in ("filename", "file", "document", "doc", "report")):
            if "research" in tool_name:
                return "semiconductor_q4_2025"
            if "earnings" in tool_name or "financial" in tool_name:
                return "q4_2025_earnings"
            if "support" in tool_name or "kb" in tool_name:
                return "kb_billing"
            return "sample"
        if "path" in combined:
            return "public/sample.txt"
        if any(k in combined for k in ("text", "content", "input", "prompt", "message")):
            return _default_llm_input(agent_id, contract_yaml, all_tools)
        if any(k in combined for k in ("id", "run")):
            return "1"
        return "sample"

    if len(required) == 1:
        return _value_for(str(required[0]))

    return {str(field): _value_for(str(field)) for field in required}


def _arg_from_validation_error(
    error: Exception,
    *,
    tool_name: str,
    agent_id: str,
    contract_yaml: str,
    all_tools: list,
) -> object | None:
    """Build a best-effort argument payload from a missing-field validation error."""
    text = str(error)
    missing_fields = re.findall(r"\n\s*([a-zA-Z_][a-zA-Z0-9_]*)\n\s+Field required", text)
    if not missing_fields:
        return None

    def _fallback_value(field: str) -> object:
        f = field.lower()
        if any(k in f for k in ("topic", "query", "keyword", "search")):
            return "semiconductor"
        if any(k in f for k in ("filename", "file", "document", "doc", "report")):
            return "q4_2025_earnings"
        if "path" in f:
            return "public/sample.txt"
        if any(k in f for k in ("text", "content", "input", "prompt", "message")):
            return _default_llm_input(agent_id, contract_yaml, all_tools)
        return "sample"

    if len(missing_fields) == 1:
        return _fallback_value(missing_fields[0])
    return {field: _fallback_value(field) for field in missing_fields}


def _resolve_llm_runner(mod: ModuleType) -> tuple[str, object, str] | None:
    """Resolve a runnable LLM entrypoint from a module without hardcoding IDs."""
    for name in ("build_llm_agent", "build_langgraph_agent", "build_agent"):
        candidate = getattr(mod, name, None)
        if callable(candidate):
            return ("builder", candidate, name)

    # Generic builder fallback for module-defined builders such as
    # build_agents_sdk_agent(), build_openai_agent(), etc.
    for name in sorted(dir(mod)):
        if not name.startswith("build_"):
            continue
        candidate = getattr(mod, name, None)
        if not callable(candidate):
            continue
        if getattr(candidate, "__module__", None) != mod.__name__:
            continue
        return ("builder", candidate, name)

    for name in ("run_agent", "run", "execute", "main"):
        candidate = getattr(mod, name, None)
        if callable(candidate):
            return ("callable", candidate, name)

    for name in ("graph", "agent", "workflow", "pipeline", "app"):
        candidate = getattr(mod, name, None)
        if candidate is None:
            continue
        if callable(getattr(candidate, "invoke", None)):
            return ("invoke_obj", candidate, name)
        if callable(getattr(candidate, "run", None)):
            return ("run_obj", candidate, name)

    return None


def _load_contract_from_db_sync(agent_id: str, db_url: str) -> str | None:
    """
    Load contract YAML for an agent from the DB synchronously.

    Prefers the human-approved active contract; falls back to the latest
    pending contract (generated during onboarding, awaiting review).
    Returns None if no contract exists for this agent.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _SyncSession
    from norma.models.contract import Contract as _Contract

    engine = create_engine(db_url, echo=False)
    with _SyncSession(engine) as s:
        contract = (
            s.query(_Contract)
            .filter(_Contract.agent_id == agent_id, _Contract.is_active == True)  # noqa: E712
            .order_by(_Contract.id.desc())
            .first()
        )
        if not contract:
            contract = (
                s.query(_Contract)
                .filter(_Contract.agent_id == agent_id)
                .order_by(_Contract.id.desc())
                .first()
            )
        return contract.yaml_content if contract else None


def _pending_action_for(agent: Agent, runs: list, violations: list) -> dict | None:
    """Compute the highest-priority pending action from the recommendations logic."""
    successful = [r for r in runs if r.completion_status == "success"]
    quality_scores = [r.quality_score for r in successful if r.quality_score is not None]
    avg_quality = statistics.mean(quality_scores) if quality_scores else 0.0

    if (
        agent.current_tier == "restricted"
        and len(successful) >= 5
        and agent.trust_score >= 0.60
        and avg_quality >= 0.80
        and len(violations) == 0
    ):
        return {
            "type": "tier_promotion",
            "message": f"Eligible for standard tier — {len(successful)} clean runs, trust {agent.trust_score:.2f}",
            "cta": "Review & approve contract",
        }

    if (
        agent.current_tier == "standard"
        and len(successful) >= 10
        and agent.trust_score >= 0.80
        and avg_quality >= 0.85
        and len(violations) == 0
    ):
        return {
            "type": "tier_promotion",
            "message": f"Eligible for trusted tier — {len(successful)} clean runs, trust {agent.trust_score:.2f}",
            "cta": "Promote to trusted",
        }

    recent_violations = [r for r in runs[-10:] if r.completion_status == "failed"]
    unresolved_recent = [
        r for r in recent_violations
        if any(not (v.scope or "").startswith("review:") for v in (r.violations or []))
    ]
    if unresolved_recent:
        focus_run = unresolved_recent[-1].id
        return {
            "type": "review_reinstate",
            "message": f"{len(unresolved_recent)} violation(s) in last {min(10, len(runs))} runs — review required",
            "cta": "Review enforcement log",
            "cta_primary": "Review enforcement log",
            "cta_secondary": "View contracts",
            "context": f"Run #{focus_run}",
        }

    return None


def _build_agent_payload(agent: Agent) -> dict:
    runs = sorted(agent.runs, key=lambda r: r.id)
    successful_runs = [r for r in runs if r.completion_status == "success"]
    n_runs = len(runs)

    # --- quality / cost ---
    quality_scores = [r.quality_score for r in successful_runs if r.quality_score is not None]
    avg_quality = statistics.mean(quality_scores) if quality_scores else 0.0

    cost_values = [r.cost_usd for r in successful_runs if r.cost_usd is not None]
    avg_cost = statistics.mean(cost_values) if cost_values else 0.0

    completion_rate = len(successful_runs) / n_runs if n_runs else 0.0
    quality_adj_cost = avg_cost / avg_quality if avg_quality > 0 else 0.0

    # --- latency ---
    latencies = sorted([r.latency_ms for r in runs if r.latency_ms is not None])
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

    # --- token avg ---
    token_totals = [
        (r.input_tokens or 0) + (r.output_tokens or 0)
        for r in runs
    ]
    avg_tokens = int(statistics.mean(token_totals)) if token_totals else 0

    # --- trust history ---
    trust_history = []
    for i, run in enumerate(runs):
        point: dict = {"run": i + 1, "score": run.trust_score_after or agent.trust_score}
        if run.completion_status == "failed" and run.violations:
            point["event"] = "violation"
        trust_history.append(point)

    # --- trend: compare first 5 vs last 5 quality ---
    trend = "stable"
    if len(quality_scores) >= 6:
        first5 = statistics.mean(quality_scores[:5])
        last5 = statistics.mean(quality_scores[-5:])
        delta = last5 - first5
        if delta > 0.03:
            trend = "up"
        elif delta < -0.03:
            trend = "down"

    # --- active contract ---
    active_contracts = [c for c in agent.contracts if c.is_active]
    contract = active_contracts[0] if active_contracts else None

    # --- violations in last 30 days ---
    violations_30d = sum(1 for v in agent.violations)

    last_run = runs[-1] if runs else None

    return {
        "id": agent.agent_id,
        "name": agent.name,
        "description": f"{agent.name} — {agent.type} agent, {agent.department} department",
        "tier": agent.current_tier,
        "trust_score": round(agent.trust_score, 4),
        "trust_history": trust_history,
        "quality_score": round(avg_quality, 4),
        "cost_per_task": round(avg_cost, 5),
        "completion_rate": round(completion_rate, 4),
        "quality_adj_cost": round(quality_adj_cost, 5),
        "trend": trend,
        "contract_version": contract.version if contract else "—",
        "contract_deployed": contract.activated_at.isoformat() if contract and contract.activated_at else "",
        "approved_by": contract.approved_by if contract else "—",
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "avg_tokens": avg_tokens,
        "violations_30d": violations_30d,
        "pending_action": _pending_action_for(agent, runs, agent.violations),
        "last_run_at": last_run.timestamp.isoformat() if last_run else "",
        "enabled": agent.enabled,
        # Phase 4: registry versioning
        "entry_point": agent.entry_point,
        "directory": agent.directory,
        "file_hash": agent.file_hash,
        "agent_code_version": agent.agent_code_version,
        "code_status": agent.code_status,
        "last_seen_at": agent.last_seen_at.isoformat() if agent.last_seen_at else None,
        # Phase 6: multi-agent type
        "type": agent.agent_type or "standard",
        "parent_agent_id": agent.parent_agent_id,
        # Phase 2: multi-framework
        "framework": agent.framework,
    }


@router.get("/")
async def list_agents(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Return all agents with current tier, trust score, and aggregated metrics."""
    result = await db.execute(
        select(Agent)
        .options(
            selectinload(Agent.runs).selectinload(Run.violations),
            selectinload(Agent.contracts),
            selectinload(Agent.violations),
        )
        .order_by(Agent.agent_id)
    )
    agents = result.scalars().all()

    rows: list[dict] = []
    for a in agents:
        payload = _build_agent_payload(a)
        sub_agents_result = await db.execute(select(Agent).where(Agent.parent_agent_id == a.agent_id))
        db_sub_agents = sub_agents_result.scalars().all()
        payload["sub_agents"] = [
            {
                "agent_id": sa.agent_id,
                "name": sa.name,
                "trust_score": round(sa.trust_score, 4),
                "current_tier": sa.current_tier,
                "type": sa.agent_type or "standard",
                "virtual": False,
            }
            for sa in db_sub_agents
        ]

        if payload.get("type") == "orchestrator" and not payload["sub_agents"]:
            payload["sub_agents"] = _build_virtual_sub_agents(
                a,
                _resolve_agent_path(a.agent_id, a.entry_point),
            )
        rows.append(payload)
    return rows


@router.post("/bulk/pause")
async def bulk_set_agent_enabled(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pause or resume a fleet subset (or all agents when no IDs provided)."""
    enabled = bool(body.get("enabled", False))
    agent_ids = body.get("agent_ids") or []

    stmt = select(Agent)
    if agent_ids:
        stmt = stmt.where(Agent.agent_id.in_(agent_ids))

    result = await db.execute(stmt)
    agents = result.scalars().all()
    if not agents:
        raise HTTPException(status_code=404, detail="No agents found for bulk update")

    updated: list[str] = []
    for agent in agents:
        agent.enabled = enabled
        updated.append(agent.agent_id)

    await db.commit()
    return {
        "updated": len(updated),
        "enabled": enabled,
        "agent_ids": sorted(updated),
    }


@router.post("/bulk/check-changes")
async def bulk_check_agent_changes(
    body: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run change detection for multiple agents and return per-agent results."""
    from norma.agents.introspect import _compute_file_hash

    requested_ids = body.get("agent_ids") or []

    stmt = select(Agent)
    if requested_ids:
        stmt = stmt.where(Agent.agent_id.in_(requested_ids))

    result = await db.execute(stmt)
    agents = result.scalars().all()
    if not agents:
        raise HTTPException(status_code=404, detail="No agents found for bulk scan")

    now = datetime.now(timezone.utc)
    results: list[dict] = []

    for agent in agents:
        try:
            # Resolve agent file from DB entry_point (DB-driven, no hardcoded registry)
            agent_path = _resolve_agent_path(agent.agent_id, agent.entry_point)
            if agent_path is None:
                results.append({
                    "agent_id": agent.agent_id,
                    "status": "missing",
                    "error": "No registered entry_point in DB",
                })
                continue

            agent_dir = agent_path.parent
            py_files = sorted(agent_dir.glob("*.py")) if agent_dir.exists() else []
            if not py_files:
                agent.code_status = "missing"
                agent.last_seen_at = now
                results.append({
                    "agent_id": agent.agent_id,
                    "status": "missing",
                    "files_checked": [],
                    "changed": False,
                })
                continue

            current_hash = _compute_file_hash(py_files)
            prev_hash = agent.file_hash
            changed = prev_hash is not None and current_hash != prev_hash

            if changed:
                agent.agent_code_version += 1
                agent.code_status = "changed"
            elif prev_hash is None:
                agent.code_status = "ok"
            else:
                agent.code_status = "ok"

            agent.file_hash = current_hash
            agent.entry_point = str(agent_path)
            agent.directory = str(agent_dir)
            agent.last_seen_at = now

            results.append({
                "agent_id": agent.agent_id,
                "status": agent.code_status,
                "prev_hash": prev_hash,
                "current_hash": current_hash,
                "changed": changed,
                "agent_code_version": agent.agent_code_version,
                "files_checked": [f.name for f in py_files],
                "last_seen_at": now.isoformat(),
            })
        except Exception as exc:
            results.append({
                "agent_id": agent.agent_id,
                "status": "missing",
                "error": str(exc),
            })

    await db.commit()
    changed_count = sum(1 for r in results if r.get("changed") is True)
    return {
        "scanned": len(results),
        "changed": changed_count,
        "results": results,
    }


@router.get("/bulk/export")
async def export_fleet_summary_csv(db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    """Export a fleet-level summary CSV for dashboard bulk export actions."""
    result = await db.execute(
        select(Agent)
        .options(
            selectinload(Agent.runs).selectinload(Run.violations),
            selectinload(Agent.contracts),
            selectinload(Agent.violations),
        )
        .order_by(Agent.agent_id)
    )
    agents = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "agent_id",
        "name",
        "tier",
        "trust_score",
        "enabled",
        "framework",
        "run_count",
        "avg_quality_score",
        "avg_cost_usd",
        "violations_30d",
        "last_run_at",
    ])

    for agent in agents:
        payload = _build_agent_payload(agent)
        writer.writerow([
            payload["id"],
            payload["name"],
            payload["tier"],
            payload["trust_score"],
            payload["enabled"],
            payload.get("framework") or "",
            len(agent.runs),
            payload["quality_score"],
            payload["cost_per_task"],
            payload["violations_30d"],
            payload.get("last_run_at") or "",
        ])

    buf.seek(0)
    filename = f"norma_fleet_summary_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/scan")
async def scan_agent_directory(directory: str = Query(..., description="Absolute path to a Python agent directory")) -> dict:
    """Scan a Python directory for agent tools WITHOUT registering anything.

    Returns discovered tools, data path hints, and a contract preview so the
    UI can show what norma found before the user commits to onboarding.
    """
    from norma.agents.introspect import introspect_directory

    try:
        info = introspect_directory(directory)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    tool_names = info["tool_names"]
    data_hints = info["data_path_hints"]
    contract_preview = {
        "tools_allow": tool_names[:8],
        "tools_deny": [],
        "data_allow": [h for h in data_hints if "public" in h or "data" in h][:4],
        "data_deny": [h for h in data_hints if "confidential" in h or "secret" in h or "payment" in h][:4],
    }

    return {
        "directory": directory,
        "files_scanned": info["files_scanned"],
        "tools": info["tools"],
        "tool_names": tool_names,
        "data_path_hints": data_hints,
        "contract_preview": contract_preview,
        "errors": info["errors"],
        "agents": info.get("agents", []),
        "file_hash": info.get("file_hash", ""),
    }


# ─── Quality Rubric ────────────────────────────────────────────────────────────
# Must be defined BEFORE /{agent_id} routes to avoid route shadowing.

@router.get("/quality-rubric")
async def get_quality_rubric() -> dict:
    """Return the current LLM-as-judge quality rubric prompt."""
    from norma.core import quality_scorer
    return {"rubric": quality_scorer._QUALITY_RUBRIC}


@router.put("/quality-rubric")
async def update_quality_rubric(body: dict = Body(...)) -> dict:
    """Replace the LLM-as-judge quality rubric prompt for this session."""
    new_rubric = body.get("rubric", "")
    if not new_rubric or not new_rubric.strip():
        raise HTTPException(status_code=422, detail="rubric must be a non-empty string")
    from norma.core import quality_scorer
    quality_scorer._QUALITY_RUBRIC = new_rubric
    return {"rubric": quality_scorer._QUALITY_RUBRIC, "updated": True}


@router.get("/{agent_id}")
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Return full agent detail for Engineer mode."""
    result = await db.execute(
        select(Agent)
        .where(Agent.agent_id == agent_id)
        .options(
            selectinload(Agent.runs).selectinload(Run.violations),
            selectinload(Agent.contracts),
            selectinload(Agent.violations),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    payload = _build_agent_payload(agent)

    # Attach sub-agents list if this is an orchestrator
    sub_agents_result = await db.execute(
        select(Agent).where(Agent.parent_agent_id == agent_id)
    )
    sub_agents = sub_agents_result.scalars().all()
    payload["sub_agents"] = [
        {
            "agent_id": sa.agent_id,
            "name": sa.name,
            "trust_score": round(sa.trust_score, 4),
            "current_tier": sa.current_tier,
            "type": sa.agent_type or "standard",
            "virtual": False,
        }
        for sa in sub_agents
    ]

    if (
        payload.get("type") == "orchestrator"
        and not payload["sub_agents"]
    ):
        payload["sub_agents"] = _build_virtual_sub_agents(
            agent,
            _resolve_agent_path(agent_id, agent.entry_point),
        )

    return payload


@router.get("/{agent_id}/metrics/trends")
async def get_agent_metric_trends(
    agent_id: str,
    days: int = Query(30, ge=1, le=365),
    granularity: str = Query("auto", pattern="^(auto|hour|day|run)$"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return time-series trends for quality, cost, tokens, and context utilization."""
    agent_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Use naive UTC to match SQLite's naive CURRENT_TIMESTAMP values
    now = datetime.utcnow()
    if granularity == "run":
        resolved_granularity = "run"
    elif granularity == "auto" and days > 3:
        resolved_granularity = "day"
    elif granularity in {"auto", "hour"}:
        resolved_granularity = "hour"
    else:
        resolved_granularity = "day"

    if resolved_granularity == "hour":
        cutoff = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
    else:
        cutoff = (now - timedelta(days=days)).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

    run_result = await db.execute(
        select(Run)
        .where(
            Run.agent_id == agent_id,
            Run.timestamp >= cutoff,
            Run.parent_run_id.is_(None),  # top-level runs only, not orchestrator sub-runs
        )
        .order_by(Run.timestamp.asc())
    )
    runs = run_result.scalars().all()

    span_result = await db.execute(
        select(Span)
        .join(Run, Span.trace_id == Run.id)
        .where(Run.agent_id == agent_id, Run.timestamp >= cutoff, Run.parent_run_id.is_(None), Span.span_type == "llm_call")
        .order_by(Span.id.asc())
    )
    llm_spans = span_result.scalars().all()

    def _as_utc(ts: datetime) -> datetime:
        """Treat naive datetimes from SQLite as UTC (SQLite CURRENT_TIMESTAMP is UTC)."""
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)

    def _bucket_start(ts: datetime | None) -> datetime | None:
        if ts is None:
            return None
        utc_ts = _as_utc(ts)
        if resolved_granularity == "hour":
            return utc_ts.replace(minute=0, second=0, microsecond=0)
        return utc_ts.replace(hour=0, minute=0, second=0, microsecond=0)

    by_bucket: dict[str, dict] = {}

    for run in runs:
        if resolved_granularity == "run":
            run_ts = _as_utc(run.timestamp) if run.timestamp else None
            if run_ts is None:
                continue
            bucket_key = f"run:{run.id}"
            bucket_ts = run_ts
        else:
            bucket_ts = _bucket_start(run.timestamp)
            if bucket_ts is None:
                continue
            bucket_key = bucket_ts.isoformat().replace("+00:00", "Z")
        bucket = by_bucket.setdefault(
            bucket_key,
            {
                "run_count": 0,
                "_sort_ts": bucket_ts,
                "quality_scores": [],
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "latencies": [],
                "trust_end": run.trust_score_after,
                "bucket_start": bucket_ts,
                "_run_id": run.id if resolved_granularity == "run" else None,
            },
        )
        bucket["run_count"] += 1
        if run.quality_score is not None:
            bucket["quality_scores"].append(run.quality_score)
        bucket["cost_usd"] += float(run.cost_usd or 0.0)
        bucket["input_tokens"] += int(run.input_tokens or 0)
        bucket["output_tokens"] += int(run.output_tokens or 0)
        if run.latency_ms is not None:
            bucket["latencies"].append(float(run.latency_ms))
        if run.trust_score_after is not None:
            bucket["trust_end"] = run.trust_score_after

    context_by_bucket: dict[str, list[float]] = {}
    for span in llm_spans:
        if resolved_granularity == "run":
            bucket_key = f"run:{span.trace_id}"
        else:
            bucket_ts = _bucket_start(span.timestamp)
            if bucket_ts is None:
                continue
            bucket_key = bucket_ts.isoformat().replace("+00:00", "Z")
        attrs = span.attributes
        ratio = None
        if attrs:
            try:
                import json as _json

                parsed = _json.loads(attrs) if isinstance(attrs, str) else attrs
                val = parsed.get("context_utilization_ratio") if isinstance(parsed, dict) else None
                if isinstance(val, (float, int)):
                    ratio = float(val)
            except Exception:
                ratio = None
        if ratio is not None:
            context_by_bucket.setdefault(bucket_key, []).append(ratio)

    # Sort by actual timestamp (run granularity keys are "run:N" so sort by _sort_ts)
    sorted_bucket_keys = sorted(
        by_bucket.keys(),
        key=lambda k: by_bucket[k].get("_sort_ts") or by_bucket[k]["bucket_start"],
    )

    points = []
    for bucket_key in sorted_bucket_keys:
        bucket = by_bucket[bucket_key]
        bucket_start = bucket["bucket_start"]
        quality_scores = bucket["quality_scores"]
        latencies = bucket["latencies"]
        ratios = context_by_bucket.get(bucket_key, [])
        if resolved_granularity == "run":
            bucket_label = bucket_start.strftime("%m-%d %H:%M")
        elif resolved_granularity == "hour":
            bucket_label = bucket_start.strftime("%m-%d %H:00")
        else:
            bucket_label = bucket_start.strftime("%m-%d")
        # Always emit bucket_start as an ISO timestamp string so the frontend
        # can call new Date(pt.bucket_start) regardless of granularity.
        bucket_start_iso = bucket_start.isoformat().replace("+00:00", "Z")
        points.append(
            {
                "date": bucket_start.date().isoformat(),
                "bucket_start": bucket_start_iso,
                "bucket_label": bucket_label,
                "run_count": bucket["run_count"],
                "avg_quality": round(sum(quality_scores) / len(quality_scores), 4)
                if quality_scores
                else None,
                "total_cost_usd": round(bucket["cost_usd"], 8),
                "input_tokens": bucket["input_tokens"],
                "output_tokens": bucket["output_tokens"],
                "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
                "avg_context_utilization_ratio": round(sum(ratios) / len(ratios), 6)
                if ratios
                else None,
                "trust_score_end": round(bucket["trust_end"], 4) if bucket["trust_end"] is not None else None,
            }
        )

    return {
        "agent_id": agent_id,
        "window_days": days,
        "granularity": resolved_granularity,
        "points": points,
    }


@router.get("/{agent_id}/enhancements")
async def get_agent_enhancements(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Data-driven enhancement recommendations from runs, spans, and violations."""
    result = await db.execute(
        select(Agent)
        .where(Agent.agent_id == agent_id)
        .options(
            selectinload(Agent.runs).selectinload(Run.spans),
            selectinload(Agent.violations),
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    runs = sorted(agent.runs, key=lambda r: r.id)
    spans: list[Span] = []
    for run in runs:
        spans.extend(run.spans)

    return generate_enhancements(
        runs=runs,
        spans=spans,
        violations=list(agent.violations),
    )


@router.post("/{agent_id}/enhancements/apply")
async def apply_enhancement_to_contract(
    agent_id: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply an enhancement-generated YAML snippet to a pending contract proposal."""
    yaml_snippet = (payload.get("yaml_snippet") or "").strip()
    recommendation_type = payload.get("recommendation_type") or "enhancement"
    applied_by = payload.get("applied_by") or "dashboard-user"
    if not yaml_snippet:
        raise HTTPException(status_code=422, detail="yaml_snippet is required")

    agent_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    contracts_result = await db.execute(
        select(Contract)
        .where(Contract.agent_id == agent_id)
        .order_by(Contract.id.desc())
        .options(selectinload(Contract.versions))
    )
    contracts = contracts_result.scalars().all()
    if not contracts:
        tools: list[str] = []
        try:
            agent_path = _resolve_agent_path(agent_id, getattr(agent, "entry_point", None))
            if agent_path is not None:
                mod = _load_agent_module(agent_id, agent_path)
                tools = [t.name for t in _discover_tools_from_module(mod)]
        except Exception:
            tools = []

        generated = await generate_contract_proposal(
            {
                "agent_id": agent_id,
                "description": agent.name,
                "tools": tools,
                "system_prompt": "",
            },
            agent_id,
        )
        base_yaml = generated.get("yaml_content") or ""
        merged_yaml = apply_yaml_snippet(base_yaml, yaml_snippet)
        proposal = Contract(
            agent_id=agent_id,
            version="1.0",
            yaml_content=merged_yaml,
            summary_text=contract_summary_from_yaml(merged_yaml),
            is_active=False,
            created_by=applied_by,
        )
        db.add(proposal)
        await db.flush()
        db.add(ContractVersion(
            contract_id=proposal.id,
            changed_by=applied_by,
            reason=f"Bootstrapped contract from enhancement: {recommendation_type}",
        ))
        agent.pending_contract_version = "1.0"
        await db.commit()
        return {
            "status": "applied",
            "agent_id": agent_id,
            "contract_version": "1.0",
            "recommendation_type": recommendation_type,
            "created_new_proposal": True,
            "bootstrapped_contract": True,
        }

    pending = next((c for c in contracts if not c.is_active), None)

    if pending is not None:
        pending.yaml_content = apply_yaml_snippet(pending.yaml_content, yaml_snippet)
        pending.summary_text = contract_summary_from_yaml(pending.yaml_content)
        db.add(ContractVersion(
            contract_id=pending.id,
            changed_by=applied_by,
            reason=f"Applied enhancement: {recommendation_type}",
        ))
        await db.commit()
        await db.refresh(pending)
        return {
            "status": "applied",
            "agent_id": agent_id,
            "contract_version": pending.version,
            "recommendation_type": recommendation_type,
            "created_new_proposal": False,
        }

    active = contracts[0]
    try:
        next_version = f"{float(active.version) + 0.1:.1f}"
    except Exception:
        next_version = "1.1"

    new_yaml = apply_yaml_snippet(active.yaml_content, yaml_snippet)
    proposal = Contract(
        agent_id=agent_id,
        version=next_version,
        yaml_content=new_yaml,
        summary_text=contract_summary_from_yaml(new_yaml),
        is_active=False,
        created_by=applied_by,
    )
    db.add(proposal)
    await db.flush()
    db.add(ContractVersion(
        contract_id=proposal.id,
        changed_by=applied_by,
        reason=f"Created from active contract via enhancement: {recommendation_type}",
    ))
    agent.pending_contract_version = next_version
    await db.commit()

    return {
        "status": "applied",
        "agent_id": agent_id,
        "contract_version": next_version,
        "recommendation_type": recommendation_type,
        "created_new_proposal": True,
    }


@router.get("/{agent_id}/budget")
async def get_agent_budget(agent_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Budget).where(Budget.agent_id == agent_id))
    budget = result.scalar_one_or_none()
    if not budget:
        return {
            "agent_id": agent_id,
            "budget": None,
        }
    return {
        "agent_id": agent_id,
        "budget": {
            "period": budget.period,
            "max_cost_usd": budget.max_cost_usd,
            "max_runs": budget.max_runs,
            "enabled": budget.enabled,
        },
    }


@router.put("/{agent_id}/budget")
async def upsert_agent_budget(
    agent_id: str,
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    period = body.get("period", "monthly")
    max_cost_usd = float(body.get("max_cost_usd", 25.0))
    max_runs = body.get("max_runs")
    enabled = bool(body.get("enabled", True))

    if period not in ("daily", "monthly"):
        raise HTTPException(status_code=422, detail="period must be 'daily' or 'monthly'")

    agent_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    result = await db.execute(select(Budget).where(Budget.agent_id == agent_id))
    budget = result.scalar_one_or_none()
    if budget is None:
        budget = Budget(agent_id=agent_id)
        db.add(budget)

    budget.period = period
    budget.max_cost_usd = max_cost_usd
    budget.max_runs = int(max_runs) if max_runs is not None else None
    budget.enabled = enabled
    await db.flush()

    return {
        "agent_id": agent_id,
        "budget": {
            "period": budget.period,
            "max_cost_usd": budget.max_cost_usd,
            "max_runs": budget.max_runs,
            "enabled": budget.enabled,
        },
    }


@router.get("/{agent_id}/sub-agents")
async def get_sub_agents(agent_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Return sub-agents belonging to an orchestrator agent."""
    parent_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    parent = parent_result.scalar_one_or_none()
    if not parent:
        raise HTTPException(status_code=404, detail="Agent not found")

    result = await db.execute(
        select(Agent).where(Agent.parent_agent_id == agent_id)
    )
    sub_agents = result.scalars().all()
    mapped = [
        {
            "agent_id": sa.agent_id,
            "name": sa.name,
            "trust_score": round(sa.trust_score, 4),
            "current_tier": sa.current_tier,
            "type": sa.agent_type or "standard",
            "enabled": sa.enabled,
            "virtual": False,
        }
        for sa in sub_agents
    ]
    if mapped:
        return mapped

    if parent.agent_type == "orchestrator" or parent.type == "orchestrator":
        return _build_virtual_sub_agents(
            parent,
            _resolve_agent_path(agent_id, parent.entry_point),
        )
    return []


@router.post("/")
async def create_agent(payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    """Register a new agent (proposal only — does not activate a contract).

    Required: agent_id, name
    Optional: type (default "single"), department, owner, description, tools[]
    If tools[] provided, auto-generates a contract proposal (not activated).
    """
    agent_id = payload.get("agent_id")
    name = payload.get("name")
    if not agent_id or not name:
        raise HTTPException(status_code=422, detail="agent_id and name are required")

    # Check uniqueness
    existing = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent '{agent_id}' already exists")

    agent = Agent(
        agent_id=agent_id,
        name=name,
        type=payload.get("type", "single"),
        department=payload.get("department"),
        owner=payload.get("owner"),
        current_tier="restricted",
        trust_score=0.40,
        enabled=True,
    )
    db.add(agent)
    await db.flush()

    # Auto-generate contract proposal if tools provided
    contract_result = None
    tools = payload.get("tools", [])
    description = payload.get("description", name)
    if tools or description:
        from norma.core.contract_generator import generate_contract_proposal
        from norma.core.contract_engine import contract_summary_from_yaml

        agent_config = {
            "agent_id": agent_id,
            "description": description,
            "tools": tools,
            "system_prompt": payload.get("system_prompt", ""),
        }
        contract_result = await generate_contract_proposal(agent_config, agent_id)

        contract = Contract(
            agent_id=agent_id,
            version="1.0",
            yaml_content=contract_result["yaml_content"],
            summary_text=contract_summary_from_yaml(contract_result["yaml_content"]),
            is_active=False,
            created_by="norma-onboarding",
        )
        db.add(contract)
        agent.pending_contract_version = "1.0"

    await db.commit()

    # Reload with relationships for payload builder
    result = await db.execute(
        select(Agent)
        .where(Agent.agent_id == agent_id)
        .options(
            selectinload(Agent.runs).selectinload(Run.violations),
            selectinload(Agent.contracts),
            selectinload(Agent.violations),
        )
    )
    agent = result.scalar_one()

    response = _build_agent_payload(agent)
    if contract_result:
        response["contract_proposal"] = {
            "version": "1.0",
            "source": contract_result.get("source", "stub"),
            "meta": contract_result.get("meta", {}),
            "validation_errors": contract_result.get("validation_errors", []),
        }

    # Broadcast SSE event
    from norma.api.events import broadcast
    broadcast("agent_created", {"agent_id": agent_id, "name": name, "tier": "restricted"})

    return response


@router.delete("/{agent_id}", status_code=204, response_model=None)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    """Delete an agent and all associated runs, contracts, and violations."""
    from norma.models.run import Run
    from norma.models.contract import Contract
    from norma.models.violation import Violation
    from sqlalchemy import delete as sa_delete

    result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Cascade-delete in dependency order
    run_ids_result = await db.execute(select(Run.id).where(Run.agent_id == agent_id))
    run_ids = [row[0] for row in run_ids_result.fetchall()]

    if run_ids:
        await db.execute(sa_delete(Violation).where(Violation.run_id.in_(run_ids)))

    await db.execute(sa_delete(Violation).where(Violation.agent_id == agent_id))
    await db.execute(sa_delete(Contract).where(Contract.agent_id == agent_id))
    await db.execute(sa_delete(Run).where(Run.agent_id == agent_id))
    await db.delete(agent)
    await db.commit()
    return Response(status_code=204)


@router.post("/onboard")
async def onboard_agent_from_code(payload: dict, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Real onboarding: point norma at a Python directory, get a monitored agent.

    Difference from POST /api/agents/:
      - Input is a filesystem path to agent Python code (not a JSON form)
      - Tools are DISCOVERED by scanning the code for @tool decorators
      - Contract proposal is generated from real tool names, not user-typed text
      - next_steps guides the team through the remaining manual work

    Required body fields:
        directory   str  — absolute path to the agent Python directory or file
        agent_id    str  — new agent identifier (lowercase [a-z0-9_-])
        name        str  — human-readable display name
    Optional:
        type        str  — single | orchestrator | subagent  (default: single)
        description str  — description passed to contract generator
        department  str
        owner       str
        system_prompt str

    Returns:
        agent payload + introspection result + contract_proposal + next_steps
    """
    import re

    from norma.agents.introspect import introspect_directory, introspect_file
    from norma.core.contract_generator import generate_contract_proposal
    from norma.core.contract_engine import contract_summary_from_yaml

    directory = payload.get("directory")
    agent_id = payload.get("agent_id")
    name = payload.get("name")
    # entry_point: specific file the UI picked (from scan candidates);
    # preferred over directory so we store the exact file, not just the folder.
    entry_point_raw = payload.get("entry_point")

    if not directory:
        raise HTTPException(status_code=422, detail="'directory' is required (path to agent code)")
    if not agent_id or not name:
        raise HTTPException(status_code=422, detail="'agent_id' and 'name' are required")
    if not re.fullmatch(r"[a-z0-9_-]+", agent_id):
        raise HTTPException(
            status_code=422,
            detail="agent_id must be lowercase alphanumeric with hyphens/underscores only",
        )

    # Uniqueness check
    existing = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Agent '{agent_id}' already exists")

    # Step 1 — Introspect the code (AST-based, never executes user code)
    # If a specific entry_point file was provided by the UI, use it directly;
    # otherwise fall back to the whole directory.
    from pathlib import Path as _Path
    entry_file: _Path | None = None
    if entry_point_raw:
        _ep = _Path(entry_point_raw)
        if _ep.is_file():
            entry_file = _ep
    target = entry_file if entry_file is not None else _Path(directory)
    try:
        if target.is_file():
            from norma.agents.introspect import introspect_file
            introspection = introspect_file(target)
        else:
            introspection = introspect_directory(target)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    tool_names = introspection["tool_names"]
    data_hints = introspection["data_path_hints"]

    # Detect framework from introspection
    detected_framework: str | None = None
    if introspection.get("agents"):
        detected_framework = introspection["agents"][0].get("framework")

    # Resolve the canonical entry_point string to persist in DB.
    # Prefer the detected agent candidate entry point when onboarding a directory.
    if target.is_file():
        resolved_entry_point = str(target)
    else:
        agents = introspection.get("agents") or []
        first_entry = agents[0].get("entry_point") if agents and isinstance(agents[0], dict) else None
        if first_entry:
            resolved_entry_point = str(first_entry)
        else:
            py_files = sorted(target.glob("*.py"))
            if not py_files:
                raise HTTPException(
                    status_code=422,
                    detail=f"No Python files found for runnable entry point in: {target}",
                )
            preferred = [
                "main.py",
                "agent.py",
                "orchestrator.py",
                "pipeline.py",
                "__init__.py",
            ]
            chosen = next((f for name in preferred for f in py_files if f.name == name), py_files[0])
            resolved_entry_point = str(chosen)

    # Step 2 — Register the agent
    agent = Agent(
        agent_id=agent_id,
        name=name,
        type=payload.get("type", "single"),
        department=payload.get("department"),
        owner=payload.get("owner"),
        current_tier="restricted",
        trust_score=0.40,
        enabled=True,
        entry_point=resolved_entry_point,
        directory=directory,
        framework=detected_framework,
    )
    db.add(agent)
    await db.flush()

    # Step 3 — Generate contract from introspected tool names (not user-typed text)
    agent_config = {
        "agent_id": agent_id,
        "description": payload.get("description", f"Agent introspected from {directory}"),
        "tools": tool_names,
        "system_prompt": payload.get("system_prompt", ""),
        "data_hints": data_hints,
    }
    contract_result = await generate_contract_proposal(agent_config, agent_id)

    contract = Contract(
        agent_id=agent_id,
        version="1.0",
        yaml_content=contract_result["yaml_content"],
        summary_text=contract_summary_from_yaml(contract_result["yaml_content"]),
        is_active=False,
        created_by="norma-onboard",
    )
    db.add(contract)
    agent.pending_contract_version = "1.0"

    await db.commit()

    # Broadcast
    from norma.api.events import broadcast
    broadcast("agent_created", {"agent_id": agent_id, "name": name, "tier": "restricted"})

    # S7: Auto-run one sample task after onboarding so the dashboard has
    # immediate metrics rather than showing zeros.
    import asyncio as _asyncio

    sample_run_result: dict | None = None
    try:
        from norma.config import get_settings as _get_settings
        _sync_db_url = _get_settings().database_url.replace("+aiosqlite", "")

        # Load the module we just onboarded — safe to import now since this is
        # the operator confirming execution after onboarding.
        _ep_path = _Path(resolved_entry_point)
        _mod = _load_agent_module(agent_id, _ep_path)

        # Discover tools: prefer ALL_TOOLS attribute, else scan namespace
        from langchain_core.tools import BaseTool as _BT
        _tools: list = list(getattr(_mod, "ALL_TOOLS", None) or [
            obj for name, obj in vars(_mod).items()
            if not name.startswith("_") and isinstance(obj, _BT)
        ])

        if _tools:
            # Use the just-generated contract (not the agent-embedded one)
            _contract_yaml_sample = contract_result["yaml_content"]
            import yaml as _yaml_s
            _allow = _yaml_s.safe_load(_contract_yaml_sample).get("authorities", {}).get("tools", {}).get("allow", [])
            _tmap = {t.name: t for t in _tools}
            # Pick the first allowed tool that actually exists in the discovered set
            _probe_name = next((n for n in _allow if n in _tmap), None) or _tools[0].name

            _out: list[str] = [""]
            _blk: list[bool] = [False]

            def _sample_run() -> None:
                import asyncio as _asyncio_t
                from norma.integrations.session import NormaAgentSession as _S
                from norma.core.quality_scorer import evaluate_quality as _eq
                with _S(
                    agent_id=agent_id,
                    contract_yaml=_contract_yaml_sample,
                    contract_version="1.0",
                    db_url=_sync_db_url,
                ) as sess:
                    _wrapped = {t.name: t for t in sess.wrap_tools(list(_tmap.values()))}
                    _tool = _wrapped.get(_probe_name)
                    if _tool is None:
                        _out[0] = f"Tool '{_probe_name}' not in wrapped set"
                        return
                    _result = _tool.run({})
                    _out[0] = str(_result)
                    _blk[0] = bool(sess._blocked)
                    if not _blk[0]:
                        _qr = _asyncio_t.run(_eq(_out[0], task_description=f"Probe: {_probe_name}"))
                        sess.record_quality_result(_qr)
                    else:
                        sess.record_quality(0.0)

            _loop = _asyncio.get_event_loop()
            await _loop.run_in_executor(None, _sample_run)
            sample_run_result = {
                "task": f"Probe: {_probe_name}",
                "tool": _probe_name,
                "output": _out[0][:300],
                "blocked": _blk[0],
            }
            broadcast("run_completed", {"agent_id": agent_id, "blocked": _blk[0]})
        else:
            sample_run_result = {"skipped": "No tools discovered in the onboarded module"}
    except Exception as _exc:  # never fail onboarding because of the sample run
        sample_run_result = {"error": str(_exc)}

    # Reload for response
    result = await db.execute(
        select(Agent)
        .where(Agent.agent_id == agent_id)
        .options(
            selectinload(Agent.runs).selectinload(Run.violations),
            selectinload(Agent.contracts),
            selectinload(Agent.violations),
        )
    )
    agent = result.scalar_one()
    response = _build_agent_payload(agent)
    response["introspection"] = {
        "tool_names": tool_names,
        "files_scanned": introspection["files_scanned"],
        "data_path_hints": data_hints[:10],
        "errors": introspection["errors"],
        "source": "ast",   # tools came from code scan, not user input
        "framework": detected_framework,
    }
    response["contract_proposal"] = {
        "version": "1.0",
        "source": contract_result.get("source", "stub"),
        "meta": contract_result.get("meta", {}),
        "validation_errors": contract_result.get("validation_errors", []),
    }
    response["next_steps"] = [
        f"Review REVIEW REQUIRED fields in the contract proposal above",
        f"Edit data.deny to match your actual sensitive data paths",
        f"Approve via: POST /api/contracts/{agent_id}/approve/1.0",
        f"Instrument your agent: wrap tools with NormaAgentSession",
        f"Run a sample execution to verify enforcement works",
    ]
    if sample_run_result is not None:
        response["sample_run"] = sample_run_result
    return response


@router.get("/{agent_id}/runs/recent")
async def get_agent_recent_runs(
    agent_id: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Recent runs for an agent with enforcement events. Used by the run timeline panel."""
    result = await db.execute(
        select(Agent)
        .where(Agent.agent_id == agent_id)
        .options(selectinload(Agent.runs).selectinload(Run.violations))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    runs = sorted(agent.runs, key=lambda r: r.id, reverse=True)[:limit]
    return [
        {
            "run_id": r.id,
            "parent_run_id": r.parent_run_id,
            "initiated_by": r.initiated_by,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "status": r.completion_status,
            "quality_score": r.quality_score,
            "trust_score_after": r.trust_score_after,
            "latency_ms": r.latency_ms,
            "cost_usd": r.cost_usd,
            "contract_version": r.contract_version,
            "enforcement_events": [
                {
                    "type": "blocked" if v.blocked else "audited",
                    "policy_rule": v.policy_rule,
                    "action_attempted": v.action_attempted,
                    "event_type": v.event_type,
                }
                for v in r.violations
            ],
        }
        for r in runs
    ]


@router.get("/{agent_id}/export/compliance")
async def export_compliance(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export all runs + violations as a CSV for compliance auditing."""
    result = await db.execute(
        select(Agent)
        .where(Agent.agent_id == agent_id)
        .options(selectinload(Agent.runs).selectinload(Run.violations))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "run_id", "timestamp", "status", "contract_version",
        "quality_score", "trust_score_after", "latency_ms", "cost_usd",
        "violation_policy_rule", "violation_action_attempted", "violation_blocked",
    ])
    for r in sorted(agent.runs, key=lambda x: x.id):
        base = [
            r.id, r.timestamp.isoformat() if r.timestamp else "",
            r.completion_status, r.contract_version or "",
            r.quality_score or "", r.trust_score_after or "",
            r.latency_ms or "", r.cost_usd or "",
        ]
        if r.violations:
            for v in r.violations:
                writer.writerow(base + [v.policy_rule or "", v.action_attempted or "", v.blocked])
        else:
            writer.writerow(base + ["", "", ""])

    buf.seek(0)
    fname = f"norma_compliance_{agent_id}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


@router.get("/{agent_id}/graph")
async def get_agent_graph(
    agent_id: str,
    run_id: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the agent's tool graph for visualization.

    Parses the agent module's CONTRACT_YAML and ALL_TOOLS to build a graph of:
      - Agent node
      - Tool nodes (allowed vs denied)
      - Data source nodes
            - Task sequence hints (when available)
    """
    import yaml as _yaml

    _agent_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    _agent_row = _agent_result.scalar_one_or_none()
    if _agent_row is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    _ep_path = _resolve_agent_path(agent_id, _agent_row.entry_point)
    if not _ep_path:
        raise HTTPException(status_code=404, detail=f"No graph available for '{agent_id}' — not in registry")

    mod = _load_agent_module(agent_id, _ep_path)

    # Resolve contract YAML: module-embedded → DB active → DB any → empty
    from norma.config import get_settings as _get_settings
    _sync_db_url = _get_settings().database_url.replace("+aiosqlite", "")
    _raw_yaml = (
        getattr(mod, "CONTRACT_YAML", None)
        or _load_contract_from_db_sync(agent_id, _sync_db_url)
        or ""
    )
    contract = _yaml.safe_load(_raw_yaml) or {}

    # Support both nested (authorities.tools/data) and flat (tools/data) schemas
    _auth = contract.get("authorities") or {}
    _tools_block = _auth.get("tools") or contract.get("tools") or {}
    _data_block = _auth.get("data") or contract.get("data") or {}
    tools_allow: list[str] = _tools_block.get("allow") or []
    tools_deny: list[str] = _tools_block.get("deny") or []
    data_allow: list[str] = _data_block.get("allow") or []
    data_deny: list[str] = _data_block.get("deny") or []

    # Resolve tools: module-embedded → discovered from namespace
    all_tools = getattr(mod, "ALL_TOOLS", None) or _discover_tools_from_module(mod)

    nodes: list[dict] = [{"id": "agent", "label": agent_id, "type": "agent"}]
    edges: list[dict] = []

    for t in all_tools:
        status = "denied" if t.name in tools_deny else "allowed"
        nodes.append({
            "id": f"tool:{t.name}",
            "label": t.name,
            "type": "tool",
            "status": status,
            "description": (t.description or "")[:120],
        })
        edges.append({"from": "agent", "to": f"tool:{t.name}", "type": "uses" if status == "allowed" else "blocked"})

    for dp in data_allow:
        nid = f"data:{dp}"
        nodes.append({"id": nid, "label": dp, "type": "data", "status": "allowed"})
        for t in all_tools:
            if t.name in tools_allow:
                edges.append({"from": f"tool:{t.name}", "to": nid, "type": "reads"})

    for dp in data_deny:
        nid = f"data:{dp}"
        nodes.append({"id": nid, "label": dp, "type": "data", "status": "denied"})

    task_hints = _module_task_hints(mod)
    if task_hints:
        tasks = [
            {
                "index": i,
                "description": t["description"],
                "tool": t["tool"],
                "arg": t.get("arg"),
                "expected_blocked": t.get("expected_quality", 1.0) == 0.0,
            }
            for i, t in enumerate(task_hints)
        ]
    else:
        tasks = [
            {
                "index": i,
                "description": f"Allowed tool: {tool_name}",
                "tool": tool_name,
                "arg": None,
                "expected_blocked": False,
            }
            for i, tool_name in enumerate(tools_allow)
        ]

    # If we have real span telemetry, prefer an execution-ordered graph.
    execution_run_id: int | None = None
    phase_groups: list[dict] = []
    phase_label_source: str | None = None
    recent_runs_result = await db.execute(
        select(Run)
        .where(Run.agent_id == agent_id)
        .order_by(Run.id.desc())
        .limit(30)
    )
    recent_runs = recent_runs_result.scalars().all()
    available_runs = [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "status": r.completion_status,
            "quality_score": r.quality_score,
            "cost_usd": r.cost_usd,
        }
        for r in recent_runs
    ]

    target_run = None
    if run_id is not None:
        target_run = next((r for r in recent_runs if r.id == run_id), None)
        if target_run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found for '{agent_id}'")
    elif recent_runs:
        target_run = recent_runs[0]

    if target_run is not None:
        span_result = await db.execute(
            select(Span)
            .where(Span.trace_id == target_run.id)
            .order_by(Span.id)
        )
        spans = span_result.scalars().all()
        exec_spans = [
            s for s in spans
            if s.span_type in {"llm_call", "tool_call", "agent_handoff"}
            or (s.span_type == "enforcement_check" and s.status == "blocked")
        ]

        # For orchestrator runs: also load child run spans so tool calls (including blocked ones) appear
        child_runs_result = await db.execute(
            select(Run).where(Run.parent_run_id == target_run.id).order_by(Run.id)
        )
        child_runs = child_runs_result.scalars().all()
        child_run_spans: dict[int, list[Span]] = {}  # child_run.id → spans
        for cr in child_runs:
            cr_span_result = await db.execute(
                select(Span)
                .where(Span.trace_id == cr.id)
                .where(Span.span_type.in_(["llm_call", "tool_call"]))
                .order_by(Span.id)
            )
            child_run_spans[cr.id] = cr_span_result.scalars().all()

        if exec_spans:
            execution_run_id = target_run.id
            phase_doc = await _llm_phase_groups_for_spans(exec_spans)
            if phase_doc is None:
                phase_doc = _heuristic_phase_groups_for_spans(exec_spans)

            phase_by_span = phase_doc.get("phase_by_span", {}) if isinstance(phase_doc, dict) else {}
            phase_groups = phase_doc.get("phase_groups", []) if isinstance(phase_doc, dict) else []
            phase_label_source = str(phase_doc.get("source") or "heuristic") if isinstance(phase_doc, dict) else "heuristic"

            exec_nodes: list[dict] = [{"id": "agent", "label": agent_id, "type": "agent"}]
            exec_edges: list[dict] = []
            exec_tasks: list[dict] = []

            # Build a lookup: sub-agent name → child run (for orchestrator parent runs)
            child_run_by_subagent: dict[str, Run] = {}
            for cr in child_runs:
                child_run_by_subagent[cr.agent_id] = cr

            prev_node_id = "agent"
            global_idx = 0
            for idx, span in enumerate(exec_spans):
                node_id = f"span:{span.id}"
                node_label = (
                    f"llm:{span.name}" if span.span_type == "llm_call"
                    else span.name.removeprefix("enforce:") if span.span_type == "enforcement_check"
                    else span.name
                )
                phase_meta = phase_by_span.get(span.span_id, {}) if isinstance(phase_by_span, dict) else {}
                node_type = (
                    "model" if span.span_type == "llm_call"
                    else "subagent" if span.span_type == "agent_handoff"
                    else "tool"
                )
                exec_nodes.append(
                    {
                        "id": node_id,
                        "label": node_label,
                        "type": node_type,
                        "status": "denied" if span.status == "blocked" else "allowed",
                        "description": f"{span.span_type} · {span.status}",
                        "phase_id": phase_meta.get("phase_id"),
                        "phase_name": phase_meta.get("phase_name"),
                        "phase_confidence": phase_meta.get("confidence"),
                    }
                )
                exec_edges.append(
                    {
                        "from": prev_node_id,
                        "to": node_id,
                        "type": "blocked" if span.status == "blocked" else "sequence",
                        "order": global_idx + 1,
                        "phase_id": phase_meta.get("phase_id"),
                        "telemetry": {
                            "run_id": target_run.id,
                            "span_id": span.span_id,
                            "parent_span_id": span.parent_span_id,
                            "span_type": span.span_type,
                            "name": span.name,
                            "status": span.status,
                            "model_name": span.model_name,
                            "tokens_in": span.tokens_in,
                            "tokens_out": span.tokens_out,
                            "cost_usd": span.cost_usd,
                            "latency_ms": span.latency_ms,
                            "start_time": span.start_time.isoformat() if span.start_time else None,
                            "end_time": span.end_time.isoformat() if span.end_time else None,
                            "input_preview": _preview_jsonish(span.input_data),
                            "output_preview": _preview_jsonish(span.output_data),
                            "attributes": _parse_jsonish_object(span.attributes),
                            "run_input_tokens": target_run.input_tokens,
                            "run_output_tokens": target_run.output_tokens,
                            "run_cost_usd": target_run.cost_usd,
                            "run_latency_ms": target_run.latency_ms,
                            "run_quality_score": target_run.quality_score,
                            "timestamp": span.timestamp.isoformat() if span.timestamp else None,
                        },
                    }
                )
                exec_tasks.append(
                    {
                        "index": global_idx,
                        "description": f"{span.span_type}: {span.name}",
                        "tool": span.name,
                        "arg": _preview_jsonish(span.input_data, limit=80),
                        "expected_blocked": span.status == "blocked",
                    }
                )
                global_idx += 1
                prev_node_id = node_id

                # If this is a sub-agent handoff, emit its child run tool spans as nested nodes
                if span.span_type == "agent_handoff":
                    # Match by sub-agent name (span.name) to child run agent_id (may be partial match)
                    matched_cr = child_run_by_subagent.get(span.name)
                    if matched_cr is None:
                        # Try partial match: child run agent_id contains span.name or vice versa
                        for cr_aid, cr in child_run_by_subagent.items():
                            if span.name in cr_aid or cr_aid in span.name:
                                matched_cr = cr
                                break
                    if matched_cr is not None:
                        child_tool_spans = child_run_spans.get(matched_cr.id, [])
                        child_prev = node_id
                        for cidx, cspan in enumerate(child_tool_spans):
                            cnode_id = f"span:{cspan.id}"
                            exec_nodes.append(
                                {
                                    "id": cnode_id,
                                    "label": cspan.name,
                                    "type": "tool",
                                    "status": "denied" if cspan.status == "blocked" else "allowed",
                                    "description": f"tool_call · {cspan.status}",
                                    "phase_id": phase_meta.get("phase_id"),
                                    "phase_name": phase_meta.get("phase_name"),
                                }
                            )
                            exec_edges.append(
                                {
                                    "from": child_prev,
                                    "to": cnode_id,
                                    "type": "blocked" if cspan.status == "blocked" else "uses",
                                    "order": global_idx + 1,
                                    "telemetry": {
                                        "run_id": matched_cr.id,
                                        "span_id": cspan.span_id,
                                        "span_type": cspan.span_type,
                                        "name": cspan.name,
                                        "status": cspan.status,
                                        "latency_ms": cspan.latency_ms,
                                        "input_preview": _preview_jsonish(cspan.input_data),
                                        "output_preview": _preview_jsonish(cspan.output_data),
                                        "timestamp": cspan.timestamp.isoformat() if cspan.timestamp else None,
                                    },
                                }
                            )
                            exec_tasks.append(
                                {
                                    "index": global_idx,
                                    "description": f"tool_call: {cspan.name}",
                                    "tool": cspan.name,
                                    "arg": _preview_jsonish(cspan.input_data, limit=80),
                                    "expected_blocked": cspan.status == "blocked",
                                }
                            )
                            global_idx += 1
                            child_prev = cnode_id

            nodes = exec_nodes
            edges = exec_edges
            tasks = exec_tasks

    return {
        "agent_id": agent_id,
        "tier": contract.get("tier", "restricted"),
        "nodes": nodes,
        "edges": edges,
        "tasks": tasks,
        "graph_source": "execution" if execution_run_id is not None else "contract",
        "execution_run_id": execution_run_id,
        "available_runs": available_runs,
        "phase_groups": phase_groups,
        "phase_label_source": phase_label_source,
    }


@router.post("/{agent_id}/check-changes")
async def check_agent_changes(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Recompute the file hash for an agent and compare with the stored hash.

    If the hash changed, increments agent_code_version and sets code_status='changed'.
    If files are missing, sets code_status='missing'.
    If unchanged, sets code_status='ok'.
    Always updates last_seen_at.
    """
    from norma.agents.introspect import _compute_file_hash

    result = await db.execute(
        select(Agent).where(Agent.agent_id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Resolve files to hash from DB entry_point (no hardcoded registry)
    agent_files_path = _resolve_agent_path(agent_id, agent.entry_point)
    if agent_files_path is None:
        raise HTTPException(status_code=404, detail=f"No registered runnable entry_point for {agent_id}")

    # Determine directory to scan
    agent_dir = agent_files_path.parent
    py_files = sorted(agent_dir.glob("*.py")) if agent_dir.exists() else []

    now = datetime.now(timezone.utc)

    if not py_files:
        agent.code_status = "missing"
        agent.last_seen_at = now
        await db.commit()
        return {
            "agent_id": agent_id,
            "status": "missing",
            "message": "Agent directory not found or no Python files present",
        }

    current_hash = _compute_file_hash(py_files)
    prev_hash = agent.file_hash
    changed = prev_hash is not None and current_hash != prev_hash

    if changed:
        agent.agent_code_version += 1
        agent.code_status = "changed"
    elif prev_hash is None:
        # First-time check — just record the hash
        agent.code_status = "ok"
    else:
        agent.code_status = "ok"

    agent.file_hash = current_hash
    agent.entry_point = str(agent_files_path.relative_to(_PROJECT_ROOT))
    agent.directory = str(agent_dir.relative_to(_PROJECT_ROOT))
    agent.last_seen_at = now
    await db.commit()

    return {
        "agent_id": agent_id,
        "status": agent.code_status,
        "prev_hash": prev_hash,
        "current_hash": current_hash,
        "changed": changed,
        "agent_code_version": agent.agent_code_version,
        "files_checked": [str(f.name) for f in py_files],
        "last_seen_at": now.isoformat(),
    }


@router.post("/{agent_id}/execute")
async def execute_agent_task(
    agent_id: str,
    mode: str = Query("step", description="'step' = run one tool; 'full' = run all tools; 'llm' = invoke real LLM agent"),
    body: dict | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Execute contract-allowed tool tasks for the agent.

    mode=step (default): run the next tool, cycling by run count.
    mode=full: run every discovered tool end-to-end, returning per-step results.
    mode=llm:  invoke the agent's build_llm_agent() or build_langgraph_agent() with
               the full NormaCallbackHandler so real token/cost metrics are captured.
               Body: {"input": "user task description"}
    """
    import asyncio

    from norma.config import get_settings

    settings = get_settings()

    # ── Resolve agent file path purely from DB ──────────────────────────────────
    _ep_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    _ep_agent = _ep_result.scalar_one_or_none()
    if _ep_agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    agent_path = _resolve_agent_path(agent_id, _ep_agent.entry_point)
    if agent_path is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Agent '{agent_id}' has no runnable entry point. "
                "Onboard it via POST /api/agents/onboard with a Python directory "
                "that defines @tool-decorated functions."
            ),
        )

    mod = _load_agent_module(agent_id, agent_path)
    sync_db_url = settings.database_url.replace("+aiosqlite", "")

    # ── Resolve tools and contract ──────────────────────────────────────────────
    # Contract priority: DB active → DB pending (awaiting approval).
    # The contract the human approved in the dashboard governs execution.
    # The agent file itself must NOT contain a CONTRACT_YAML — norma owns that.
    _db_contract_yaml = _load_contract_from_db_sync(agent_id, sync_db_url)

    ALL_TOOLS = _discover_tools_from_module(mod)
    forced_llm_mode = False
    if not ALL_TOOLS and mode in {"step", "full"}:
        # Non-LangChain agents (e.g. OpenAI function-calling SDK usage) may
        # expose no module-level BaseTool objects; run via the LLM entrypoint.
        mode = "llm"
        forced_llm_mode = True

    if mode in {"step", "full"} and not ALL_TOOLS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No LangChain @tool functions found in '{agent_path.name}'. "
                "Ensure tools are decorated with @tool."
            ),
        )

    if not _db_contract_yaml:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Agent '{agent_id}' has no approved contract. "
                "Complete onboarding (POST /api/agents/onboard) and approve the "
                "generated contract before running."
            ),
        )
    CONTRACT_YAML = _db_contract_yaml

    module_hints = {
        h["tool"]: h for h in _module_task_hints(mod)
        if isinstance(h, dict) and isinstance(h.get("tool"), str)
    }

    def _build_task_plan(
        tools: list,
        contract_yaml: str,
        task_hints: dict[str, dict] | None = None,
    ) -> list[dict]:
        """Build an ordered list of runnable tasks from a tool list + contract.

        Tools allowed by the contract come first, then any remaining discovered
        tools. If body specifies a specific tool, only that tool runs.
        No SCRIPTED_TASKS or TASK_HINTS are used — the execute endpoint discovers
        all tools automatically.
        """
        import yaml as _yaml_rt

        _contract_doc = _yaml_rt.safe_load(contract_yaml) or {}
        _task_hints = task_hints or module_hints
        _tools_allow: list[str] = (
            _contract_doc.get("authorities", {}).get("tools", {}).get("allow", [])
            or _contract_doc.get("tools", {}).get("allow", [])
            or []
        )
        _tool_map = {t.name: t for t in tools}
        _all_tool_names = list(_tool_map)
        runnable_allow = [n for n in _tools_allow if n in _all_tool_names]
        runnable_other = [n for n in _all_tool_names if n not in runnable_allow]
        runnable = runnable_allow + runnable_other

        # If a specific tool+arg was requested from the UI, run only that
        requested_tool = (body or {}).get("tool")
        if isinstance(requested_tool, str):
            if requested_tool not in _all_tool_names:
                raise HTTPException(
                    status_code=422,
                    detail=f"Tool '{requested_tool}' not in module. Available: {_all_tool_names}",
                )
            return [{"description": f"UI-triggered: {requested_tool}", "tool": requested_tool, "arg": (body or {}).get("arg")}]

        plan: list[dict] = []
        for name in runnable:
            default_arg = _infer_tool_default_arg(
                _tool_map[name],
                agent_id=agent_id,
                contract_yaml=contract_yaml,
                task_hints=_task_hints,
                all_tools=tools,
            )
            plan.append(
                {
                    "description": str((_task_hints.get(name, {}) or {}).get("description") or f"Run tool: {name}"),
                    "tool": name,
                    "arg": default_arg,
                }
            )
        return plan

    # ── Broadcast run_started so dashboard can show live running indicator ───────
    try:
        from norma.api.events import broadcast
        broadcast("run_started", {"agent_id": agent_id, "mode": mode})
    except Exception:
        pass

    # ── mode=llm: invoke real LLM agent with NormaCallbackHandler ──────────────
    if mode == "llm":
        llm_runner = _resolve_llm_runner(mod)
        if llm_runner is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Agent '{agent_id}' module has no runnable LLM entrypoint. "
                    "Add one of: build_llm_agent(), build_langgraph_agent(), "
                    "build_agent(), run_agent(), run(), execute(), or a module-level "
                    "graph/agent/workflow object with .invoke()."
                ),
            )
        if llm_runner[0] == "builder" and not settings.openai_api_key:
            raise HTTPException(
                status_code=422,
                detail="mode=llm requires OPENAI_API_KEY to be set in the environment.",
            )

        _raw_input = (body or {}).get("input")
        if isinstance(_raw_input, str) and _raw_input.strip():
            task_input = _raw_input.strip()
        else:
            task_input = _default_llm_input(agent_id, CONTRACT_YAML, ALL_TOOLS)

        # Reload agent row (we have it already from _ep_agent)
        agent_row = _ep_agent
        trust_start = float(agent_row.trust_score)
        active_contract_res = await db.execute(
            select(Contract)
            .where(Contract.agent_id == agent_id, Contract.is_active == True)  # noqa: E712
            .order_by(Contract.id.desc())
        )
        active_contract = active_contract_res.scalar_one_or_none()
        contract_version_label = active_contract.version if active_contract else "1.0"

        loop = asyncio.get_event_loop()

        def _run_llm_agent() -> dict:
            import asyncio as _asyncio_t
            from norma.integrations.session import NormaAgentSession
            from norma.middleware.langchain_callback import NormaCallbackHandler
            from norma.core.quality_scorer import evaluate_quality as _eq

            runner_kind, runner_obj, _runner_name = llm_runner

            def _extract_output(result: object) -> str:
                if isinstance(result, dict):
                    for key in ("output", "final_report", "answer", "response", "result"):
                        val = result.get(key)
                        if val is not None:
                            return str(val)
                return str(result)

            with NormaAgentSession(
                agent_id=agent_id,
                contract_yaml=CONTRACT_YAML,
                contract_version=contract_version_label,
                db_url=sync_db_url,
                initiated_by="api-llm",
            ) as sess:
                wrapped_tools = sess.wrap_tools(ALL_TOOLS)
                callback = NormaCallbackHandler(sess)
                if runner_kind == "builder":
                    # Pass wrapped tools + session so multi-node agents (e.g. research-team)
                    # get per-subagent span nesting.
                    try:
                        llm_agent = runner_obj(wrapped_tools=wrapped_tools, session=sess)
                    except TypeError:
                        llm_agent = runner_obj()
                    # LangGraph compiled graphs use .invoke; AgentExecutor also uses .invoke
                    try:
                        result = llm_agent.invoke(
                            {"input": task_input},
                            config={"callbacks": [callback]},
                        )
                    except AgentPausedError:
                        raise
                    except Exception:
                        try:
                            result = llm_agent.invoke(
                                {"messages": [{"role": "user", "content": task_input}]},
                                config={"callbacks": [callback]},
                            )
                        except Exception:
                            result = llm_agent.invoke(
                                {"topic": task_input},
                                config={"callbacks": [callback]},
                            )
                    output = _extract_output(result)
                elif runner_kind == "invoke_obj":
                    target = runner_obj
                    try:
                        result = target.invoke({"input": task_input})
                    except Exception:
                        try:
                            result = target.invoke({"topic": task_input})
                        except Exception:
                            result = target.invoke(task_input)
                    output = _extract_output(result)
                    sess.record_llm_call(
                        model="external_runner",
                        input_data={"input": task_input},
                        output_text=output,
                        tokens_in=0,
                        tokens_out=0,
                        cost_usd=0.0,
                    )
                elif runner_kind == "run_obj":
                    target = runner_obj
                    try:
                        result = target.run(task_input)
                    except Exception:
                        result = target.run(input=task_input)
                    output = _extract_output(result)
                    sess.record_llm_call(
                        model="external_runner",
                        input_data={"input": task_input},
                        output_text=output,
                        tokens_in=0,
                        tokens_out=0,
                        cost_usd=0.0,
                    )
                else:
                    func = runner_obj
                    try:
                        result = func(task_input)
                    except AgentPausedError:
                        raise
                    except Exception as exc_primary:
                        try:
                            result = func(input=task_input)
                        except Exception as exc_input:
                            try:
                                result = func(topic=task_input)
                            except Exception as exc_topic:
                                msg = str(exc_topic or exc_input or exc_primary)
                                if "OPENAI_API_KEY" in msg:
                                    raise RuntimeError(
                                        "mode=llm requires OPENAI_API_KEY to be set in the environment."
                                    ) from exc_topic
                                raise
                    output = _extract_output(result)
                    sess.record_llm_call(
                        model="external_runner",
                        input_data={"input": task_input},
                        output_text=output,
                        tokens_in=0,
                        tokens_out=0,
                        cost_usd=0.0,
                    )

                _qr = _asyncio_t.run(_eq(str(output), task_description=task_input))
                sess.record_quality_result(_qr)
                quality = _qr.score

            return {
                "output": str(output)[:1000],
                "quality_score": quality,
                "blocked": bool(sess._blocked),
                "input_tokens": sess._input_tokens,
                "output_tokens": sess._output_tokens,
                "cost_usd": float(sess._cost_usd),
            }

        try:
            llm_result = await loop.run_in_executor(None, _run_llm_agent)
        except RuntimeError as exc:
            if "OPENAI_API_KEY" in str(exc):
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise
        await db.refresh(agent_row)
        trust_after = float(agent_row.trust_score)
        from norma.api.events import broadcast
        broadcast("run_completed", {"agent_id": agent_id, "blocked": llm_result["blocked"]})

        return {
            "mode": "llm",
            "agent_id": agent_id,
            "input": task_input,
            "output": llm_result["output"],
            "blocked": llm_result["blocked"],
            "quality_score": llm_result["quality_score"],
            "token_counts": {
                "input": llm_result["input_tokens"],
                "output": llm_result["output_tokens"],
            },
            "cost_usd": llm_result["cost_usd"],
            "trust_before": round(trust_start, 4),
            "trust_after": round(trust_after, 4),
            "trust_delta": round(trust_after - trust_start, 4),
            "note": "Executed in llm mode because no LangChain @tool objects were discovered." if forced_llm_mode else None,
        }

    # ── Prepare task plan for step/full modes (tool-by-tool execution) ──────────
    TASK_PLAN = _build_task_plan(ALL_TOOLS, CONTRACT_YAML)
    if not TASK_PLAN:
        raise HTTPException(status_code=422, detail=f"No runnable tasks found for '{agent_id}'")

    # ── Detect orchestrator: has SUBAGENTS attribute ───────────────────────────
    is_orchestrator = hasattr(mod, "SUBAGENTS") and isinstance(mod.SUBAGENTS, list)

    # ── Verify agent exists in DB ──────────────────────────────────────────────
    result = await db.execute(
        select(Agent).where(Agent.agent_id == agent_id)
    )
    agent_row = result.scalar_one_or_none()
    if agent_row is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # ── Backfill entry_point if missing (self-heal agents onboarded pre-fix) ──
    if not agent_row.entry_point:
        agent_row.entry_point = str(agent_path)
        await db.commit()

    # ── Backfill parent_agent_id on sub-agents if orchestrator ────────────────
    if is_orchestrator:
        for sub_id in mod.SUBAGENTS:
            sub_result = await db.execute(select(Agent).where(Agent.agent_id == sub_id))
            sub_row = sub_result.scalar_one_or_none()
            if sub_row and not sub_row.parent_agent_id:
                sub_row.parent_agent_id = agent_id
        await db.commit()

    # ── Resolve contract version label ─────────────────────────────────────────
    from norma.models.contract import Contract as _Contract
    active_contract_result = await db.execute(
        select(_Contract)
        .where(_Contract.agent_id == agent_id, _Contract.is_active == True)  # noqa: E712
        .order_by(_Contract.id.desc())
    )
    active_contract = active_contract_result.scalar_one_or_none()
    contract_version_label = active_contract.version if active_contract else "1.0"
    sync_db_url = get_settings().database_url.replace("+aiosqlite", "")
    trust_start = float(agent_row.trust_score)

    from norma.api.events import broadcast

    # ── Orchestrator mode: run sub-agents as child runs ────────────────────────
    if is_orchestrator and mode in ("step", "full"):
        sub_ids: list[str] = mod.SUBAGENTS

        # Load sub-agent modules
        sub_mods = {}
        for sid in sub_ids:
            _sub_agent_result = await db.execute(select(Agent).where(Agent.agent_id == sid))
            _sub_agent_row = _sub_agent_result.scalar_one_or_none()
            if _sub_agent_row is None:
                continue
            _sub_path = _resolve_agent_path(sid, _sub_agent_row.entry_point)
            if _sub_path is None:
                continue
            sub_mods[sid] = _load_agent_module(sid, _sub_path)

        # Resolve sub-agent contract versions
        sub_contract_versions: dict[str, str] = {}
        for sid in sub_ids:
            _scr = await db.execute(
                select(_Contract)
                .where(_Contract.agent_id == sid, _Contract.is_active == True)  # noqa: E712
                .order_by(_Contract.id.desc())
            )
            _sc = _scr.scalar_one_or_none()
            sub_contract_versions[sid] = _sc.version if _sc else "1.0"

        def _exec_sub_task(task: dict, sub_id: str, parent_run_id_val: int) -> dict:
            """Run one sub-agent task as a child run under the orchestrator's run."""
            import asyncio as _asyncio_t
            from norma.integrations.session import NormaAgentSession
            from norma.core.quality_scorer import evaluate_quality as _eq
            s_mod = sub_mods.get(sub_id)
            if s_mod is None:
                return {"output": f"Sub-agent {sub_id} not loaded", "blocked": False, "quality_score": None}
            tool_map = {t.name: t for t in s_mod.ALL_TOOLS}
            out_buf: list[str] = [""]
            blk_buf: list[bool] = [False]
            with NormaAgentSession(
                agent_id=sub_id,
                contract_yaml=sub_contract_yaml_by_id.get(sub_id, getattr(s_mod, "CONTRACT_YAML", "")),
                contract_version=sub_contract_versions.get(sub_id, "1.0"),
                db_url=sync_db_url,
                parent_run_id=parent_run_id_val,
                initiated_by=f"orchestrator:{agent_id}",
            ) as sess:
                wrapped = {t.name: t for t in sess.wrap_tools(list(tool_map.values()))}
                tool_name = task["tool"]
                if tool_name not in wrapped:
                    return {"output": f"Tool '{tool_name}' not found in {sub_id}", "blocked": False, "quality_score": None}
                arg = task.get("arg")
                try:
                    out = wrapped[tool_name].run(arg or {}) if arg else wrapped[tool_name].run({})
                except AgentPausedError:
                    raise
                except Exception as _e:
                    retry_arg = _arg_from_validation_error(
                        _e,
                        tool_name=tool_name,
                        agent_id=sub_id,
                        contract_yaml=sub_contract_yaml_by_id.get(sub_id, ""),
                        all_tools=list(tool_map.values()),
                    )
                    if retry_arg is not None:
                        try:
                            out = wrapped[tool_name].run(retry_arg)
                        except Exception as _e2:
                            out = f"[skipped — tool '{tool_name}' requires input: {_e2}]"
                    else:
                        out = f"[skipped — tool '{tool_name}' requires input: {_e}]"
                out_buf[0] = str(out)
                blk_buf[0] = bool(sess._blocked)
                if blk_buf[0]:
                    sess.record_quality(0.0)
                    quality = 0.0
                else:
                    _qr = _asyncio_t.run(_eq(out_buf[0], task_description=task.get("description", "")))
                    sess.record_quality_result(_qr)
                    quality = _qr.score
            return {
                "output": out_buf[0],
                "blocked": blk_buf[0],
                "quality_score": None if blk_buf[0] else quality,
            }

        def _create_orchestrator_run_sync(
            orch_contract_version: str,
            n_tasks: int,
        ) -> int:
            """Create the parent (orchestrator) Run row and return its ID."""
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            engine = create_engine(sync_db_url, echo=False)
            _Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
            with _Session() as s:
                run = Run(
                    agent_id=agent_id,
                    parent_run_id=None,
                    initiated_by="api",
                    contract_version=orch_contract_version,
                    completion_status="success",
                    timestamp=__import__("datetime").datetime.utcnow(),
                )
                s.add(run)
                s.commit()
                s.refresh(run)
                return run.id

        def _finalize_orchestrator_run_sync(
            run_id: int,
            n_violations: int,
            avg_quality: float | None,
            latency_ms: int,
        ) -> None:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            engine = create_engine(sync_db_url, echo=False)
            _Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
            with _Session() as s:
                from norma.models.run import Run as _Run
                row = s.get(_Run, run_id)
                if row:
                    row.completion_status = "failed" if n_violations > 0 else "success"
                    row.quality_score = avg_quality
                    row.latency_ms = latency_ms
                    s.commit()

        import time as _time
        loop = asyncio.get_event_loop()

        # Build sub-agent task plans from each sub-agent's tools + contracts.
        all_sub_tasks: list[dict] = []
        sub_contract_yaml_by_id: dict[str, str] = {}
        for sub_id in sub_ids:
            s_mod = sub_mods.get(sub_id)
            if s_mod is None:
                continue
            s_tools = getattr(s_mod, "ALL_TOOLS", None) or _discover_tools_from_module(s_mod)
            if not s_tools:
                continue
            s_contract_yaml = _load_contract_from_db_sync(sub_id, sync_db_url) or getattr(s_mod, "CONTRACT_YAML", None)
            if not s_contract_yaml:
                continue
            sub_contract_yaml_by_id[sub_id] = s_contract_yaml
            s_plan = _build_task_plan(
                s_tools,
                s_contract_yaml,
                task_hints={
                    h["tool"]: h for h in _module_task_hints(s_mod)
                    if isinstance(h, dict) and isinstance(h.get("tool"), str)
                },
            )
            for s_task in s_plan:
                all_sub_tasks.append({**s_task, "sub_agent": sub_id})

        if not all_sub_tasks:
            raise HTTPException(status_code=422, detail=f"No runnable sub-agent tasks found for orchestrator '{agent_id}'")

        if mode == "step":
            # Round-robin through tasks by run count
            run_count_result = await db.execute(select(Run).where(Run.agent_id == agent_id))
            run_count = len(run_count_result.scalars().all())
            task_idx = run_count % len(all_sub_tasks)
            task = all_sub_tasks[task_idx]
            sub_id = task.get("sub_agent", sub_ids[0])

            orch_run_id = await loop.run_in_executor(
                None, _create_orchestrator_run_sync, contract_version_label, 1
            )
            _t0 = _time.time()
            step_result = await loop.run_in_executor(None, _exec_sub_task, task, sub_id, orch_run_id)
            _latency = int((_time.time() - _t0) * 1000)
            await loop.run_in_executor(
                None, _finalize_orchestrator_run_sync,
                orch_run_id,
                1 if step_result["blocked"] else 0,
                step_result["quality_score"],
                _latency,
            )
            await db.refresh(agent_row)
            trust_after = float(agent_row.trust_score)
            broadcast("run_completed", {"agent_id": agent_id, "blocked": step_result["blocked"]})

            return {
                "mode": "step",
                "orchestrator": True,
                "parent_run_id": orch_run_id,
                "sub_agent": sub_id,
                "task_index": task_idx,
                "next_task_index": (task_idx + 1) % len(all_sub_tasks),
                "total_tasks": len(all_sub_tasks),
                "task_description": task["description"],
                "tool": task["tool"],
                "output": step_result["output"][:600],
                "blocked": step_result["blocked"],
                "trust_before": round(trust_start, 4),
                "trust_after": round(trust_after, 4),
                "trust_delta": round(trust_after - trust_start, 4),
                "quality_score": step_result["quality_score"],
                "token_counts": {"input": 0, "output": 0},
                "cost_usd": 0.0,
                "note": "orchestrator mode — sub-agent tasks run as child runs",
            }

        # mode == "full" for orchestrator
        _t0_full = _time.time()
        orch_run_id = await loop.run_in_executor(
            None, _create_orchestrator_run_sync, contract_version_label, len(all_sub_tasks)
        )
        steps = []
        for i, task in enumerate(all_sub_tasks):
            sub_id = task.get("sub_agent", sub_ids[0])
            await db.refresh(agent_row)
            t_before = float(agent_row.trust_score)
            sub_result = await loop.run_in_executor(None, _exec_sub_task, task, sub_id, orch_run_id)
            await db.refresh(agent_row)
            t_after = float(agent_row.trust_score)
            steps.append({
                "task_index": i,
                "sub_agent": sub_id,
                "task_description": task["description"],
                "tool": task["tool"],
                "arg": task.get("arg"),
                "output": sub_result["output"][:400],
                "blocked": sub_result["blocked"],
                "quality_score": sub_result["quality_score"],
                "trust_before": round(t_before, 4),
                "trust_after": round(t_after, 4),
                "trust_delta": round(t_after - t_before, 4),
            })
            broadcast("run_completed", {"agent_id": sub_id, "blocked": sub_result["blocked"]})

        _latency_full = int((_time.time() - _t0_full) * 1000)
        n_viol = sum(1 for s in steps if s["blocked"])
        valid_q = [s["quality_score"] for s in steps if s["quality_score"] is not None]
        avg_q = round(sum(valid_q) / len(valid_q), 4) if valid_q else None
        await loop.run_in_executor(
            None, _finalize_orchestrator_run_sync, orch_run_id, n_viol, avg_q, _latency_full
        )
        await db.refresh(agent_row)
        broadcast("run_completed", {"agent_id": agent_id, "blocked": n_viol > 0})

        return {
            "mode": "full",
            "orchestrator": True,
            "parent_run_id": orch_run_id,
            "agent_id": agent_id,
            "subagents": sub_ids,
            "total_tasks": len(steps),
            "steps": steps,
            "trust_start": round(trust_start, 4),
            "trust_end": round(float(agent_row.trust_score), 4),
            "trust_delta": round(float(agent_row.trust_score) - trust_start, 4),
            "violations": n_viol,
            "note": "orchestrator mode — tool executions persisted as child runs",
        }

    # ── Helper: run one task synchronously (single-agent) ─────────────────────
    def _exec_one(task: dict) -> dict:
        out_buf: list[str] = [""]
        blk_buf: list[bool] = [False]
        quality_buf: list[float] = [0.0]
        from norma.integrations.session import NormaAgentSession
        from norma.core.quality_scorer import evaluate_quality_sync
        tool_map = {t.name: t for t in ALL_TOOLS}
        with NormaAgentSession(
            agent_id=agent_id,
            contract_yaml=CONTRACT_YAML,
            contract_version=contract_version_label,
            db_url=sync_db_url,
            initiated_by="api",
        ) as sess:
            wrapped = {t.name: t for t in sess.wrap_tools(list(tool_map.values()))}
            tool_name = task["tool"]
            if tool_name not in wrapped:
                out_buf[0] = f"Tool '{tool_name}' not found. Available: {list(wrapped)}"
            else:
                tool = wrapped[tool_name]
                arg = task.get("arg")
                try:
                    out = tool.run(arg or {}) if arg else tool.run({})
                except AgentPausedError:
                    raise
                except Exception as _e:
                    # Tool requires a specific argument we don't have (e.g. filename).
                    # Retry once with inferred payload from missing-field errors.
                    retry_arg = _arg_from_validation_error(
                        _e,
                        tool_name=tool_name,
                        agent_id=agent_id,
                        contract_yaml=CONTRACT_YAML,
                        all_tools=ALL_TOOLS,
                    )
                    if retry_arg is not None:
                        try:
                            out = tool.run(retry_arg)
                        except Exception as _e2:
                            out = f"[skipped — tool '{tool_name}' requires input: {_e2}]"
                    else:
                        # Record as a graceful skip rather than crashing the full run.
                        out = f"[skipped — tool '{tool_name}' requires input: {_e}]"
                out_buf[0] = str(out)

            blk_buf[0] = bool(sess._blocked)
            if blk_buf[0]:
                quality_buf[0] = 0.0
            else:
                # Score the actual output text — not a hardcoded expected_quality field
                quality_buf[0] = evaluate_quality_sync(
                    out_buf[0], task_description=task.get("description", "")
                ).score
            sess.record_quality(quality_buf[0])
        return {
            "output": out_buf[0],
            "blocked": blk_buf[0],
            "quality_score": 0.0 if blk_buf[0] else quality_buf[0],
        }

    loop = asyncio.get_event_loop()

    # ── FULL mode: run every task in sequence ──────────────────────────────────
    if mode == "full":
        steps = []
        for i, task in enumerate(TASK_PLAN):
            await db.refresh(agent_row)
            t_before = float(agent_row.trust_score)
            step_result = await loop.run_in_executor(None, _exec_one, task)
            await db.refresh(agent_row)
            t_after = float(agent_row.trust_score)
            steps.append({
                "task_index": i,
                "task_description": task["description"],
                "tool": task["tool"],
                "arg": task.get("arg"),
                "output": step_result["output"][:400],
                "blocked": step_result["blocked"],
                "quality_score": step_result["quality_score"],
                "trust_before": round(t_before, 4),
                "trust_after": round(t_after, 4),
                "trust_delta": round(t_after - t_before, 4),
            })
            broadcast("run_completed", {"agent_id": agent_id, "blocked": step_result["blocked"]})

        await db.refresh(agent_row)
        return {
            "mode": "full",
            "agent_id": agent_id,
            "total_tasks": len(steps),
            "steps": steps,
            "trust_start": round(trust_start, 4),
            "trust_end": round(float(agent_row.trust_score), 4),
            "trust_delta": round(float(agent_row.trust_score) - trust_start, 4),
            "violations": sum(1 for s in steps if s["blocked"]),
            "note": "full mode — ran all contract-allowed runnable tasks",
        }

    # ── STEP mode: run one task cycling by run count ───────────────────────────
    run_count_result = await db.execute(select(Run).where(Run.agent_id == agent_id))
    run_count = len(run_count_result.scalars().all())
    task_idx = run_count % len(TASK_PLAN)
    task = TASK_PLAN[task_idx]

    step_result = await loop.run_in_executor(None, _exec_one, task)
    await db.refresh(agent_row)
    trust_after = float(agent_row.trust_score)

    broadcast("run_completed", {"agent_id": agent_id, "blocked": step_result["blocked"]})

    return {
        "mode": "step",
        "agent_id": agent_id,
        "task_index": task_idx,
        "next_task_index": (task_idx + 1) % len(TASK_PLAN),
        "total_tasks": len(TASK_PLAN),
        "task_description": task["description"],
        "tool": task["tool"],
        "output": step_result["output"][:600],
        "blocked": step_result["blocked"],
        "completion_status": "failed" if step_result["blocked"] else "success",
        "trust_before": round(trust_start, 4),
        "trust_after": round(trust_after, 4),
        "trust_delta": round(trust_after - trust_start, 4),
        "quality_score": step_result["quality_score"],
        "token_counts": {"input": 0, "output": 0},
        "cost_usd": 0.0,
        "note": "step mode — ran one contract-allowed task; token counts and cost are 0 when no LLM spans are present",
    }


@router.post("/{agent_id}/replay")
async def replay_agent_run(
    agent_id: str,
    source_run_id: int | None = Query(None, description="Optional source run to replay from"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-execute the agent's full runnable task plan using the current contract.

    This is the customer-facing replay path for regression checks after contract
    updates. It always replays full mode and persists new runs.
    """
    source_run: Run | None = None
    if source_run_id is not None:
        source_result = await db.execute(select(Run).where(Run.id == source_run_id))
        source_run = source_result.scalar_one_or_none()
        if source_run is None:
            raise HTTPException(status_code=404, detail=f"Run {source_run_id} not found")
        if source_run.agent_id != agent_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Run {source_run_id} belongs to '{source_run.agent_id}', not '{agent_id}'"
                ),
            )

    before_result = await db.execute(select(Run.id).where(Run.agent_id == agent_id).order_by(Run.id.desc()))
    before_ids = [row[0] for row in before_result.all()]
    before_max = before_ids[0] if before_ids else 0

    execution = await execute_agent_task(
        agent_id=agent_id,
        mode="full",
        body=None,
        db=db,
    )

    after_result = await db.execute(
        select(Run.id)
        .where(Run.agent_id == agent_id, Run.id > before_max)
        .order_by(Run.id.asc())
    )
    new_run_ids = [row[0] for row in after_result.all()]

    return {
        "agent_id": agent_id,
        "replayed": True,
        "source_run_id": source_run_id,
        "source_contract_version": source_run.contract_version if source_run else None,
        "replay_mode": "full",
        "created_runs": len(new_run_ids),
        "created_run_ids": new_run_ids,
        "execution": execution,
    }


# ── Pause / Resume ────────────────────────────────────────────────────────────


@router.patch("/{agent_id}/pause")
async def pause_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pause an agent — blocks all new runs until resumed."""
    result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.enabled = False
    await db.commit()

    try:
        from norma.api.events import broadcast
        broadcast("agent_paused", {"agent_id": agent_id, "enabled": False})
    except Exception:
        pass

    return {"agent_id": agent_id, "enabled": False, "status": "paused"}


@router.patch("/{agent_id}/resume")
async def resume_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Resume a paused agent — allows new runs again."""
    result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.enabled = True
    await db.commit()

    try:
        from norma.api.events import broadcast
        broadcast("agent_resumed", {"agent_id": agent_id, "enabled": True})
    except Exception:
        pass

    return {"agent_id": agent_id, "enabled": True, "status": "resumed"}
