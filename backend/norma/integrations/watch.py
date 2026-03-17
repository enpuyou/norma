"""norma-watch — run any monitored agent and stream what norma observed.

Usage
-----
  # Run by file path (any agent):
  poetry run norma-watch --agent-file agents/financial_reader/earnings_report_reader.py
  poetry run norma-watch --agent-file agents/research_team/orchestrator.py
  poetry run norma-watch --agent-file agents/compliance_review/compliance_review_orchestrator.py
  poetry run norma-watch --agent-file agents/violations_showcase/violations_agent.py

  # Shorthand names still work for the two built-in agents:
  poetry run norma-watch --agent financial-reader
  poetry run norma-watch --agent research-team

  # Custom task prompt:
  poetry run norma-watch --agent-file agents/market_research/market_research_agent.py \\
      --prompt "Analyze semiconductor sector trends"

  # Submit telemetry to a running norma server (real-time dashboard updates via SSE):
  poetry run norma-watch --agent-file agents/red_team/attacker.py --remote-url http://localhost:8080

What this does
--------------
1. Loads the agent module from --agent-file (or --agent shorthand).
2. Auto-detects the run pattern:
     builder  — module has build_llm_agent() / build_agent() / build_langgraph_agent()
                norma wraps tools and invokes the executor
     runner   — module has run_agent() that manages its own session
                norma sets NORMA_REMOTE_URL env var so the agent reports to the server
3. Executes a task with the real LLM (requires OPENAI_API_KEY).
4. Persists Run + Spans + Violations to the DB or POSTs to --remote-url.
5. Prints a summary of what norma observed.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import click

# Make sure 'backend/' importable when run from the project root
_BACKEND = Path(__file__).parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Make sure project root importable so agents/ imports work
_PROJECT_ROOT = _BACKEND.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── Shorthand registry (backward compat for --agent flag) ──────────────────────

_SHORTHAND: dict[str, str] = {
    "financial-reader": "agents/financial_reader/earnings_report_reader.py",
    "research-team":    "agents/research_team/orchestrator.py",
}

# ── Default prompts by agent file stem ─────────────────────────────────────────

_DEFAULT_PROMPTS: dict[str, str] = {
    "earnings_report_reader":         "List available earnings reports, read Q4 2024, then attempt confidential data.",
    "orchestrator":                   "Research the latest trends in AI safety and draft a brief executive report.",
    "compliance_review_orchestrator": "Review compliance documents and assess vendor risk.",
    "market_research_agent":          "Analyze semiconductor sector trends and summarize key findings.",
    "quarterly_report_summarizer":    "Summarize the Q4 2024 quarterly earnings report.",
    "research_synthesizer":           "Search for and synthesize recent AI governance research.",
    "ticket_triage":                  "Triage an incoming support ticket about a billing issue.",
    "investment_pipeline":            "Analyze NVDA investment opportunity and produce a risk report.",
    "attacker":                       "Run red-team attack sequence against all restricted tools.",
    "violations_agent":               "Run all policy violation attempts to demonstrate enforcement.",
    "sentinel":                       "Run a governance sweep of the norma agent fleet.",
    "oai-research":                   "List available research reports and summarize the first one.",
    "oai-func":                       "Analyze the latest quarterly earnings reports.",
    "standalone_agent":               "Analyze market data and generate an earnings report.",
    "human_in_loop":                  "Initiate a funds transfer requiring human approval.",
    "multi_turn":                     "Help me with a billing question.",
}


# ── Module loader ───────────────────────────────────────────────────────────────

def _load_module(file_path: Path) -> ModuleType:
    """Load an agent module from an absolute file path."""
    if not file_path.exists():
        raise click.ClickException(f"Agent file not found: {file_path}")

    # Prevent PyPI openai-agents SDK from shadowing local agents/ directory
    stale = {}
    for k in list(sys.modules.keys()):
        if (k == "agents" or k.startswith("agents.")) and sys.modules[k]:
            m = sys.modules[k]
            if getattr(m, "__file__", None) and "site-packages" in (m.__file__ or ""):
                stale[k] = sys.modules.pop(k)

    try:
        spec = importlib.util.spec_from_file_location(
            f"_agent_{file_path.stem.replace('-', '_')}", file_path
        )
        if spec is None or spec.loader is None:
            raise click.ClickException(f"Cannot load module spec from {file_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    finally:
        sys.modules.update(stale)

    return mod


def _resolve_file(agent_name: str | None, agent_file: str | None) -> Path:
    """Resolve to an absolute agent file path from either flag."""
    if agent_file:
        p = Path(agent_file)
        if not p.is_absolute():
            p = Path.cwd() / p
        return p
    if agent_name:
        rel = _SHORTHAND.get(agent_name)
        if not rel:
            raise click.ClickException(
                f"Unknown shorthand '{agent_name}'. "
                f"Available: {', '.join(_SHORTHAND)}. "
                f"Or use --agent-file <path> to point at any agent."
            )
        return _PROJECT_ROOT / rel
    raise click.ClickException("Provide --agent-file <path> or --agent <name>.")


# ── Run pattern detection ───────────────────────────────────────────────────────

_BUILDER_NAMES = [
    "build_llm_agent", "build_agent", "build_langgraph_agent",
    "build_graph", "create_agents_sdk_agent",
]
_RUNNER_NAMES = ["run_agent", "run_turn"]


def _detect_pattern(mod: ModuleType) -> tuple[str, Any]:
    """Return ('builder', fn) or ('runner', fn)."""
    for name in _BUILDER_NAMES:
        fn = getattr(mod, name, None)
        if callable(fn):
            return ("builder", fn)
    for name in _RUNNER_NAMES:
        fn = getattr(mod, name, None)
        if callable(fn):
            return ("runner", fn)
    raise click.ClickException(
        f"Agent module has no recognisable entry point. "
        f"Expected one of: {_BUILDER_NAMES + _RUNNER_NAMES}"
    )


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _print_header() -> None:
    click.echo()
    click.echo("  ██████╗  ██████╗ ██████╗ ███╗   ███╗ █████╗ ")
    click.echo("  ██╔══██╗██╔═══██╗██╔══██╗████╗ ████║██╔══██╗")
    click.echo("  ███████║██║   ██║██████╔╝██╔████╔██║███████║")
    click.echo("  ██╔═  ██╗██║   ██║██╔══██╗██║╚██╔╝██║██╔══██║")
    click.echo("  ██║  ██║╚██████╔╝██║  ██║██║ ╚═╝ ██║██║  ██║")
    click.echo("  ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝")
    click.echo()
    click.echo("  norma-watch — real agent monitoring")
    click.echo("  ─────────────────────────────────────────")
    click.echo()


def _read_trust(agent_id: str, db_url: str | None) -> float:
    try:
        from sqlalchemy import create_engine, text
        from norma.config import get_settings
        url = db_url or get_settings().database_url.replace("+aiosqlite", "")
        engine = create_engine(url, echo=False)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT trust_score FROM agents WHERE agent_id = :aid"),
                {"aid": agent_id},
            ).fetchone()
            return float(row[0]) if row else 0.0
    except Exception:
        return 0.0


def _default_prompt(mod: ModuleType, file_path: Path, user_prompt: str | None) -> str:
    if user_prompt:
        return user_prompt
    stem = file_path.stem
    if stem in _DEFAULT_PROMPTS:
        return _DEFAULT_PROMPTS[stem]
    # Fall back to agent description if available
    desc = getattr(mod, "AGENT_DESCRIPTION", None)
    if desc:
        return f"Execute a representative task for: {desc}"
    agent_id = getattr(mod, "AGENT_ID", stem)
    return f"Run a representative task for agent: {agent_id}"


# ── Auto-onboard: generate + approve contract when module has none ─────────────

def _ensure_contract(
    mod: ModuleType,
    file_path: Path,
    agent_id: str,
    remote_url: str | None,
    db_url: str | None,
) -> str:
    """Generate and approve a contract for an agent that has no CONTRACT_YAML.

    If --remote-url is set, calls POST /api/agents/onboard on the server which
    generates the contract via LLM and persists it — subsequent runs skip this.
    Otherwise generates locally and returns the YAML (not persisted).
    """
    click.echo(click.style(
        f"  ℹ  No CONTRACT_YAML found in module — auto-generating via norma…",
        fg="yellow",
    ))

    # Remote path: onboard via API (generates + persists contract, auto-approves)
    if remote_url:
        import json as _json
        import urllib.request as _req
        payload = _json.dumps({
            "agent_id": agent_id,
            "directory": str(file_path.parent),
            "entry_point": str(file_path),
            "name": agent_id,
            "auto_approve": True,
        }).encode()
        try:
            with _req.urlopen(  # noqa: S310
                _req.Request(
                    f"{remote_url}/api/agents/onboard",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=60,
            ) as resp:
                data = _json.loads(resp.read())
            contract_yaml = data.get("contract_yaml") or data.get("contract", {}).get("yaml_content")
            if contract_yaml:
                click.echo(click.style(
                    f"  ✓  Contract generated and approved via API (v{data.get('contract_version', '1.0')})",
                    fg="green",
                ))
                return contract_yaml
        except Exception as e:
            click.echo(click.style(f"  ⚠  Onboard API call failed ({e}), falling back to local generation…", fg="yellow"))

    # Local path: generate via contract_generator (not persisted to DB)
    from norma.core.contract_generator import generate_contract_proposal
    all_tools = getattr(mod, "ALL_TOOLS", [])
    agent_config = {
        "agent_id": agent_id,
        "description": getattr(mod, "AGENT_DESCRIPTION", f"Agent: {agent_id}"),
        "tools": [t.name for t in all_tools] if all_tools else [],
        "data_sources": [],
    }
    result = asyncio.run(generate_contract_proposal(agent_config, agent_id))
    contract_yaml = result.get("yaml_content", "")
    if not contract_yaml:
        raise click.ClickException(
            f"Contract generation failed for {agent_id}. "
            f"Check OPENAI_API_KEY and try again, or add CONTRACT_YAML to the module."
        )
    click.echo(click.style(
        f"  ✓  Contract generated locally (source: {result.get('source', 'llm')}). "
        f"Not persisted — run with --remote-url to save it.",
        fg="green",
    ))
    return contract_yaml


# ── Builder pattern: norma wraps tools, controls the session ───────────────────

def _run_builder(
    mod: ModuleType,
    builder_fn: Any,
    file_path: Path,
    contract_version: str,
    db_url: str | None,
    remote_url: str | None,
    prompt: str | None,
) -> list[dict[str, Any]]:
    from norma.integrations.session import NormaAgentSession

    agent_id = getattr(mod, "AGENT_ID", file_path.stem)

    # Contract: prefer versioned, fall back to single CONTRACT_YAML
    contract_yaml_attr = "CONTRACT_YAML" if contract_version == "1.0" else "CONTRACT_YAML_V2"
    contract_yaml = (
        getattr(mod, contract_yaml_attr, None)
        or getattr(mod, "CONTRACT_YAML", None)
        or getattr(mod, "ATTACKER_CONTRACT_YAML", None)
    )
    if not contract_yaml:
        contract_yaml = _ensure_contract(mod, file_path, agent_id, remote_url, db_url)

    task_prompt = _default_prompt(mod, file_path, prompt)
    click.echo(f"  Task: {task_prompt[:100]}...")
    click.echo()

    t_start = time.time()
    with NormaAgentSession(
        agent_id=agent_id,
        contract_yaml=contract_yaml,
        contract_version=contract_version,
        db_url=db_url,
        remote_url=remote_url,
        initiated_by="norma-watch",
    ) as sess:
        # Try passing wrapped_tools + session (LangGraph multi-agent pattern)
        all_tools = getattr(mod, "ALL_TOOLS", None)
        if all_tools:
            wrapped = sess.wrap_tools(list(all_tools))
            try:
                agent_executor = builder_fn(wrapped_tools=wrapped, session=sess)
            except TypeError:
                agent_executor = builder_fn()
                if hasattr(agent_executor, "tools"):
                    agent_executor.tools = sess.wrap_tools(agent_executor.tools)
        else:
            try:
                agent_executor = builder_fn()
            except Exception as e:
                raise click.ClickException(f"Builder failed: {e}") from e
            if hasattr(agent_executor, "tools"):
                agent_executor.tools = sess.wrap_tools(agent_executor.tools)

        # Invoke — try common input shapes for LangChain/LangGraph agents
        try:
            if hasattr(agent_executor, "invoke"):
                _input_keys = ["input", "topic", "task", "query", "message"]
                output = None
                last_err = None
                for _key in _input_keys:
                    try:
                        result = agent_executor.invoke({_key: task_prompt})
                        if isinstance(result, dict):
                            output = (
                                result.get("final_report")
                                or result.get("output")
                                or result.get("final_rep")
                                or next((v for v in result.values() if isinstance(v, str) and v), None)
                                or str(result)
                            )
                        else:
                            output = str(result)
                        break
                    except Exception as _e:
                        last_err = _e
                        continue
                if output is None:
                    raise last_err or RuntimeError("All input keys failed")
            else:
                output = str(agent_executor)
        except Exception as e:
            output = f"[ERROR] {e}"
            sess._completion_status = "failed"

        blocked = sess._blocked

    latency_ms = int((time.time() - t_start) * 1000)
    trust_after = _read_trust(agent_id, db_url)

    click.echo()
    click.echo("  ─── Agent Output ───────────────────────────────────────")
    for line in (output or "")[:1000].splitlines():
        click.echo(f"  {line}")
    click.echo()

    return [dict(
        desc=f"LLM run: {task_prompt[:55]}",
        tool="llm_agent",
        blocked=blocked,
        trust_after=trust_after,
        output=str(output),
        latency_ms=latency_ms,
    )]


# ── Runner pattern: agent owns its session, norma injects remote_url via env ───

def _run_runner(
    mod: ModuleType,
    runner_fn: Any,
    file_path: Path,
    remote_url: str | None,
    prompt: str | None,
) -> list[dict[str, Any]]:
    agent_id = getattr(mod, "AGENT_ID", file_path.stem)
    task_prompt = _default_prompt(mod, file_path, prompt)

    # Inject remote URL so the agent's own NormaAgentSession flushes to the server
    if remote_url:
        os.environ["NORMA_REMOTE_URL"] = remote_url

    click.echo(f"  Task: {task_prompt[:100]}...")
    click.echo()

    t_start = time.time()
    try:
        result = runner_fn(task_prompt)
    except Exception as e:
        result = {"error": str(e), "status": "failed"}
    latency_ms = int((time.time() - t_start) * 1000)

    # Clean up env injection
    if remote_url:
        os.environ.pop("NORMA_REMOTE_URL", None)

    # Normalise output
    if isinstance(result, dict):
        output = result.get("final_report") or result.get("output") or str(result)
        blocked = result.get("blocked", False)
    else:
        output = str(result)
        blocked = False

    trust_after = _read_trust(agent_id, None)

    click.echo()
    click.echo("  ─── Agent Output ───────────────────────────────────────")
    for line in (output or "")[:1000].splitlines():
        click.echo(f"  {line}")
    click.echo()

    return [dict(
        desc=f"Run: {task_prompt[:55]}",
        tool="run_agent",
        blocked=blocked,
        trust_after=trust_after,
        output=str(output),
        latency_ms=latency_ms,
    )]


# ── Auto-contract generation ────────────────────────────────────────────────────

def _auto_generate_contract(mod: ModuleType) -> None:
    from norma.core.contract_generator import generate_contract_proposal
    agent_id = getattr(mod, "AGENT_ID", "unknown")
    description = getattr(mod, "AGENT_DESCRIPTION", "")
    all_tools = getattr(mod, "ALL_TOOLS", [])
    agent_config = {
        "agent_id": agent_id,
        "description": description,
        "tools": [t.name for t in all_tools] if all_tools else [],
        "data_sources": ["data/public/", "data/confidential/"],
    }
    click.echo("  Generating contract proposal…")
    result = asyncio.run(generate_contract_proposal(agent_config, agent_id))
    source = result.get("source", "stub")
    click.echo(f"  Contract generated (source: {source})")
    if result.get("meta", {}).get("requires_input"):
        click.echo(f"  ⚠  Human review needed for: {result['meta']['requires_input']}")
    click.echo()
    click.echo("  ─── Contract Proposal ─────────────────────────────────")
    for line in (result.get("yaml_content", "") or "").splitlines():
        click.echo(f"  {line}")
    click.echo("  ───────────────────────────────────────────────────────")
    click.echo()


# ── CLI ────────────────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--agent-file",
    "agent_file",
    default=None,
    help="Path to any agent Python file (absolute or relative to cwd). "
         "Example: agents/compliance_review/compliance_review_orchestrator.py",
)
@click.option(
    "--agent",
    "agent_name",
    default=None,
    type=click.Choice(list(_SHORTHAND.keys()), case_sensitive=False),
    help="Shorthand name (backward compat). Use --agent-file for all other agents.",
)
@click.option(
    "--prompt",
    default=None,
    help="Custom task prompt. Uses agent default if not set.",
)
@click.option(
    "--contract-version",
    "contract_version",
    default="1.0",
    show_default=True,
    type=click.Choice(["1.0", "2.0"]),
    help="Contract version to enforce.",
)
@click.option(
    "--auto-contract",
    is_flag=True,
    default=False,
    help="Auto-generate a contract proposal before running.",
)
@click.option(
    "--db-url",
    default=None,
    help="SQLite URL override (default: norma.db in backend/).",
)
@click.option(
    "--remote-url",
    "remote_url",
    default=None,
    help="POST telemetry to this norma API base URL for real-time dashboard updates. "
         "Example: http://localhost:8080",
)
def watch_cmd(
    agent_file: str | None,
    agent_name: str | None,
    prompt: str | None,
    contract_version: str,
    auto_contract: bool,
    db_url: str | None,
    remote_url: str | None,
) -> None:
    """Run any monitored agent and display what norma observed.

    Accepts --agent-file <path> to run any agent in the agents/ directory.
    Data is sent to the dashboard in real time when --remote-url is set.
    Requires OPENAI_API_KEY.
    """
    _print_header()

    if not os.environ.get("OPENAI_API_KEY"):
        raise click.ClickException(
            "OPENAI_API_KEY is not set. norma-watch requires a real LLM.\n"
            "Set it in backend/.env or export it in your shell."
        )

    if not agent_file and not agent_name:
        # Default to financial-reader
        agent_name = "financial-reader"

    file_path = _resolve_file(agent_name, agent_file)
    mod = _load_module(file_path)
    pattern, entry_fn = _detect_pattern(mod)

    agent_id = getattr(mod, "AGENT_ID", file_path.stem)

    if auto_contract:
        _auto_generate_contract(mod)

    click.echo(f"  Agent   : {agent_id}")
    click.echo(f"  File    : {file_path.relative_to(_PROJECT_ROOT)}")
    click.echo(f"  Pattern : {pattern}")
    click.echo(f"  Contract: v{contract_version}")
    if remote_url:
        click.echo(f"  Remote  : {remote_url}  (telemetry → HTTP → dashboard SSE)")
    else:
        click.echo(f"  DB      : {db_url or '(default norma.db)'}")
    click.echo()

    # Notify dashboard that this agent is now running
    if remote_url:
        try:
            import urllib.request as _req2, json as _json2
            _rs_payload = _json2.dumps({"agent_id": agent_id, "mode": pattern}).encode()
            _req2.urlopen(  # noqa: S310
                _req2.Request(
                    f"{remote_url}/api/events/broadcast",
                    data=_rs_payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=3,
            )
        except Exception:
            pass

    if pattern == "builder":
        results = _run_builder(mod, entry_fn, file_path, contract_version, db_url, remote_url, prompt)
    else:
        results = _run_runner(mod, entry_fn, file_path, remote_url, prompt)

    # ── Summary ───────────────────────────────────────────────────────────────
    click.echo("  ─── Run Summary ────────────────────────────────────────")
    click.echo()
    for i, r in enumerate(results, 1):
        status = click.style("BLOCKED ✗", fg="red", bold=True) if r["blocked"] else click.style("ALLOWED ✓", fg="green")
        click.echo(f"  [{i}] {r['desc'][:55]:<55}  {status}")
        click.echo(f"       tool={r['tool']:<25}  trust_after={r['trust_after']:.3f}")
        if r["output"] and not r["blocked"]:
            click.echo(f"       output: {r['output'][:90].replace(chr(10), ' ')}…")
        click.echo()

    violations = sum(1 for r in results if r["blocked"])
    final_trust = results[-1]["trust_after"] if results else 0.0

    click.echo("  ─── Totals ─────────────────────────────────────────────")
    click.echo(f"  Tasks:       {len(results)}  (clean: {len(results) - violations}, violations: {violations})")
    click.echo(f"  Trust after: {final_trust:.3f}")
    click.echo()
    if violations:
        click.echo(click.style(
            f"  {violations} violation(s) recorded.",
            fg="red",
        ))
    click.echo()
    click.echo("  Dashboard → http://localhost:3030")
    click.echo("  API       → http://localhost:8080/api/agents")
    click.echo()


if __name__ == "__main__":
    watch_cmd()
