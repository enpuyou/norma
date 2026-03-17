"""Agent code introspection — extract tool definitions from Python source.

This module scans Python files for LangChain @tool decorators and BaseTool
subclasses.  AST-based parsing is the primary approach (never executes user
code).  Import-based scanning is used as a fallback when AST finds nothing.

Enterprise scenario:
    A team has a Python agent directory:
        my_agent/
          tools.py      ← @tool functions
          pipeline.py   ← orchestration logic

    They run:
        poetry run norma onboard --dir ./my_agent/ --agent-id my-agent --name "My Agent"

    norma introspects the directory, extracts real tool names from the actual
    code (not user-typed text), and generates a contract proposal.

Real input:  a filesystem path to a Python module or directory
Real output: {tools: [{name, description, args, source, file}], data_path_hints, errors,
              agents: [{agent_id, type, confidence, files, tools}], file_hash}
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import re
from pathlib import Path
from typing import Any


# ── LangChain pattern detection ──────────────────────────────────────────────────

# Imports that signal LangChain agent usage
_LANGCHAIN_AGENT_IMPORTS = {
    "AgentExecutor", "create_react_agent", "create_openai_tools_agent",
    "create_structured_chat_agent", "initialize_agent", "AgentType",
    "hub",
}
# Imports that signal LangGraph orchestration
_LANGGRAPH_IMPORTS = {
    "StateGraph", "END", "START", "CompiledGraph",
}
# LLM classes
_LLM_CLASSES = {
    "ChatOpenAI", "ChatAnthropic", "ChatGoogleGenerativeAI", "ChatBedrock",
    "OpenAI", "AzureChatOpenAI", "ChatOllama", "ChatMistralAI",
}
# Patterns that signal agent invocation
_INVOKE_PATTERNS = {
    ".invoke(", ".run(", "AgentExecutor(", "graph.compile(", ".stream(",
}

# ── OpenAI Agents SDK pattern detection ──────────────────────────────────────────

# Imports that signal OpenAI Agents SDK usage
_OPENAI_AGENTS_SDK_IMPORTS = {
    "Agent", "Runner", "function_tool", "RunHooks",
    "FunctionTool", "RunResult", "RunConfig",
    "handoff", "Handoff", "GuardrailFunctionOutput",
}
# Module-level imports for the agents SDK
_OPENAI_AGENTS_SDK_MODULES = {
    "agents",
}
# Patterns that signal Agents SDK invocation
_OPENAI_AGENTS_SDK_INVOKE = {
    "Runner.run(", "Runner.run_sync(", "Runner.run_streamed(",
    "Agent(", "function_tool",
}

# ── OpenAI function-calling pattern detection ────────────────────────────────────

# Imports that signal vanilla OpenAI function-calling
_OPENAI_FUNC_IMPORTS = {
    "OpenAI", "AsyncOpenAI", "AzureOpenAI", "AsyncAzureOpenAI",
}
_OPENAI_FUNC_MODULES = {
    "openai",
}
# Patterns that signal function-calling usage
_OPENAI_FUNC_PATTERNS = {
    "chat.completions.create", "tools=[", '"type": "function"',
    "tool_choice", "function_call",
}


def _ast_detect_langchain_patterns(source: str) -> dict[str, Any]:
    """
    Detect LangChain / LangGraph / OpenAI patterns in source code via AST + regex.

    Returns a dict with:
        has_tool_decorator    bool  — @tool (LangChain) or @function_tool (Agents SDK)
        has_agent_executor    bool
        has_langgraph         bool
        has_llm_class         bool
        has_invoke            bool
        has_openai_agents_sdk bool  — OpenAI Agents SDK patterns detected
        has_openai_func       bool  — OpenAI function-calling patterns detected
        detected_imports      list[str]  — matched import names
        agent_type_hint       str | None — "orchestrator" | "subagent" | "single" | None
        framework             str | None — "langchain" | "langgraph" | "openai_agents" | "openai_func" | None
        confidence            "agent" | "possible" | "none"
        pattern_count         int
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _empty_pattern_result()

    detected_imports: set[str] = set()

    # Walk AST for import names
    all_known = (
        _LANGCHAIN_AGENT_IMPORTS | _LANGGRAPH_IMPORTS | _LLM_CLASSES
        | _OPENAI_AGENTS_SDK_IMPORTS | _OPENAI_FUNC_IMPORTS
    )
    openai_agents_module_seen = False
    openai_module_seen = False

    for node in ast.walk(tree):
        # from x import A, B
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Track module-level imports: "from agents import ..." or "from openai import ..."
            if module.split(".")[0] in _OPENAI_AGENTS_SDK_MODULES:
                openai_agents_module_seen = True
            if module.split(".")[0] in _OPENAI_FUNC_MODULES:
                openai_module_seen = True
            for alias in node.names:
                name = alias.asname or alias.name
                base = alias.name.split(".")[0]
                for sym in (name, base):
                    if sym in all_known:
                        detected_imports.add(sym)
        # import x as y
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                if name.split(".")[0] in _OPENAI_AGENTS_SDK_MODULES:
                    openai_agents_module_seen = True
                if name.split(".")[0] in _OPENAI_FUNC_MODULES:
                    openai_module_seen = True
                for sym in all_known:
                    if sym in name:
                        detected_imports.add(sym)

    # Check for AGENT_TYPE / SUBAGENTS variables
    has_agent_type_var = "AGENT_TYPE" in source or "SUBAGENTS" in source
    # @tool (LangChain) or @function_tool (Agents SDK) — both count
    has_tool_decorator = "@tool" in source or "@function_tool" in source
    has_agent_executor = bool(detected_imports & _LANGCHAIN_AGENT_IMPORTS)
    has_langgraph = bool(detected_imports & _LANGGRAPH_IMPORTS)
    has_llm_class = bool(detected_imports & _LLM_CLASSES)
    has_invoke = any(p in source for p in _INVOKE_PATTERNS)

    # OpenAI Agents SDK detection
    has_openai_agents_sdk = (
        openai_agents_module_seen
        and bool(detected_imports & _OPENAI_AGENTS_SDK_IMPORTS)
    ) or any(p in source for p in _OPENAI_AGENTS_SDK_INVOKE)

    # OpenAI function-calling detection
    # Trigger if we see openai module import + patterns, OR if we see
    # OpenAI function schemas (\"type\": \"function\") even without the import
    has_openai_func = (
        openai_module_seen
        and any(p in source for p in _OPENAI_FUNC_PATTERNS)
    ) or (
        '\"type\": \"function\"' in source
        and '\"function\"' in source
        and '\"parameters\"' in source
    )

    pattern_count = sum([
        has_tool_decorator,
        has_agent_executor,
        has_langgraph,
        has_llm_class,
        has_invoke,
        has_agent_type_var,
        has_openai_agents_sdk,
        has_openai_func,
    ])

    # Infer framework
    framework: str | None = None
    if has_openai_agents_sdk:
        framework = "openai_agents"
    elif has_openai_func:
        framework = "openai_func"
    elif has_langgraph:
        framework = "langgraph"
    elif has_agent_executor or has_tool_decorator:
        framework = "langchain"

    # Infer type hint
    agent_type_hint: str | None = None
    if has_langgraph or ("SUBAGENTS" in source):
        agent_type_hint = "orchestrator"
    elif has_openai_agents_sdk and ("handoff" in source.lower() or "Handoff" in source):
        agent_type_hint = "orchestrator"
    elif has_tool_decorator and (has_agent_executor or has_openai_agents_sdk):
        agent_type_hint = "subagent"
    elif has_tool_decorator or has_agent_executor or has_llm_class or has_openai_agents_sdk or has_openai_func:
        agent_type_hint = "single"

    confidence: str
    if pattern_count >= 2:
        confidence = "agent"
    elif pattern_count == 1:
        confidence = "possible"
    else:
        confidence = "none"

    return {
        "has_tool_decorator": has_tool_decorator,
        "has_agent_executor": has_agent_executor,
        "has_langgraph": has_langgraph,
        "has_llm_class": has_llm_class,
        "has_invoke": has_invoke,
        "has_openai_agents_sdk": has_openai_agents_sdk,
        "has_openai_func": has_openai_func,
        "detected_imports": sorted(detected_imports),
        "agent_type_hint": agent_type_hint,
        "framework": framework,
        "confidence": confidence,
        "pattern_count": pattern_count,
    }


def _empty_pattern_result() -> dict[str, Any]:
    return {
        "has_tool_decorator": False,
        "has_agent_executor": False,
        "has_langgraph": False,
        "has_llm_class": False,
        "has_invoke": False,
        "has_openai_agents_sdk": False,
        "has_openai_func": False,
        "detected_imports": [],
        "agent_type_hint": None,
        "framework": None,
        "confidence": "none",
        "pattern_count": 0,
    }


def _compute_file_hash(files: list[Path]) -> str:
    """SHA-256 hash of all file contents, sorted by path for determinism."""
    h = hashlib.sha256()
    for f in sorted(files):
        try:
            h.update(f.read_bytes())
        except Exception:
            pass
    return h.hexdigest()[:16]


def _group_agent_files(
    py_files: list[Path],
    file_patterns: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Group Python files into likely agent units.

    Heuristics:
      1. Files in the same directory that share LangChain imports are grouped.
      2. A file named agent.py / main.py / pipeline.py is the entry point.
      3. Remaining files in the directory are support files.

    Returns list of agent candidates:
        {
          "entry_point": str,
          "directory": str,
          "files": [str, ...],
          "type": "orchestrator" | "subagent" | "single",
          "confidence": "agent" | "possible",
          "tools": [str, ...],  (tool names found in this group)
          "detected_imports": [str, ...],
          "file_hash": str,
        }
    """
    # Group by parent directory
    dir_groups: dict[Path, list[Path]] = {}
    for f in py_files:
        dir_groups.setdefault(f.parent, []).append(f)

    candidates: list[dict[str, Any]] = []

    ENTRY_NAMES = {"agent.py", "main.py", "pipeline.py", "app.py", "run.py", "orchestrator.py"}

    for directory, files in dir_groups.items():
        # Aggregate patterns across files in this directory
        combined_patterns: dict[str, Any] = {
            "has_tool_decorator": False,
            "has_agent_executor": False,
            "has_langgraph": False,
            "has_llm_class": False,
            "has_invoke": False,
            "has_openai_agents_sdk": False,
            "has_openai_func": False,
            "detected_imports": [],
            "agent_type_hint": None,
            "framework": None,
            "confidence": "none",
            "pattern_count": 0,
        }
        all_tools: list[str] = []

        for f in files:
            fp = file_patterns.get(str(f), _empty_pattern_result())
            combined_patterns["has_tool_decorator"] |= fp.get("has_tool_decorator", False)
            combined_patterns["has_agent_executor"] |= fp.get("has_agent_executor", False)
            combined_patterns["has_langgraph"] |= fp.get("has_langgraph", False)
            combined_patterns["has_llm_class"] |= fp.get("has_llm_class", False)
            combined_patterns["has_invoke"] |= fp.get("has_invoke", False)
            combined_patterns["has_openai_agents_sdk"] |= fp.get("has_openai_agents_sdk", False)
            combined_patterns["has_openai_func"] |= fp.get("has_openai_func", False)
            combined_patterns["detected_imports"] = sorted(set(
                combined_patterns["detected_imports"] + fp.get("detected_imports", [])
            ))
            # Prefer the most specific framework detected
            if fp.get("framework") and not combined_patterns["framework"]:
                combined_patterns["framework"] = fp["framework"]
            all_tools.extend(fp.get("tool_names", []))

        combined_patterns["pattern_count"] = sum([
            combined_patterns["has_tool_decorator"],
            combined_patterns["has_agent_executor"],
            combined_patterns["has_langgraph"],
            combined_patterns["has_llm_class"],
            combined_patterns["has_invoke"],
            combined_patterns["has_openai_agents_sdk"],
            combined_patterns["has_openai_func"],
        ])

        # Skip directories with no agent patterns
        if combined_patterns["pattern_count"] == 0:
            continue

        confidence = "agent" if combined_patterns["pattern_count"] >= 2 else "possible"

        # Infer agent type from directory-level signals
        if combined_patterns["has_langgraph"]:
            agent_type = "orchestrator"
        elif combined_patterns["has_openai_agents_sdk"] and any(
            "handoff" in str(f).lower() for f in files
        ):
            agent_type = "orchestrator"
        elif combined_patterns["has_agent_executor"] and combined_patterns["has_tool_decorator"]:
            agent_type = "subagent"
        else:
            agent_type = "single"

        # Infer framework
        framework = combined_patterns.get("framework")
        if not framework:
            if combined_patterns["has_openai_agents_sdk"]:
                framework = "openai_agents"
            elif combined_patterns["has_openai_func"]:
                framework = "openai_func"
            elif combined_patterns["has_langgraph"]:
                framework = "langgraph"
            elif combined_patterns["has_agent_executor"] or combined_patterns["has_tool_decorator"]:
                framework = "langchain"

        # Pick entry point
        entry_file = next(
            (f for f in files if f.name in ENTRY_NAMES),
            files[0],
        )

        candidates.append({
            "entry_point": str(entry_file),
            "directory": str(directory),
            "files": [str(f) for f in sorted(files)],
            "type": agent_type,
            "confidence": confidence,
            "tools": sorted(set(all_tools)),
            "detected_imports": combined_patterns["detected_imports"],
            "framework": framework,
            "file_hash": _compute_file_hash(files),
        })

    return candidates



def introspect_directory(directory: str | Path) -> dict[str, Any]:
    """
    Scan a Python directory for LangChain tool definitions and agent patterns.

    Uses AST-based parsing so the code is never executed (safe for foreign
    codebases).  Falls back to import-based scanning if AST finds nothing.

    Returns:
        tools:            list of {name, description, args, source, file}
        tool_names:       list[str]  — convenience flat list of names
        data_path_hints:  list[str]  — string literals that look like file paths
        files_scanned:    int
        errors:           list of {file, error}
        agents:           list of detected agent candidates with confidence scoring
        file_hash:        str  — SHA-256 (first 16 chars) of all scanned files
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    tools: list[dict[str, Any]] = []
    data_paths: list[str] = []
    errors: list[dict[str, str]] = []
    files_scanned = 0
    file_patterns: dict[str, dict[str, Any]] = {}

    py_files = [
        f for f in sorted(dir_path.rglob("*.py"))
        if f.name != "__pycache__" and "__pycache__" not in str(f) and "test" not in f.name
    ]

    for py_file in py_files:
        files_scanned += 1
        try:
            source = py_file.read_text(encoding="utf-8")
            file_tools = _ast_extract_tools(source, str(py_file))
            # Also extract from OpenAI function schemas if present
            if not file_tools:
                file_tools = _ast_extract_openai_func_tools(source, str(py_file))
            file_paths = _ast_extract_data_paths(source)
            patterns = _ast_detect_langchain_patterns(source)
            # Annotate patterns with tool_names for grouping
            patterns["tool_names"] = [t["name"] for t in file_tools]
            file_patterns[str(py_file)] = patterns
            tools.extend(file_tools)
            data_paths.extend(file_paths)
        except SyntaxError as e:
            errors.append({"file": str(py_file), "error": f"SyntaxError: {e}"})
            file_patterns[str(py_file)] = _empty_pattern_result()
        except Exception as e:
            errors.append({"file": str(py_file), "error": str(e)})
            file_patterns[str(py_file)] = _empty_pattern_result()

    # If AST found nothing (e.g. class-based tools), try import-based scan
    if not tools:
        for py_file in py_files:
            import_tools = _import_extract_tools(py_file)
            tools.extend(import_tools)

    # Deduplicate by tool name (same tool may appear in multiple files)
    seen: set[str] = set()
    unique_tools: list[dict[str, Any]] = []
    for t in tools:
        if t["name"] not in seen:
            seen.add(t["name"])
            unique_tools.append(t)

    # Detect agent candidates with confidence scoring
    agent_candidates = _group_agent_files(py_files, file_patterns)

    return {
        "tools": unique_tools,
        "tool_names": [t["name"] for t in unique_tools],
        "data_path_hints": sorted(set(data_paths)),
        "files_scanned": files_scanned,
        "errors": errors,
        "agents": agent_candidates,
        "file_hash": _compute_file_hash(py_files),
    }


def introspect_file(py_file: str | Path) -> dict[str, Any]:
    """
    Introspect a single Python file.  Convenience wrapper around
    introspect_directory for when the user points at a specific file.
    """
    path = Path(py_file)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {py_file}")

    tools: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    try:
        source = path.read_text(encoding="utf-8")
        tools = _ast_extract_tools(source, str(path))
        if not tools:
            tools = _ast_extract_openai_func_tools(source, str(path))
        data_paths = _ast_extract_data_paths(source)
        patterns = _ast_detect_langchain_patterns(source)
        patterns["tool_names"] = [t["name"] for t in tools]
    except SyntaxError as e:
        errors.append({"file": str(path), "error": f"SyntaxError: {e}"})
        data_paths = []
        patterns = _empty_pattern_result()
    except Exception as e:
        errors.append({"file": str(path), "error": str(e)})
        data_paths = []
        patterns = _empty_pattern_result()

    if not tools:
        tools = _import_extract_tools(path)

    # Single-file agent candidate
    agent_type = patterns.get("agent_type_hint") or "single"
    confidence = patterns.get("confidence", "none")
    framework = patterns.get("framework")
    agent_candidates = [{
        "entry_point": str(path),
        "directory": str(path.parent),
        "files": [str(path)],
        "type": agent_type,
        "confidence": confidence,
        "tools": [t["name"] for t in tools],
        "detected_imports": patterns.get("detected_imports", []),
        "framework": framework,
        "file_hash": _compute_file_hash([path]),
    }] if confidence != "none" else []

    return {
        "tools": tools,
        "tool_names": [t["name"] for t in tools],
        "data_path_hints": sorted(set(data_paths)),
        "files_scanned": 1,
        "errors": errors,
        "agents": agent_candidates,
        "file_hash": _compute_file_hash([path]),
    }


# ── AST-based extraction (primary — no code execution) ──────────────────────────

def _ast_extract_tools(source: str, filename: str) -> list[dict[str, Any]]:
    """
    Parse Python source with AST and find @tool-decorated functions.

    Detected patterns:
        @tool                       — bare decorator
        @tool(...)                  — decorator with arguments (e.g. @tool(name="x"))
        @langchain_core.tools.tool  — fully qualified
    """
    tree = ast.parse(source)
    tools = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        if not _has_tool_decorator(node) and not _has_function_tool_decorator(node):
            continue

        docstring = ast.get_docstring(node) or ""
        args = [
            arg.arg for arg in node.args.args
            if arg.arg not in ("self", "cls")
        ]

        # Try to pick up a custom tool name from @tool(name="x") or @function_tool(name="x")
        name = _extract_decorator_name_arg(node) or node.name

        tools.append({
            "name": name,
            "description": docstring.strip(),
            "args": args,
            "source": "ast",
            "file": filename,
        })

    return tools


def _ast_extract_openai_func_tools(source: str, filename: str) -> list[dict[str, Any]]:
    """
    Extract tool definitions from OpenAI function-calling schemas.

    Detects patterns like:
        OPENAI_TOOL_SCHEMAS = [{"type": "function", "function": {"name": "..."}}]
        TOOL_FUNCTIONS = {"tool_name": func, ...}
    """
    tools: list[dict[str, Any]] = []

    # Strategy 1: regex for "name" keys in function schemas
    import re
    # Match "name": "tool_name" patterns inside function schema dicts
    name_pattern = re.compile(
        r'"function"\s*:\s*\{[^}]*"name"\s*:\s*"([a-zA-Z_][a-zA-Z0-9_]*)"',
        re.DOTALL,
    )
    for match in name_pattern.finditer(source):
        tool_name = match.group(1)
        tools.append({
            "name": tool_name,
            "description": "",
            "args": [],
            "source": "openai_schema",
            "file": filename,
        })

    # Strategy 2: dict assignment TOOL_FUNCTIONS = {"name": func, ...}
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if "TOOL" not in target.id.upper() and "FUNCTION" not in target.id.upper():
                    continue
                # It's a dict literal
                if isinstance(node.value, ast.Dict):
                    for key in node.value.keys:
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            if key.value not in [t["name"] for t in tools]:
                                tools.append({
                                    "name": key.value,
                                    "description": "",
                                    "args": [],
                                    "source": "openai_dict",
                                    "file": filename,
                                })
    except SyntaxError:
        pass

    return tools


def _has_tool_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function has a @tool decorator (any form)."""
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == "tool":
            return True
        if isinstance(deco, ast.Attribute) and deco.attr == "tool":
            return True
        if isinstance(deco, ast.Call):
            func = deco.func
            if isinstance(func, ast.Name) and func.id == "tool":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                return True
    return False


def _has_function_tool_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the function has a @function_tool decorator (OpenAI Agents SDK)."""
    for deco in node.decorator_list:
        if isinstance(deco, ast.Name) and deco.id == "function_tool":
            return True
        if isinstance(deco, ast.Attribute) and deco.attr == "function_tool":
            return True
        if isinstance(deco, ast.Call):
            func = deco.func
            if isinstance(func, ast.Name) and func.id == "function_tool":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "function_tool":
                return True
    return False


def _extract_decorator_name_arg(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Extract name= keyword argument from @tool(name="...") if present."""
    for deco in node.decorator_list:
        if not isinstance(deco, ast.Call):
            continue
        for kw in deco.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                return str(kw.value.value)
    return None


_PATH_TOKEN_RE = None  # lazy init


def _ast_extract_data_paths(source: str) -> list[str]:
    """
    Extract string literals (or path-like tokens within larger strings) that
    look like file-system paths.  These are hints for what data the agent
    accesses — not authoritative, but useful contract seed material.

    Two strategies:
    1. Short string constants that look like paths (unchanged behaviour).
    2. For longer string constants (e.g. embedded YAML blocks), scan the
       content for path-token patterns like  word/word  or  word/word/**
       to catch entries in deny/allow lists.
    """
    import re

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    _path_re = re.compile(
        r"\b((?:[a-zA-Z0-9_.-]+/){1,}[a-zA-Z0-9_.*-]+)"
    )

    paths: list[str] = []
    seen: set[str] = set()

    def _add(val: str) -> None:
        if val not in seen and not val.startswith("http"):
            seen.add(val)
            paths.append(val)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        val = node.value
        if not val or val.startswith("http") or val.startswith("${"):
            continue

        if ("/" in val or "\\" in val) and 3 < len(val) < 120:
            # Short path literal — direct match
            _add(val)
        elif len(val) >= 120 and "/" in val:
            # Large string (e.g. YAML block) — scan for embedded path tokens
            for match in _path_re.finditer(val):
                token = match.group(1)
                if (
                    3 < len(token) < 80
                    and not token.startswith("http")
                    and not token[0].isdigit()
                ):
                    _add(token)

    return paths[:40]  # cap to avoid noise from huge files


# ── Import-based extraction (fallback — executes code) ───────────────────────────

def _import_extract_tools(py_file: Path) -> list[dict[str, Any]]:
    """
    Load the module and inspect for BaseTool instances.
    More accurate than AST (catches class-based tools), but executes the code.
    Catches all exceptions — caller must handle empty list gracefully.
    """
    try:
        from langchain_core.tools import BaseTool

        spec = importlib.util.spec_from_file_location(
            f"_norma_introspect_{py_file.stem}", py_file
        )
        if not spec or not spec.loader:
            return []

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        tools = []
        for _attr_name, obj in inspect.getmembers(module):
            if isinstance(obj, BaseTool):
                args: list[str] = []
                if hasattr(obj, "args"):
                    try:
                        args = list(obj.args.keys())
                    except Exception:
                        pass

                tools.append({
                    "name": obj.name,
                    "description": obj.description,
                    "args": args,
                    "source": "import",
                    "file": str(py_file),
                })

        return tools
    except Exception:
        return []


# ── CLI entry point ─────────────────────────────────────────────────────────────

def onboard_cmd() -> None:
    """
    CLI: poetry run norma-onboard --dir ./path/to/agent/ --agent-id my-agent --name "My Agent"

    Introspects the directory and prints the discovered tool list.
    For full registration, use POST /api/agents/onboard.
    """
    import json
    import sys

    import click

    @click.command()
    @click.option("--dir", "directory", required=True, help="Path to agent Python directory")
    @click.option("--agent-id", required=True, help="Agent identifier (lowercase, [a-z0-9_-])")
    @click.option("--name", required=True, help="Human-readable agent name")
    @click.option("--json-out", is_flag=True, help="Output as JSON")
    def _cmd(directory: str, agent_id: str, name: str, json_out: bool) -> None:
        from rich.console import Console
        from rich.table import Table

        console = Console()

        try:
            result = introspect_directory(directory)
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

        if json_out:
            console.print(json.dumps(result, indent=2))
            return

        console.print(f"\n[bold green]norma introspection[/bold green] — {directory}")
        console.print(
            f"  Files scanned: {result['files_scanned']}  |  "
            f"Tools found: {len(result['tools'])}"
        )

        if result["tools"]:
            table = Table(title="Discovered Tools")
            table.add_column("Name", style="cyan")
            table.add_column("Args")
            table.add_column("Description")
            for t in result["tools"]:
                table.add_row(
                    t["name"],
                    ", ".join(t["args"]) or "—",
                    (t["description"] or "—")[:60],
                )
            console.print(table)
        else:
            console.print("[yellow]No @tool-decorated functions found.[/yellow]")

        if result["errors"]:
            for err in result["errors"]:
                console.print(f"[red]Error in {err['file']}:[/red] {err['error']}")

        if result["data_path_hints"]:
            console.print("\n[bold]Data path hints:[/bold]")
            for p in result["data_path_hints"][:10]:
                console.print(f"  {p}")

        console.print(
            f"\n[dim]To register:[/dim] POST /api/agents/onboard with "
            f'{{"directory": "{directory}", "agent_id": "{agent_id}", "name": "{name}"}}'
        )

    _cmd()
