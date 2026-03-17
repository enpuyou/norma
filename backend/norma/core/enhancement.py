"""Enhancement engine — data-driven workflow improvements from runs, spans, and violations."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from typing import Any

import yaml


def _to_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _confidence(sample_n: int) -> str:
    if sample_n >= 8:
        return "high"
    if sample_n >= 4:
        return "medium"
    return "low"


def _priority(confidence: str) -> str:
    if confidence == "high":
        return "high"
    if confidence == "medium":
        return "medium"
    return "low"


def _recommend_token_waste(spans: list[Any]) -> dict[str, Any] | None:
    llm_spans = [s for s in spans if getattr(s, "span_type", "") == "llm_call"]
    wasteful = [
        s for s in llm_spans
        if (getattr(s, "tokens_in", 0) or 0) >= 600
        and (getattr(s, "tokens_out", 0) or 0) <= (getattr(s, "tokens_in", 0) or 0) * 0.15
    ]
    if not wasteful:
        return None

    wasteful = sorted(
        wasteful,
        key=lambda s: ((getattr(s, "tokens_out", 0) or 0) / max((getattr(s, "tokens_in", 1) or 1), 1), -(getattr(s, "tokens_in", 0) or 0)),
    )
    top = wasteful[:3]
    refs = [
        f"span:{s.span_id} in={s.tokens_in or 0} out={s.tokens_out or 0}"
        for s in top
    ]
    confidence = _confidence(len(wasteful))
    return {
        "id": "token_waste",
        "type": "token_waste",
        "title": "Reduce prompt token waste",
        "priority": _priority(confidence),
        "confidence": confidence,
        "evidence": (
            f"Detected {len(wasteful)} LLM calls with high input/low output token ratio. "
            f"Examples: {'; '.join(refs)}"
        ),
        "action": "apply_contract_rule",
        "yaml_snippet": (
            "routing:\n"
            "  enforce_context_budget: true\n"
            "  compression_required_over_tokens: 600\n"
            "  max_context_utilization_ratio: 0.70"
        ),
        "span_ids": [s.span_id for s in top],
    }


def _recommend_violation_pattern(violations: list[Any]) -> dict[str, Any] | None:
    if not violations:
        return None
    by_rule = Counter((getattr(v, "policy_rule", "unknown") or "unknown") for v in violations)
    rule, count = by_rule.most_common(1)[0]
    if count < 2:
        return None

    sample = next((v for v in violations if (getattr(v, "policy_rule", "") or "") == rule), None)
    action_attempted = getattr(sample, "action_attempted", "") if sample else ""
    snippet_path = "reports/confidential/**"
    if isinstance(action_attempted, str) and "/" in action_attempted:
        tokens = action_attempted.split()
        candidate = next((t for t in tokens if "/" in t), None)
        if candidate:
            snippet_path = candidate.strip().strip("'\".,;")
            if not snippet_path.endswith("**"):
                snippet_path = snippet_path.rstrip("/") + "/**"

    confidence = _confidence(count)
    return {
        "id": "violation_pattern",
        "type": "violation_pattern",
        "title": "Harden repeated violation pattern",
        "priority": "high",
        "confidence": confidence,
        "evidence": f"Rule '{rule}' triggered {count} times across recent runs.",
        "action": "apply_contract_rule",
        "yaml_snippet": f"enforcement:\n  deny:\n  - {snippet_path}",
        "span_ids": [],
    }


def _recommend_cost_hotspot(spans: list[Any]) -> dict[str, Any] | None:
    cost_spans = [s for s in spans if (getattr(s, "cost_usd", 0.0) or 0.0) > 0]
    if len(cost_spans) < 3:
        return None

    total_cost = sum((s.cost_usd or 0.0) for s in cost_spans)
    if total_cost <= 0:
        return None

    by_name: dict[str, float] = defaultdict(float)
    sample_span: dict[str, Any] = {}
    for span in cost_spans:
        name = getattr(span, "name", "unknown") or "unknown"
        by_name[name] += span.cost_usd or 0.0
        sample_span.setdefault(name, span)

    hot_name, hot_cost = max(by_name.items(), key=lambda x: x[1])
    share = hot_cost / total_cost
    if share < 0.35:
        return None

    confidence = _confidence(len(cost_spans))
    span = sample_span[hot_name]
    return {
        "id": "cost_hotspot",
        "type": "cost_hotspot",
        "title": "Cap dominant cost hotspot",
        "priority": _priority(confidence),
        "confidence": confidence,
        "evidence": (
            f"Step '{hot_name}' accounts for {share * 100:.1f}% of span-attributed cost "
            f"(${hot_cost:.5f} of ${total_cost:.5f})."
        ),
        "action": "apply_contract_rule",
        "yaml_snippet": (
            "sla:\n"
            "  max_cost_per_run: 0.10\n"
            "limits:\n"
            "  max_llm_calls_per_run: 8"
        ),
        "span_ids": [getattr(span, "span_id", "")],
    }


def _recommend_quality_bottleneck(runs: list[Any], spans: list[Any]) -> dict[str, Any] | None:
    low_quality_runs = [r for r in runs if (getattr(r, "quality_score", None) or 0.0) < 0.75]
    if not low_quality_runs:
        return None

    run_ids = {r.id for r in low_quality_runs if getattr(r, "id", None) is not None}
    related = [s for s in spans if getattr(s, "trace_id", None) in run_ids]
    if not related:
        return None

    bottleneck = [s for s in related if (getattr(s, "status", "") or "") in {"blocked", "error"}]
    if not bottleneck:
        bottleneck = sorted(related, key=lambda s: getattr(s, "latency_ms", 0) or 0, reverse=True)[:3]

    if not bottleneck:
        return None

    top = bottleneck[:3]
    names = Counter((getattr(s, "name", "unknown") or "unknown") for s in top)
    primary_name, primary_count = names.most_common(1)[0]
    quality_values = [r.quality_score for r in low_quality_runs if getattr(r, "quality_score", None) is not None]
    avg_q = statistics.mean(quality_values) if quality_values else 0.0
    confidence = _confidence(len(low_quality_runs))
    return {
        "id": "quality_bottleneck",
        "type": "quality_bottleneck",
        "title": "Stabilize quality bottleneck step",
        "priority": _priority(confidence),
        "confidence": confidence,
        "evidence": (
            f"Average quality across impacted runs is {avg_q:.3f}. "
            f"Bottleneck step '{primary_name}' appears in {primary_count} of top failing spans."
        ),
        "action": "review_prompt_and_contract",
        "yaml_snippet": (
            "quality:\n"
            "  require_min_score: 0.80\n"
            "governance:\n"
            "  require_approval_for:\n"
            "  - low_confidence_outputs"
        ),
        "span_ids": [s.span_id for s in top],
    }


def generate_enhancements(*, runs: list[Any], spans: list[Any], violations: list[Any]) -> list[dict[str, Any]]:
    """Generate a ranked set of enhancement recommendations from telemetry."""
    recommendations: list[dict[str, Any]] = []

    for rec in (
        _recommend_token_waste(spans),
        _recommend_violation_pattern(violations),
        _recommend_cost_hotspot(spans),
        _recommend_quality_bottleneck(runs, spans),
    ):
        if rec:
            recommendations.append(rec)

    rank = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda r: rank.get(r.get("priority", "low"), 9))
    return recommendations


def _merge_values(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        out = dict(base)
        for key, value in patch.items():
            if key in out:
                out[key] = _merge_values(out[key], value)
            else:
                out[key] = value
        return out
    if isinstance(base, list) and isinstance(patch, list):
        merged = list(base)
        for item in patch:
            if item not in merged:
                merged.append(item)
        return merged
    return patch


def apply_yaml_snippet(contract_yaml: str, yaml_snippet: str) -> str:
    """Apply an enhancement YAML snippet onto an existing contract YAML document."""
    base_obj = yaml.safe_load(contract_yaml) or {}
    patch_obj = yaml.safe_load(yaml_snippet) or {}
    if not isinstance(base_obj, dict) or not isinstance(patch_obj, dict):
        return contract_yaml

    merged = _merge_values(base_obj, patch_obj)
    return yaml.safe_dump(merged, sort_keys=False)
