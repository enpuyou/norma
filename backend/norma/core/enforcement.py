"""Runtime Enforcement — deterministic contract enforcement middleware.

Two layers (from design doc):
  1. Deterministic (Phase 2): tool access, data path, output pattern matching, cost/latency
  2. Semantic (Phase 2+, feature-flagged): LLM-powered scope check

Enforcement happens BEFORE execution, not logged after the fact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any


# ─── PII / credential output patterns ─────────────────────────────────────────
DENY_PATTERNS: dict[str, re.Pattern[str]] = {
    "credit_card_regex": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "ssn_regex":         re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b"),
    "pii_regex":         re.compile(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b"),   # naive name pattern
    "credential_regex":  re.compile(r"(?i)(password|api_key|secret|token)\s*[:=]\s*\S+"),
}


@dataclass
class EnforcementResult:
    allowed: bool
    blocked: bool = False
    policy_rule: str = ""
    action_attempted: str = ""
    event_type: str = "access_allowed"


@dataclass
class ExecutionContext:
    agent_id: str
    tool_requested: str | None = None
    data_path_requested: str | None = None
    output_text: str | None = None
    cost_so_far_usd: float = 0.0
    latency_so_far_ms: int = 0
    contract: dict[str, Any] = field(default_factory=dict)


def enforce(ctx: ExecutionContext) -> EnforcementResult:
    """
    Run all deterministic enforcement checks.
    Returns the first violation if any; otherwise returns allowed=True.
    """
    checks = [
        _check_tool_access,
        _check_data_path,
        _check_output_patterns,
        _check_cost_sla,
        _check_latency_sla,
    ]
    for check in checks:
        result = check(ctx)
        if result.blocked:
            return result
    return EnforcementResult(allowed=True)


def _check_tool_access(ctx: ExecutionContext) -> EnforcementResult:
    if ctx.tool_requested is None:
        return EnforcementResult(allowed=True)
    authorities = ctx.contract.get("authorities", {}).get("tools", {})
    deny_list: list[str] = authorities.get("deny", [])
    allow_list: list[str] = authorities.get("allow", [])

    if ctx.tool_requested in deny_list:
        return EnforcementResult(
            allowed=False, blocked=True,
            policy_rule=f"tools.deny: {ctx.tool_requested}",
            action_attempted=f"tool:{ctx.tool_requested}",
            event_type="access_blocked",
        )
    if allow_list and ctx.tool_requested not in allow_list:
        return EnforcementResult(
            allowed=False, blocked=True,
            policy_rule=f"tools.allow does not include {ctx.tool_requested}",
            action_attempted=f"tool:{ctx.tool_requested}",
            event_type="access_blocked",
        )
    return EnforcementResult(allowed=True)


def _check_data_path(ctx: ExecutionContext) -> EnforcementResult:
    if ctx.data_path_requested is None:
        return EnforcementResult(allowed=True)
    data_rules = ctx.contract.get("authorities", {}).get("data", {})
    deny_patterns: list[str] = data_rules.get("deny", [])

    for pattern in deny_patterns:
        if fnmatch(ctx.data_path_requested, pattern):
            return EnforcementResult(
                allowed=False, blocked=True,
                policy_rule=f"data.deny: {pattern}",
                action_attempted=f"GET {ctx.data_path_requested}",
                event_type="access_blocked",
            )
    return EnforcementResult(allowed=True)


def _check_output_patterns(ctx: ExecutionContext) -> EnforcementResult:
    if ctx.output_text is None:
        return EnforcementResult(allowed=True)
    deny = ctx.contract.get("output_constraints", {}).get("deny_patterns", [])
    for pattern_name in deny:
        regex = DENY_PATTERNS.get(pattern_name)
        if regex and regex.search(ctx.output_text):
            return EnforcementResult(
                allowed=False, blocked=True,
                policy_rule=f"output_constraints.deny_patterns: {pattern_name}",
                action_attempted=f"output contains {pattern_name}",
                event_type="output_blocked",
            )
    return EnforcementResult(allowed=True)


def _check_cost_sla(ctx: ExecutionContext) -> EnforcementResult:
    limit = ctx.contract.get("sla", {}).get("max_cost_per_run")
    if limit and ctx.cost_so_far_usd > limit:
        return EnforcementResult(
            allowed=False, blocked=True,
            policy_rule=f"sla.max_cost_per_run: {limit}",
            action_attempted=f"cost ${ctx.cost_so_far_usd:.4f}",
            event_type="sla_breach",
        )
    return EnforcementResult(allowed=True)


def _check_latency_sla(ctx: ExecutionContext) -> EnforcementResult:
    limit_s = ctx.contract.get("sla", {}).get("max_latency_seconds")
    if limit_s and ctx.latency_so_far_ms > limit_s * 1000:
        return EnforcementResult(
            allowed=False, blocked=True,
            policy_rule=f"sla.max_latency_seconds: {limit_s}",
            action_attempted=f"latency {ctx.latency_so_far_ms}ms",
            event_type="sla_breach",
        )
    return EnforcementResult(allowed=True)


def contains_credit_card_pattern(text: str) -> bool:
    """Convenience helper used in tests."""
    return bool(DENY_PATTERNS["credit_card_regex"].search(text))
