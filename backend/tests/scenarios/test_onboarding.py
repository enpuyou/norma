"""S1 — Real Onboarding Scenario Test.

Enterprise scenario:
    A platform team has an agent as Python code in a directory.
    They want norma to monitor it.  They should NOT have to manually type
    their tool names into a form — norma should read the code.

    Real input:  a path to norma/agents/financial_reader.py
    Real process:
        1. norma scans the file for @tool-decorated functions (AST, no import)
        2. Discovered tool names drive contract generation
        3. Agent is registered in the DB
        4. Contract proposal is stored (inactive — awaiting human review)
    Real proof:  the contract allow list contains the tool names from the code,
                 NOT generic placeholders or whatever the user typed in a form.

What this test validates:
    - introspect_directory() finds the actual @tool names in financial_reader.py
    - AST extraction does NOT require importing the module (safe for foreign code)
    - introspect_file() works for single-file agents
    - Tool names in the generated contract match the introspected real names
    - Onboarding with a bad path returns a clear error (not a 500)

No LLM calls.  Uses scenario_db fixture for DB-writing tests.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from norma.agents.introspect import introspect_directory, introspect_file


# ── Path to the real agent code we're onboarding ──────────────────────────────
# Canonical agents live in <project_root>/agents/, not inside the backend package.
# backend/tests/scenarios/test_onboarding.py → .parent×4 = project root
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
_AGENTS_DIR = _PROJECT_ROOT / "agents" / "financial_reader"
_FINANCIAL_READER = _AGENTS_DIR / "earnings_report_reader.py"

# The 3 tools defined in financial_reader.py (ground truth)
_EXPECTED_TOOLS = {"list_reports", "read_report", "read_confidential"}


# ── Test: introspect_file returns the actual @tool functions ───────────────────

def test_introspect_file_finds_real_tools() -> None:
    """
    Scenario: team points norma at their single-file agent.
    Expected: introspect_file() returns the 3 tools defined in financial_reader.py.

    This is AST-based (no import) — safe to run in CI on any machine.
    """
    assert _FINANCIAL_READER.exists(), (
        f"Test fixture missing: {_FINANCIAL_READER}\n"
        "This test requires the real financial_reader.py agent file."
    )

    result = introspect_file(_FINANCIAL_READER)

    found_names = set(result["tool_names"])
    assert found_names == _EXPECTED_TOOLS, (
        f"AST introspection found {found_names}, expected {_EXPECTED_TOOLS}.\n"
        "Tool names must come from code, not from user-typed text."
    )


def test_introspect_file_returns_docstrings() -> None:
    """
    Scenario: contract generation needs a description for each tool to infer
    what it does (data access patterns, sensitivity).
    Expected: every discovered tool has a non-empty description from its docstring.
    """
    result = introspect_file(_FINANCIAL_READER)
    for tool in result["tools"]:
        assert tool["description"], (
            f"Tool '{tool['name']}' has no docstring.  "
            "Contract generator needs descriptions to infer data access patterns."
        )


def test_introspect_file_source_is_ast() -> None:
    """
    AST-based extraction must be the primary path — it does not execute code.
    Verifying source = "ast" guarantees the code was not imported.
    """
    result = introspect_file(_FINANCIAL_READER)
    for tool in result["tools"]:
        assert tool["source"] == "ast", (
            f"Tool '{tool['name']}' was extracted via '{tool['source']}', "
            "expected 'ast'.  Onboarding must be safe for foreign codebases."
        )


def test_introspect_file_detects_data_path_hints() -> None:
    """
    The file contains path literals like 'reports/public' and 'reports/confidential'.
    These are hints for what data the agent accesses, used to seed the contract's
    data.allow and data.deny sections.
    """
    result = introspect_file(_FINANCIAL_READER)
    hints = result["data_path_hints"]

    confidential_hint = any("confidential" in h.lower() for h in hints)
    public_hint = any("public" in h.lower() or "reports" in h.lower() for h in hints)

    assert confidential_hint or public_hint, (
        f"Expected path hints containing 'confidential' or 'public/reports'.\n"
        f"Got: {hints}"
    )


# ── Test: introspect_directory on the agents/ dir ─────────────────────────────

def test_introspect_directory_scans_py_files() -> None:
    """
    Scenario: team has a multi-file agent directory.
    Expected: introspect_directory() scans all .py files and returns all tools.
    """
    result = introspect_directory(_AGENTS_DIR)

    assert result["files_scanned"] >= 1, "Should have scanned at least financial_reader.py"
    assert len(result["tools"]) >= 3, (
        f"Expected ≥3 tools from agents/, found {len(result['tools'])}"
    )
    # All expected tools should be found
    found = set(result["tool_names"])
    for expected in _EXPECTED_TOOLS:
        assert expected in found, f"Expected tool '{expected}' not found in directory scan"


def test_introspect_directory_deduplicates_tools() -> None:
    """
    If the same tool appears in multiple files, it should only appear once
    in the output (e.g., if tools.py re-exports from base.py).
    """
    result = introspect_directory(_AGENTS_DIR)
    names = result["tool_names"]
    assert len(names) == len(set(names)), (
        f"Duplicate tool names in output: {[n for n in names if names.count(n) > 1]}"
    )


# ── Test: missing directory returns clear error ────────────────────────────────

def test_introspect_missing_directory_raises() -> None:
    """
    Scenario: user runs norma onboard --dir ./typo-in-path/.
    Expected: a clear FileNotFoundError, not a Python AttributeError or 500.
    """
    import pytest
    with pytest.raises(FileNotFoundError, match="not found"):
        introspect_directory(_AGENTS_DIR / "does_not_exist")


# ── Test: introspected tools drive contract generation ─────────────────────────

def test_onboarded_contract_tools_match_code(scenario_db: str) -> None:
    """
    Scenario: the full onboarding flow from code → contract proposal.

    What this validates end-to-end (no HTTP, pure service layer):
      1. Introspect real code → get tool names
      2. Generate stub contract from those tool names
      3. Contract allow list contains the REAL tool names from code

    This is the core claim: onboarding does NOT use user-typed tool names.
    The contract is grounded in the actual code.
    """
    from norma.core.contract_generator import _generate_stub

    # Step 1: introspect real code
    introspection = introspect_file(_FINANCIAL_READER)
    real_tool_names = introspection["tool_names"]
    assert len(real_tool_names) >= 3, "Introspection must discover real tools"

    # Step 2: generate contract from introspected names
    agent_config = {
        "agent_id": "onboard-code-test",
        "description": "Financial report reader introspected from code",
        "tools": real_tool_names,
        "system_prompt": "",
    }
    contract_result = _generate_stub(agent_config, "onboard-code-test")

    # Step 3: verify the contract tools match the code
    parsed = yaml.safe_load(contract_result["yaml_content"])
    contract_allow = set(parsed["authorities"]["tools"]["allow"])

    for tool_name in real_tool_names:
        assert tool_name in contract_allow, (
            f"Tool '{tool_name}' discovered in code but missing from contract allow list.\n"
            f"Contract allow: {contract_allow}\n"
            f"This means onboarding is not grounded in the real code."
        )


def test_empty_directory_returns_empty_tools() -> None:
    """
    Scenario: team runs norma onboard on a directory with no Python tools.
    Expected: no crash, just an empty tool list and a clear error-free response.
    """
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a Python file with no @tool functions
        py_file = Path(tmpdir) / "helpers.py"
        py_file.write_text("def add(a, b):\n    return a + b\n")

        result = introspect_directory(tmpdir)
        assert result["tools"] == []
        assert result["files_scanned"] == 1
        assert result["errors"] == []


def test_syntax_error_in_file_is_reported_not_crashed() -> None:
    """
    Scenario: one file in the directory has a syntax error (common in dev).
    Expected: the error is reported in result["errors"], other files still scanned.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # Bad file
        bad = Path(tmpdir) / "broken.py"
        bad.write_text("def broken(:):\n    pass\n")  # intentional SyntaxError

        # Good file with a tool
        good = Path(tmpdir) / "good_tools.py"
        good.write_text(
            "from langchain_core.tools import tool\n\n"
            "@tool\n"
            "def good_tool(x: str) -> str:\n"
            '    """A working tool."""\n'
            "    return x\n"
        )

        result = introspect_directory(tmpdir)

    assert len(result["errors"]) >= 1, "Syntax error must be reported"
    assert result["errors"][0]["file"].endswith("broken.py")
    # Good file was still processed
    assert "good_tool" in result["tool_names"], "Good file must still be scanned"
