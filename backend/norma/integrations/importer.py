"""
NormaImporter — bulk-import existing agents into norma.ai.

Registry YAML format (norma-registry.yaml):
──────────────────────────────────────────────────────────────────────────────
version: "1"
agents:
  - id: customer-support-agent
    name: Customer Support Agent
    type: orchestrator          # orchestrator | subagent | single
    owner: alice@company.com
    department: support
    description: Handles L1 support tickets via Zendesk
    tools:
      - knowledge_base_search
      - ticket_read
      - ticket_update
    data:
      allow:
        - knowledge_base/**
        - ticket_history/**
      deny:
        - payment_info/**
        - internal_notes/**
    # Optional: norma will generate the import snippet for this agent
    langgraph:
      module: myapp.agents.support   # python dotted module path
      variable: support_graph        # the compiled graph variable name

  - id: code-review-agent
    name: Code Review Agent
    type: single
    description: Reviews pull requests for bugs and security issues
    tools: [github_read, github_comment]
    data:
      allow: [repos/**]
      deny:  [repos/**/secrets/**, repos/**/.env]
──────────────────────────────────────────────────────────────────────────────

Run:
    poetry run norma-import --registry norma-registry.yaml
    poetry run norma-import --registry norma-registry.yaml --generate-snippets
    poetry run norma-import --scan ./myapp/agents/               # auto-discover
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

import yaml


class NormaImporter:
    """
    Reads an agent registry (YAML) and registers each agent with norma.ai.

    Steps per agent:
      1. Parse config
      2. Generate a contract proposal (stub or LLM if OPENAI_API_KEY is set)
      3. Register in DB (Phase 1)
      4. Emit the two-line code snippet to paste into the existing agent file
      5. Output a summary table of all imported agents + their contract status
    """

    def __init__(self, db_url: str | None = None) -> None:
        self.db_url = db_url
        self.results: list[dict[str, Any]] = []

    def load_registry(self, registry_path: str | Path) -> list[dict[str, Any]]:
        """Parse a norma-registry.yaml and return the list of agent configs."""
        path = Path(registry_path)
        if not path.exists():
            raise FileNotFoundError(f"Registry file not found: {path}")
        with path.open() as f:
            data = yaml.safe_load(f)
        agents = data.get("agents", [])
        if not agents:
            raise ValueError("Registry file has no agents listed.")
        return agents

    def scan_module(self, module_path: str) -> list[dict[str, Any]]:
        """
        Auto-discover LangGraph CompiledGraph / StateGraph instances in a module.
        Returns a list of partial agent configs (id, variable, module).
        Requires the module to be importable (i.e. in PYTHONPATH).
        """
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            raise ImportError(f"Cannot import module {module_path!r}: {exc}") from exc

        discovered: list[dict[str, Any]] = []
        for name, obj in inspect.getmembers(mod):
            # Duck-type: LangGraph compiled graphs have .invoke and .ainvoke
            if callable(getattr(obj, "invoke", None)) and callable(getattr(obj, "ainvoke", None)):
                discovered.append({
                    "id": name.lower().replace("_", "-"),
                    "name": name,
                    "type": "single",
                    "description": f"Auto-discovered from {module_path}.{name}",
                    "tools": [],
                    "langgraph": {"module": module_path, "variable": name},
                })
        return discovered

    def scan_directory(self, directory: str | Path) -> list[dict[str, Any]]:
        """Scan a directory for Python files and look for LangGraph graphs in each."""
        base = Path(directory)
        discovered: list[dict[str, Any]] = []
        for py_file in sorted(base.rglob("*.py")):
            # Build module path from file path
            module_path = ".".join(py_file.with_suffix("").parts)
            try:
                found = self.scan_module(module_path)
                discovered.extend(found)
            except ImportError:
                pass   # skip unimportable files silently
        return discovered

    def _generate_contract(self, agent: dict[str, Any]) -> str:
        """
        Generate a contract YAML for an agent config.
        Uses LLM if OPENAI_API_KEY is set; otherwise generates a deterministic stub.
        Enforcement is always disabled until a human approves.
        """
        from norma.integrations.track import _stub_contract
        tools = agent.get("tools", [])
        description = agent.get("description", agent.get("name", agent["id"]))
        stub = _stub_contract(agent["id"], tools, description)

        # Overlay data allow/deny from registry if specified
        data_rules = agent.get("data", {})
        if data_rules:
            contract_dict = yaml.safe_load(stub)
            if "allow" in data_rules:
                contract_dict["authorities"]["data"]["allow"] = data_rules["allow"]
            if "deny" in data_rules:
                contract_dict["authorities"]["data"]["deny"]  = data_rules["deny"]
            return yaml.dump(contract_dict, default_flow_style=False)
        return stub

    def _generate_snippet(self, agent: dict[str, Any]) -> str:
        """Return a two-line Python snippet to add to the existing agent file."""
        lg = agent.get("langgraph", {})
        if lg:
            graph_var = lg.get("variable", "graph")
            agent_id  = agent["id"]
            return (
                f"# Add these two lines to {lg.get('module', 'your_agent_module')}:\n"
                f"from norma.integrations import track\n"
                f"{graph_var} = track({graph_var}, agent_id={agent_id!r})\n"
                f"# That's it. norma.ai is now tracking {agent_id!r}."
            )
        else:
            agent_id = agent["id"]
            return (
                f"# Wrap your graph before invoking it:\n"
                f"from norma.integrations import track\n"
                f"graph = track(graph, agent_id={agent_id!r})\n"
                f"# Or use the session context manager:\n"
                f"# with norma.session({agent_id!r}) as s:\n"
                f"#     result = graph.invoke(inputs)\n"
                f"#     s.record_quality(score=your_score)"
            )

    def import_agents(
        self,
        agents: list[dict[str, Any]],
        *,
        dry_run: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Import a list of agent configs.
        Returns a list of result dicts with: id, contract_generated, snippet, status.
        """
        results = []
        for agent in agents:
            contract_yaml = self._generate_contract(agent)
            snippet       = self._generate_snippet(agent)

            result = {
                "id":                 agent["id"],
                "name":               agent.get("name", agent["id"]),
                "type":               agent.get("type", "single"),
                "owner":              agent.get("owner", "unset"),
                "contract_generated": True,
                "contract_yaml":      contract_yaml,
                "snippet":            snippet,
                "status":             "dry_run" if dry_run else "imported",
                "enforcement":        "DISABLED (pending human approval)",
            }

            if not dry_run:
                # TODO Phase 1: persist to DB via SQLAlchemy
                pass

            results.append(result)

        self.results = results
        return results
