"""Contract engine — parse, validate, and version YAML agent contracts."""

from __future__ import annotations

import json
from typing import Any

import yaml
from jsonschema import ValidationError, validate

# JSON Schema for contract YAML validation (Phase 1)
CONTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["agent_id", "version", "scope", "authorities", "sla"],
    "properties": {
        "agent_id": {"type": "string"},
        "version": {"type": "string"},
        "tier": {"type": "string", "enum": ["restricted", "standard", "trusted"]},
        "scope": {
            "type": "object",
            "required": ["description"],
            "properties": {
                "description": {"type": "string"},
                "allowed_tasks": {"type": "array", "items": {"type": "string"}},
            },
        },
        "authorities": {
            "type": "object",
            "properties": {
                "tools": {
                    "type": "object",
                    "properties": {
                        "allow": {"type": "array", "items": {"type": "string"}},
                        "deny":  {"type": "array", "items": {"type": "string"}},
                    },
                },
                "data": {
                    "type": "object",
                    "properties": {
                        "allow": {"type": "array", "items": {"type": "string"}},
                        "deny":  {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
        "sla": {
            "type": "object",
            "properties": {
                "max_cost_per_run": {"type": "number"},
                "max_latency_seconds": {"type": "number"},
                "min_quality_score": {"type": "number"},
            },
        },
        "trust": {
            "type": "object",
            "properties": {
                "initial_score": {"type": "number"},
                "tier_thresholds": {"type": "object"},
                "violation_penalty": {"type": "number"},
                "clean_run_increment": {"type": "number"},
            },
        },
        "delegation": {"type": "object"},
        "output_constraints": {"type": "object"},
        "escalation": {"type": "object"},
    },
    "additionalProperties": True,
}


def parse_contract(yaml_content: str) -> dict[str, Any]:
    """Parse contract YAML and return dict. Raises ValueError on bad YAML."""
    try:
        return yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc


def validate_contract(contract: dict[str, Any]) -> list[str]:
    """
    Validate contract against schema.
    Returns list of error messages (empty = valid).
    """
    errors: list[str] = []
    try:
        validate(instance=contract, schema=CONTRACT_SCHEMA)
    except ValidationError as exc:
        errors.append(exc.message)
    return errors


def diff_contracts(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """
    Return a structured diff between two contract dicts.
    Used for version comparison and audit export.
    """
    # TODO Phase 1: implement recursive diff
    return {"added": {}, "removed": {}, "changed": {}}


def contract_diff_json(old_yaml: str, new_yaml: str) -> str:
    """Parse both YAML strings and return JSON-serialised diff."""
    old = parse_contract(old_yaml)
    new = parse_contract(new_yaml)
    return json.dumps(diff_contracts(old, new))


def contract_summary_from_yaml(yaml_content: str) -> str:
    """Derive a plain-English human-readable summary from a contract YAML string.

    Handles both the nested schema (authorities.tools / authorities.data) and the
    flat schema (tools.allow / data.allow) used by agent module files.
    """
    try:
        c = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError:
        return "Contract (could not parse YAML for summary)."

    tier = c.get("tier", "restricted")
    agent_id = c.get("agent_id", "this agent")
    raw_scope = c.get("scope")
    if isinstance(raw_scope, dict):
        scope = raw_scope
    else:
        scope = {}

    if isinstance(raw_scope, str) and raw_scope.strip():
        description = raw_scope.strip()
    else:
        description = scope.get("description") or c.get("description", "")

    # Support both nested (authorities.tools) and flat (tools) schemas
    authorities = c.get("authorities") or {}
    tools_block = authorities.get("tools") or c.get("tools") or {}
    data_block = authorities.get("data") or c.get("data") or {}

    tools_allow: list[str] = tools_block.get("allow") or []
    tools_deny: list[str] = tools_block.get("deny") or []
    data_allow: list[str] = data_block.get("allow") or []
    data_deny: list[str] = data_block.get("deny") or []

    sla = c.get("sla") or {}
    max_cost = sla.get("max_cost_per_run")
    min_quality = sla.get("min_quality_score")

    trust_block = c.get("trust") or {}
    thresholds = trust_block.get("tier_thresholds") or {}

    parts: list[str] = []

    intro = f"This contract governs {agent_id} at the {tier} tier."
    if description:
        intro = description.rstrip(".") + f". Tier: {tier}."
    parts.append(intro)

    if tools_allow:
        parts.append(f"Permitted tools: {', '.join(tools_allow)}.")
    else:
        parts.append("No tools are explicitly permitted.")

    if tools_deny:
        parts.append(f"Blocked tools: {', '.join(tools_deny)}.")

    if data_allow:
        parts.append(f"Data access allowed: {', '.join(data_allow)}.")

    if data_deny:
        parts.append(f"Data access denied: {', '.join(data_deny)}.")

    if max_cost is not None:
        parts.append(f"Max cost per run: ${max_cost:.2f}.")

    if min_quality is not None:
        parts.append(f"Minimum quality threshold: {int(min_quality * 100)}%.")

    if thresholds:
        promotion_notes = []
        for t_name, t_val in thresholds.items():
            if isinstance(t_val, dict):
                score = t_val.get("min_score")
                runs = t_val.get("min_clean_runs")
                if score and runs:
                    promotion_notes.append(
                        f"{t_name} tier requires trust \u2265 {score} and {runs} clean runs"
                    )
        if promotion_notes:
            parts.append("Tier promotion criteria: " + "; ".join(promotion_notes) + ".")

    return " ".join(parts)
