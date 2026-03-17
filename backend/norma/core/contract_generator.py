"""Contract Auto-Generator — drafts a norma contract from agent configuration.

Design principles (from design.md §1.3):
  - LLM output is always a PROPOSAL, never an auto-activated policy
  - Output labels what was inferred, assumed, and still requires human review
  - Human approval step is mandatory before enforcement activates

Two modes:
  1. With OPENAI_API_KEY: real LLM call produces a context-aware contract
  2. Without key:         conservative stub contract generated deterministically
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from norma.config import get_settings

settings = get_settings()

_SYSTEM_PROMPT = """\
You are a contract generation assistant for norma.ai, an AI agent governance platform.
Given an agent configuration (tools, description, system prompt), produce a YAML contract.

The contract must include:
- agent_id:         (use the provided agent_id)
- version:          "1.0"
- tier:             "restricted"  (always start restricted — humans promote)
- scope:            description + allowed_tasks (infer from description)
- authorities.tools.allow:   list of tool names provided
- authorities.tools.deny:    any tools that seem dangerous (external_api, email_sender, etc.)
- authorities.data.allow:    ["**"] unless specific paths are mentioned; be conservative
- authorities.data.deny:     paths that seem sensitive (confidential/**, payment_info/**, etc.)
- output_constraints.deny_patterns: always include ["pii_regex", "credential_regex"]
- sla.max_cost_per_run:       $5.00 default
- sla.max_latency_seconds:    60 default
- sla.min_quality_score:      0.75 default
- trust.initial_score:        0.40
- trust.violation_penalty:    0.25
- trust.clean_run_increment:  0.025
- trust.tier_thresholds:      standard: {min_score: 0.65, min_clean_runs: 10}
                               trusted:  {min_score: 0.82, min_clean_runs: 20}

After the YAML, add ONE blank line, then a JSON object under the key __meta__ containing:
  inferred:        list of strings — fields you inferred from the description
  assumed:         list of strings — fields you set to defaults (state what default)
  requires_input:  list of strings — fields that MUST be reviewed by a human

Return ONLY the YAML document followed by the __meta__ JSON. No markdown fences.
Example __meta__ line (at end, after YAML):
__meta__: {"inferred": ["scope.allowed_tasks"], "assumed": ["sla.max_cost_per_run=$5.00"], "requires_input": ["authorities.data.deny"]}
"""


def _infer_allowed_tasks(description: str, tools: list[str]) -> list[str]:
    text = (description or "").lower()
    inferred: list[str] = []
    if any(k in text for k in ("research", "search", "analysis", "synth")):
        inferred.extend(["research_search", "document_synthesis", "trend_analysis"])
    if any(k in text for k in ("financial", "earnings", "report")):
        inferred.extend(["report_read", "financial_summary"])
    if any(k in text for k in ("support", "ticket", "triage")):
        inferred.extend(["ticket_triage", "kb_lookup"])

    if not inferred:
        inferred = ["agent_execution"]

    tool_tasks = [f"tool:{t}" for t in tools[:8]]
    return list(dict.fromkeys(inferred + tool_tasks))


def _infer_data_authorities(description: str, data_hints: list[str]) -> tuple[list[str], list[str]]:
    hints = [h.strip() for h in data_hints if isinstance(h, str) and h.strip()]
    allow: list[str] = []
    deny: list[str] = []

    for hint in hints:
        lowered = hint.lower()
        if any(k in lowered for k in ("confidential", "internal", "secret", "credential", "payment")):
            deny.append(hint)
        else:
            allow.append(hint)

    if not allow:
        text = (description or "").lower()
        if "research" in text:
            allow = ["data/research/**"]
        elif any(k in text for k in ("financial", "earnings", "report")):
            allow = ["data/public/**", "reports/public/**"]
        elif any(k in text for k in ("support", "ticket", "kb")):
            allow = ["data/support/**"]
        else:
            allow = ["data/public/**"]

    if not deny:
        deny = ["data/confidential/**", "data/internal/**"]

    return list(dict.fromkeys(allow)), list(dict.fromkeys(deny))


def _normalize_contract_doc(
    parsed: dict[str, Any],
    *,
    agent_id: str,
    agent_config: dict[str, Any],
) -> dict[str, Any]:
    description = str(agent_config.get("description") or agent_id)
    tools = [str(t) for t in (agent_config.get("tools") or []) if str(t).strip()]
    data_hints = [str(p) for p in (agent_config.get("data_hints") or [])]

    parsed["agent_id"] = agent_id
    parsed["version"] = str(parsed.get("version") or "1.0")
    parsed["tier"] = str(parsed.get("tier") or "restricted")

    scope = parsed.get("scope")
    if isinstance(scope, dict):
        scope_desc = str(scope.get("description") or description)
        allowed_tasks = scope.get("allowed_tasks")
        if not isinstance(allowed_tasks, list) or not allowed_tasks:
            allowed_tasks = _infer_allowed_tasks(scope_desc, tools)
        parsed["scope"] = {
            "description": scope_desc,
            "allowed_tasks": [str(t) for t in allowed_tasks],
        }
    else:
        scope_desc = str(scope).strip() if isinstance(scope, str) else description
        parsed["scope"] = {
            "description": scope_desc or description,
            "allowed_tasks": _infer_allowed_tasks(scope_desc or description, tools),
        }

    authorities = parsed.get("authorities")
    if not isinstance(authorities, dict):
        authorities = {}

    tools_auth = authorities.get("tools")
    if not isinstance(tools_auth, dict):
        tools_auth = {}
    allow_tools = tools_auth.get("allow")
    deny_tools = tools_auth.get("deny")
    if not isinstance(allow_tools, list):
        allow_tools = []
    if not isinstance(deny_tools, list):
        deny_tools = []
    if not allow_tools and tools:
        allow_tools = tools
    tools_auth["allow"] = list(dict.fromkeys([str(t) for t in allow_tools]))
    tools_auth["deny"] = list(dict.fromkeys([str(t) for t in deny_tools]))

    data_auth = authorities.get("data")
    if not isinstance(data_auth, dict):
        data_auth = {}
    allow_data = data_auth.get("allow")
    deny_data = data_auth.get("deny")
    if not isinstance(allow_data, list):
        allow_data = []
    if not isinstance(deny_data, list):
        deny_data = []
    inferred_allow, inferred_deny = _infer_data_authorities(description, data_hints)
    if not allow_data:
        allow_data = inferred_allow
    if not deny_data:
        deny_data = inferred_deny
    data_auth["allow"] = list(dict.fromkeys([str(p) for p in allow_data]))
    data_auth["deny"] = list(dict.fromkeys([str(p) for p in deny_data]))

    authorities["tools"] = tools_auth
    authorities["data"] = data_auth
    parsed["authorities"] = authorities

    output_constraints = parsed.get("output_constraints")
    if not isinstance(output_constraints, dict):
        output_constraints = {}
    deny_patterns = output_constraints.get("deny_patterns")
    if not isinstance(deny_patterns, list) or not deny_patterns:
        deny_patterns = ["pii_regex", "credential_regex"]
    output_constraints["deny_patterns"] = [str(p) for p in deny_patterns]
    parsed["output_constraints"] = output_constraints

    return parsed


async def generate_contract_proposal(
    agent_config: dict[str, Any],
    agent_id: str,
) -> dict[str, Any]:
    """
    Generate a contract proposal from agent configuration.

    Returns:
        yaml_content:        str — the proposed YAML (never activates until approved)
        meta.inferred:       list — fields the LLM inferred from the description
        meta.assumed:        list — defaults applied
        meta.requires_input: list — fields needing human review before activation
        validation_errors:   list — any schema problems detected
        source:              "llm" | "stub"
    """
    if settings.openai_api_key:
        return await _generate_with_llm(agent_config, agent_id)
    return _generate_stub(agent_config, agent_id)


async def _generate_with_llm(
    agent_config: dict[str, Any],
    agent_id: str,
) -> dict[str, Any]:
    """Call OpenAI to draft the contract."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    user_content = (
        f"agent_id: {agent_id}\n"
        f"description: {agent_config.get('description', agent_id)}\n"
        f"tools: {agent_config.get('tools', [])}\n"
    )
    if agent_config.get("system_prompt"):
        user_content += f"system_prompt: |\n  {agent_config['system_prompt'][:800]}\n"

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_content},
        ],
        temperature=0.2,
        max_tokens=1200,
    )

    raw = response.choices[0].message.content or ""
    return _parse_llm_output(raw, agent_id, agent_config)


def _parse_llm_output(
    raw: str,
    agent_id: str,
    agent_config: dict[str, Any],
) -> dict[str, Any]:
    """Extract YAML + __meta__ from raw LLM output. Falls back to stub on error."""
    import json

    meta: dict[str, Any] = {"inferred": [], "assumed": [], "requires_input": []}
    yaml_text = raw

    # Extract __meta__ line if present
    meta_match = re.search(r"^__meta__:\s*(\{.+\})\s*$", raw, re.MULTILINE)
    if meta_match:
        try:
            meta = json.loads(meta_match.group(1))
        except json.JSONDecodeError:
            pass
        yaml_text = raw[: meta_match.start()].strip()

    # Validate the YAML parses
    try:
        parsed = yaml.safe_load(yaml_text)
        if not isinstance(parsed, dict):
            raise ValueError("Not a dict")
        parsed = _normalize_contract_doc(
            parsed,
            agent_id=agent_id,
            agent_config=agent_config,
        )
        yaml_text = yaml.dump(parsed, default_flow_style=False)
        errors: list[str] = []
    except Exception as exc:
        # LLM gave malformed YAML — fall back silently
        result = _generate_stub(agent_config, agent_id)
        result["validation_errors"] = [f"LLM output invalid: {exc}; fell back to stub"]
        return result

    return {
        "yaml_content": yaml_text,
        "meta": meta,
        "validation_errors": errors,
        "source": "llm",
    }


def _generate_stub(
    agent_config: dict[str, Any],
    agent_id: str,
) -> dict[str, Any]:
    """
    Conservative stub contract — generated deterministically without an LLM.
    Every field is set to a safe default. Human must fill in deny lists.
    """
    tools: list[str] = agent_config.get("tools", [])
    description: str = agent_config.get("description", agent_id)
    data_hints: list[str] = [str(p) for p in (agent_config.get("data_hints") or [])]

    # Heuristic: deny tools that look dangerous
    dangerous_keywords = [
        "email",
        "send",
        "delete",
        "write",
        "external",
        "payment",
        "billing",
        "confidential",
        "secret",
        "internal",
    ]
    auto_deny = [t for t in tools if any(k in t.lower() for k in dangerous_keywords)]
    auto_allow = tools
    data_allow, data_deny = _infer_data_authorities(description, data_hints)

    contract = {
        "agent_id": agent_id,
        "version": "1.0",
        "tier": "restricted",
        "_generated_by": "norma auto-contract (stub — no LLM key present)",
        "_enforcement": "DISABLED until a human approves via norma dashboard",
        "scope": {
            "description": description,
            "allowed_tasks": _infer_allowed_tasks(description, tools),
        },
        "authorities": {
            "tools": {
                "allow": auto_allow,
                "deny":  auto_deny,
            },
            "data": {
                "allow": data_allow,
                "deny":  data_deny,
            },
        },
        "output_constraints": {
            "deny_patterns": ["pii_regex", "credential_regex", "credit_card_regex"],
        },
        "sla": {
            "max_cost_per_run": 5.00,
            "max_latency_seconds": 60,
            "min_quality_score": 0.70,
        },
        "trust": {
            "initial_score": 0.40,
            "violation_penalty": 0.25,
            "clean_run_increment": 0.025,
            "tier_thresholds": {
                "standard": {"min_score": 0.65, "min_clean_runs": 10},
                "trusted":  {"min_score": 0.82, "min_clean_runs": 20},
            },
        },
    }

    return {
        "yaml_content": yaml.dump(contract, default_flow_style=False),
        "meta": {
            "inferred": ["authorities.tools.allow (from tool list)"],
            "assumed": [
                "sla.max_cost_per_run=$5.00",
                "sla.max_latency_seconds=60",
                "trust.initial_score=0.40",
            ],
            "requires_input": [
                "authorities.data.deny",
                "sla.min_quality_score",
            ],
        },
        "validation_errors": [],
        "source": "stub",
    }


# ── norma-generate CLI ─────────────────────────────────────────────────────────

import pathlib as _pathlib  # noqa: E402

import click as _click  # noqa: E402


@_click.command()
@_click.option("--agent-id", required=True, help="Agent ID to generate a contract for.")
@_click.option("--tools", default="", help="Comma-separated list of tool names.")
@_click.option("--description", default="", help="Short description of what the agent does.")
@_click.option("--out", default=None, help="Write YAML to this file (stdout if omitted).")
def generate_cmd(agent_id: str, tools: str, description: str, out: str | None) -> None:
    """Auto-generate a norma contract proposal for an agent."""
    import asyncio as _asyncio

    agent_config: dict[str, Any] = {
        "agent_id": agent_id,
        "description": description or f"Auto-generated contract for {agent_id}",
        "tools": [t.strip() for t in tools.split(",") if t.strip()],
    }

    _click.echo(f"  Generating contract for agent '{agent_id}'...")
    result = _asyncio.run(generate_contract_proposal(agent_config, agent_id))
    source = result.get("source", "stub")
    meta   = result.get("meta", {})
    yaml_content: str = result.get("yaml_content", "")

    _click.echo(f"  Source  : {source}")
    if meta.get("requires_input"):
        _click.echo(f"  Warning : human review needed for {meta['requires_input']}")

    if out:
        _pathlib.Path(out).write_text(yaml_content)
        _click.echo(f"  Written : {out}")
    else:
        _click.echo()
        _click.echo(yaml_content)
