"""Contracts API — versioning, auto-generation, approval workflow.

Design constraint: never auto-activate a contract.
Proposals only; human approval required (design.md §1.3).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import selectinload

from norma.core.contract_generator import generate_contract_proposal
from norma.core.contract_engine import contract_summary_from_yaml
from norma.database import get_db
from norma.models.agent import Agent
from norma.models.contract import Contract, ContractVersion

router = APIRouter()


def _contract_to_dict(c: Contract) -> dict:
    state = sa_inspect(c)
    versions_loaded = "versions" not in state.unloaded
    versions = c.versions if versions_loaded else []

    return {
        "id": c.id,
        "agent_id": c.agent_id,
        "version": c.version,
        "yaml_content": c.yaml_content,
        "summary_text": c.summary_text,
        "is_active": c.is_active,
        "created_by": c.created_by,
        "approved_by": c.approved_by,
        "activated_at": c.activated_at.isoformat() if c.activated_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "versions": [
            {
                "id": v.id,
                "diff_json": v.diff_json,
                "changed_by": v.changed_by,
                "approved_by": v.approved_by,
                "reason": v.reason,
                "timestamp": v.timestamp.isoformat() if v.timestamp else None,
            }
            for v in versions
        ],
    }


@router.get("/{agent_id}")
async def list_contracts(agent_id: str, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Return contract version history for an agent."""
    result = await db.execute(
        select(Contract)
        .where(Contract.agent_id == agent_id)
        .options(selectinload(Contract.versions))
        .order_by(Contract.id.desc())
    )
    contracts = result.scalars().all()
    return [_contract_to_dict(c) for c in contracts]


@router.post("/{agent_id}/generate")
async def generate_contract(
    agent_id: str,
    payload: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Auto-generate a contract proposal from agent config. Returns proposal — never activates."""
    from pathlib import Path

    from norma.agents.introspect import introspect_directory, introspect_file

    # Verify agent exists
    agent_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    discovered_tools: list[str] = []
    discovered_data_hints: list[str] = []
    if agent.entry_point:
        target = Path(agent.entry_point)
        try:
            if target.is_file():
                info = introspect_file(target)
            else:
                info = introspect_directory(target)
            discovered_tools = list(info.get("tool_names", []) or [])
            discovered_data_hints = list(info.get("data_path_hints", []) or [])
        except Exception:
            discovered_tools = []
            discovered_data_hints = []

    agent_config = {
        "agent_id": agent_id,
        "description": payload.get("description", agent.name),
        "tools": payload.get("tools", discovered_tools),
        "system_prompt": payload.get("system_prompt", ""),
        "data_hints": payload.get("data_hints", discovered_data_hints),
    }

    result = await generate_contract_proposal(agent_config, agent_id)

    # Determine next version
    existing = await db.execute(
        select(Contract)
        .where(Contract.agent_id == agent_id)
        .order_by(Contract.id.desc())
    )
    latest = existing.scalars().first()
    if latest:
        try:
            next_ver = f"{float(latest.version) + 1.0:.1f}"
        except ValueError:
            next_ver = "1.0"
    else:
        next_ver = "1.0"

    # Persist as inactive proposal
    contract = Contract(
        agent_id=agent_id,
        version=next_ver,
        yaml_content=result["yaml_content"],
        summary_text=contract_summary_from_yaml(result["yaml_content"]),
        is_active=False,
        created_by=payload.get("created_by", "norma-auto"),
    )
    db.add(contract)
    await db.flush()

    # Update agent pending version
    agent.pending_contract_version = next_ver
    await db.commit()

    return {
        **_contract_to_dict(contract),
        "meta": result.get("meta", {}),
        "validation_errors": result.get("validation_errors", []),
        "source": result.get("source", "stub"),
    }


_TIER_FROM_PENDING: dict[str, str] = {
    "pending-standard": "standard",
    "pending-trusted": "trusted",
}


@router.post("/{agent_id}/approve/{version}")
async def approve_contract(
    agent_id: str,
    version: str,
    approver: str = Query(..., description="Who is approving this contract"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Human approval step — activates the proposed contract version.

    If `version` is a synthetic label like 'pending-standard' (set by the seed
    or onboarding before a real contract row exists), the endpoint falls back to
    the most-recent contract for the agent and advances the tier accordingly.
    """
    # Primary lookup: exact version match
    result = await db.execute(
        select(Contract)
        .where(Contract.agent_id == agent_id, Contract.version == version)
        .options(selectinload(Contract.versions))
    )
    contract = result.scalar_one_or_none()

    # Fallback: synthetic pending label (e.g. "pending-standard") — use the
    # most-recent contract (active or not) for this agent.
    if contract is None and version in _TIER_FROM_PENDING:
        fallback = await db.execute(
            select(Contract)
            .where(Contract.agent_id == agent_id)
            .order_by(Contract.id.desc())
            .limit(1)
        )
        contract = fallback.scalar_one_or_none()

    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract v{version} not found for {agent_id}")

    # Load the agent to determine tier promotion
    agent_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = agent_result.scalar_one_or_none()

    # Determine target tier from the pending version label or the agent's stored label
    pending_label = (agent.pending_contract_version if agent else None) or version
    new_tier: str | None = _TIER_FROM_PENDING.get(pending_label)

    now = datetime.now(timezone.utc)

    if not contract.is_active:
        # Deactivate any currently active contract
        active_result = await db.execute(
            select(Contract).where(Contract.agent_id == agent_id, Contract.is_active == True)
        )
        for active in active_result.scalars().all():
            active.is_active = False

        contract.is_active = True
        contract.activated_at = now

    # Always stamp the approver (re-approve is allowed to advance the tier)
    contract.approved_by = approver

    # Log the approval
    version_entry = ContractVersion(
        contract_id=contract.id,
        changed_by="norma-auto",
        approved_by=approver,
        reason=f"Approved and activated by {approver}",
        timestamp=now,
    )
    db.add(version_entry)

    # Clear pending label and optionally promote tier
    if agent:
        agent.pending_contract_version = None
        if new_tier and agent.current_tier != new_tier:
            agent.current_tier = new_tier

    await db.commit()

    return {
        "status": "activated",
        "agent_id": agent_id,
        "version": contract.version,
        "approved_by": approver,
        "activated_at": now.isoformat(),
        "tier_advanced_to": new_tier,
    }


@router.post("/{agent_id}/disapprove/{version}")
async def disapprove_contract(
    agent_id: str,
    version: str,
    reviewer: str = Query(..., description="Who is disapproving this pending contract"),
    reason: str = Query("Rejected during review", description="Why this proposal was rejected"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject and remove a pending proposal. Active contracts cannot be disapproved."""
    result = await db.execute(
        select(Contract)
        .where(Contract.agent_id == agent_id, Contract.version == version)
        .options(selectinload(Contract.versions))
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract v{version} not found for {agent_id}")
    if contract.is_active:
        raise HTTPException(status_code=409, detail="Active contracts cannot be disapproved")

    agent_result = await db.execute(select(Agent).where(Agent.agent_id == agent_id))
    agent = agent_result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    db.add(
        ContractVersion(
            contract_id=contract.id,
            changed_by="norma-auto",
            approved_by=reviewer,
            reason=f"Disapproved by {reviewer}: {reason}",
            timestamp=now,
        )
    )
    await db.flush()

    for entry in list(contract.versions):
        await db.delete(entry)
    await db.flush()

    await db.delete(contract)
    if agent and agent.pending_contract_version == version:
        agent.pending_contract_version = None
    await db.commit()

    return {
        "status": "disapproved",
        "agent_id": agent_id,
        "version": version,
        "reviewer": reviewer,
        "reason": reason,
        "timestamp": now.isoformat(),
    }


@router.get("/{agent_id}/diff/{v1}/{v2}")
async def diff_contracts(
    agent_id: str, v1: str, v2: str, db: AsyncSession = Depends(get_db)
) -> dict:
    """Side-by-side diff between two contract versions."""
    import yaml

    r1 = await db.execute(
        select(Contract).where(Contract.agent_id == agent_id, Contract.version == v1)
    )
    r2 = await db.execute(
        select(Contract).where(Contract.agent_id == agent_id, Contract.version == v2)
    )
    c1 = r1.scalar_one_or_none()
    c2 = r2.scalar_one_or_none()

    if not c1 or not c2:
        raise HTTPException(status_code=404, detail="One or both contract versions not found")

    try:
        parsed1 = yaml.safe_load(c1.yaml_content) or {}
        parsed2 = yaml.safe_load(c2.yaml_content) or {}
    except Exception:
        parsed1, parsed2 = {}, {}

    # Compute field-level diff
    all_keys = set(list(parsed1.keys()) + list(parsed2.keys()))
    changes: list[dict] = []
    for key in sorted(all_keys):
        old_val = parsed1.get(key)
        new_val = parsed2.get(key)
        if old_val != new_val:
            changes.append({
                "field": key,
                "v1_value": old_val,
                "v2_value": new_val,
            })

    return {
        "agent_id": agent_id,
        "v1": {"version": v1, "yaml": c1.yaml_content, "approved_by": c1.approved_by, "activated_at": c1.activated_at.isoformat() if c1.activated_at else None},
        "v2": {"version": v2, "yaml": c2.yaml_content, "approved_by": c2.approved_by, "activated_at": c2.activated_at.isoformat() if c2.activated_at else None},
        "changes": changes,
        "n_fields_changed": len(changes),
    }


@router.put("/{agent_id}/{version}")
async def update_contract(
    agent_id: str,
    version: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update the YAML content of a pending (non-active) contract proposal.

    Design constraint: active contracts are read-only; only proposals can be edited.
    Every save creates a ContractVersion audit record.
    """
    import yaml

    result = await db.execute(
        select(Contract)
        .where(Contract.agent_id == agent_id, Contract.version == version)
        .options(selectinload(Contract.versions))
    )
    contract = result.scalar_one_or_none()
    if not contract:
        raise HTTPException(status_code=404, detail=f"Contract v{version} not found for agent {agent_id}")
    if contract.is_active:
        raise HTTPException(status_code=409, detail="Active contracts are read-only. Generate a new proposal to make changes.")

    new_yaml = payload.get("yaml_content", "").strip()
    if not new_yaml:
        raise HTTPException(status_code=422, detail="yaml_content is required")

    # Validate it parses as YAML
    try:
        yaml.safe_load(new_yaml)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}") from exc

    changed_by = payload.get("changed_by", "dashboard-user")

    # Audit record
    audit_entry = ContractVersion(
        contract_id=contract.id,
        diff_json=json.dumps({"previous_length": len(contract.yaml_content), "new_length": len(new_yaml)}),
        changed_by=changed_by,
        reason=payload.get("reason", "manual edit"),
        timestamp=datetime.now(timezone.utc),
    )
    contract.yaml_content = new_yaml
    contract.summary_text = contract_summary_from_yaml(new_yaml)
    db.add(audit_entry)
    await db.commit()
    await db.refresh(contract)

    return _contract_to_dict(contract)


@router.post("/{agent_id}/suggest-rule")
async def suggest_rule(
    agent_id: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Convert a natural-language rule description into a YAML clause.

    Deterministic heuristic mapping — no LLM required.
    Returns a yaml_snippet the UI can append to the pending contract.

    Examples:
      "deny access to data/confidential" → enforcement:\\n  deny:\\n  - data/confidential/**
      "only allow PDFs"                  → enforcement:\\n  allow:\\n  - **/*.pdf
      "max 5 tool calls per run"        → limits:\\n  max_tool_calls: 5
      "block tool read_secret_key"      → enforcement:\\n  denied_tools:\\n  - read_secret_key
    """
    import re

    text = (payload.get("text") or "").strip().lower()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")

    snippet: str = ""
    rule_type: str = "unknown"
    confidence: str = "low"

    # --- Pattern: deny file path ---
    m = re.search(r"deny\s+(?:access\s+to\s+)?([^\s,]+)", text)
    if m:
        path = m.group(1).rstrip(".,;")
        if not path.endswith("/**") and not path.endswith("*"):
            path = path.rstrip("/") + "/**"
        snippet = f"enforcement:\n  deny:\n  - {path}"
        rule_type = "path_deny"
        confidence = "high"

    # --- Pattern: allow file path ---
    elif re.search(r"allow\s+(?:access\s+to\s+|only\s+)?([^\s,]+)", text):
        m2 = re.search(r"allow\s+(?:access\s+to\s+|only\s+)?([^\s,]+)", text)
        path = m2.group(1).rstrip(".,;")  # type: ignore[union-attr]
        if not path.startswith("**") and "." in path:
            path = f"**/{path}"
        snippet = f"enforcement:\n  allow:\n  - {path}"
        rule_type = "path_allow"
        confidence = "high"

    # --- Pattern: block tool ---
    elif re.search(r"block\s+(?:tool\s+)?([a-z_][a-z0-9_]*)", text):
        m2 = re.search(r"block\s+(?:tool\s+)?([a-z_][a-z0-9_]*)", text)
        tool = m2.group(1)  # type: ignore[union-attr]
        snippet = f"enforcement:\n  denied_tools:\n  - {tool}"
        rule_type = "tool_deny"
        confidence = "high"

    # --- Pattern: max N tool calls ---
    elif re.search(r"max\s+(\d+)\s+tool", text):
        m2 = re.search(r"max\s+(\d+)\s+tool", text)
        n = int(m2.group(1))  # type: ignore[union-attr]
        snippet = f"limits:\n  max_tool_calls: {n}"
        rule_type = "limit"
        confidence = "high"

    # --- Pattern: max N runs per hour/day ---
    elif re.search(r"max\s+(\d+)\s+runs?\s+per\s+(hour|day)", text):
        m2 = re.search(r"max\s+(\d+)\s+runs?\s+per\s+(hour|day)", text)
        n = int(m2.group(1))  # type: ignore[union-attr]
        period = m2.group(2)  # type: ignore[union-attr]
        snippet = f"limits:\n  max_runs_per_{period}: {n}"
        rule_type = "rate_limit"
        confidence = "high"

    # --- Pattern: require human approval for ... ---
    elif re.search(r"require\s+(?:human\s+)?approval\s+for\s+(.+)", text):
        m2 = re.search(r"require\s+(?:human\s+)?approval\s+for\s+(.+)", text)
        what = m2.group(1).strip().rstrip(".,;")  # type: ignore[union-attr]
        snippet = f"governance:\n  require_approval_for:\n  - {what}"
        rule_type = "governance"
        confidence = "medium"

    else:
        # generic comment stub
        snippet = f"# TODO: manual rule — {text}"
        rule_type = "comment"
        confidence = "low"

    return {
        "agent_id": agent_id,
        "input_text": text,
        "yaml_snippet": snippet,
        "rule_type": rule_type,
        "confidence": confidence,
    }
