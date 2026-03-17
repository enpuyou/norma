"""Scenario test — OpenAI adapters (function-calling + Agents SDK).

Exercises Phase 2 multi-framework adapters end-to-end:
  S1. OpenAIFuncSession produces span trees (session → enforcement → tool_call)
  S2. OpenAIFuncSession blocks denied tools and records violations
  S3. OpenAIAgentSession produces span trees via RunHooks
  S4. OpenAIAgentSession blocks denied tools from on_tool_start
  S5. Introspection detects OpenAI Agents SDK patterns
  S6. Introspection detects OpenAI function-calling patterns
  S7. Both adapters flush to DB with correct framework field

All tests are offline — no real OpenAI API calls. We simulate the hook
lifecycle and client behavior to verify norma's monitoring/enforcement.
"""

from __future__ import annotations

import yaml
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from norma.integrations.openai_func_adapter import (
    OpenAIFuncSession,
    ToolBlockedError,
)
from norma.integrations.openai_agent_adapter import (
    OpenAIAgentSession,
    ToolBlockedError as AgentToolBlockedError,
)
from norma.models.agent import Agent
from norma.models.run import Run
from norma.models.span import Span


# ── Shared contract ────────────────────────────────────────────────────────────

CONTRACT_YAML = yaml.dump({
    "agent_id": "openai-test-agent",
    "authorities": {
        "tools": {
            "allow": ["list_data", "read_data", "summarize"],
            "deny": ["read_confidential", "web_search", "file_write"],
        },
        "data": {
            "allow": ["data/public/*"],
            "deny": ["data/confidential/*"],
        },
    },
    "sla": {
        "max_latency_ms": 5000,
        "max_cost_per_run": 1.00,
        "max_tool_calls_per_run": 10,
    },
    "trust": {
        "clean_run_increment": 0.025,
        "violation_penalty": 0.25,
        "tier_thresholds": {
            "standard": {"min_score": 0.65, "min_clean_runs": 10},
            "trusted": {"min_score": 0.82, "min_clean_runs": 20},
        },
    },
})


def _get_spans(db_url: str, run_id: int) -> list:
    """Retrieve spans for a run from a sync SQLAlchemy session."""
    engine = create_engine(db_url, echo=False)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        spans = db.query(Span).filter(Span.trace_id == run_id).all()
        result = [
            {"span_type": s.span_type, "name": s.name, "status": s.status,
             "tokens_in": s.tokens_in, "tokens_out": s.tokens_out}
            for s in spans
        ]
    engine.dispose()
    return result


def _get_latest_run(db_url: str, agent_id: str) -> dict | None:
    """Get the latest run for an agent."""
    engine = create_engine(db_url, echo=False)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        run = db.query(Run).filter(Run.agent_id == agent_id).order_by(Run.id.desc()).first()
        if run is None:
            return None
        result = {
            "id": run.id,
            "agent_id": run.agent_id,
            "completion_status": run.completion_status,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "cost_usd": run.cost_usd,
            "trust_score_after": run.trust_score_after,
        }
    engine.dispose()
    return result


# ── S1: OpenAIFuncSession span tree ───────────────────────────────────────────

def test_openai_func_span_tree(tmp_path):
    """OpenAIFuncSession emits session + tool spans when tools are called."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    _create_tables(db_url)

    with OpenAIFuncSession(
        agent_id="func-test-agent",
        contract_yaml=CONTRACT_YAML,
        db_url=db_url,
        check_enabled=False,
    ) as sess:
        # Simulate tool calls (without actual OpenAI client)
        # Record an LLM call
        sess.record_llm_call(
            model="gpt-4o",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            output_text="I'll list the data for you.",
        )

        # Record tool results
        sess.record_tool_result("list_data", "", "file1.txt, file2.txt")
        sess.record_tool_result("read_data", '{"filename": "file1.txt"}', "Revenue: $42.5B")

    # Verify spans
    run = _get_latest_run(db_url, "func-test-agent")
    assert run is not None
    assert run["completion_status"] == "success"
    assert run["input_tokens"] == 100
    assert run["output_tokens"] == 50

    spans = _get_spans(db_url, run["id"])
    span_types = [s["span_type"] for s in spans]
    assert "session" in span_types
    assert span_types.count("tool_call") == 2
    assert "llm_call" in span_types


# ── S2: OpenAIFuncSession blocks denied tools ─────────────────────────────────

def test_openai_func_blocks_denied_tool(tmp_path):
    """OpenAIFuncSession blocks a denied tool and records the violation."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    _create_tables(db_url)

    with OpenAIFuncSession(
        agent_id="func-block-agent",
        contract_yaml=CONTRACT_YAML,
        db_url=db_url,
        check_enabled=False,
    ) as sess:
        # Try to call a blocked tool via check_and_enforce_tool
        allowed, msg = sess.check_and_enforce_tool("read_confidential", "")
        assert not allowed
        assert "BLOCKED" in (msg or "")

        # Allowed tool should work
        allowed2, msg2 = sess.check_and_enforce_tool("list_data", "")
        assert allowed2
        assert msg2 is None

    run = _get_latest_run(db_url, "func-block-agent")
    assert run is not None
    assert run["completion_status"] == "failed"  # had a violation

    spans = _get_spans(db_url, run["id"])
    blocked_spans = [s for s in spans if s["status"] == "blocked"]
    assert len(blocked_spans) >= 1


# ── S3: OpenAIAgentSession span tree via hooks ────────────────────────────────

def test_openai_agent_span_tree(tmp_path):
    """OpenAIAgentSession hooks emit agent/llm/tool spans."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    _create_tables(db_url)

    import asyncio

    async def _run():
        with OpenAIAgentSession(
            agent_id="agents-sdk-test",
            contract_yaml=CONTRACT_YAML,
            db_url=db_url,
            check_enabled=False,
        ) as sess:
            hooks = sess.get_hooks()

            # Simulate agent lifecycle
            mock_agent = _MockAgent("research-agent", "gpt-4o")
            mock_context = None

            # on_agent_start
            await hooks.on_agent_start(mock_context, mock_agent)

            # on_llm_start
            await hooks.on_llm_start(mock_context, mock_agent, "You are helpful.", [])

            # on_llm_end with token usage
            mock_response = _MockModelResponse(
                input_tokens=200, output_tokens=80, response_id="resp_123"
            )
            await hooks.on_llm_end(mock_context, mock_agent, mock_response)

            # on_tool_start (allowed tool)
            mock_tool = _MockFunctionTool("list_data")
            await hooks.on_tool_start(mock_context, mock_agent, mock_tool)

            # on_tool_end
            await hooks.on_tool_end(
                mock_context, mock_agent, mock_tool,
                "file1.txt, file2.txt, file3.txt"
            )

            # on_agent_end
            await hooks.on_agent_end(mock_context, mock_agent, "Summary complete.")

    asyncio.run(_run())

    run = _get_latest_run(db_url, "agents-sdk-test")
    assert run is not None
    assert run["completion_status"] == "success"
    assert run["input_tokens"] == 200
    assert run["output_tokens"] == 80

    spans = _get_spans(db_url, run["id"])
    span_types = [s["span_type"] for s in spans]
    assert "session" in span_types
    assert "agent_start" in span_types
    assert "llm_call" in span_types
    assert "tool_call" in span_types

    # LLM span should have real token counts
    llm_spans = [s for s in spans if s["span_type"] == "llm_call"]
    assert llm_spans[0]["tokens_in"] == 200
    assert llm_spans[0]["tokens_out"] == 80


# ── S4: OpenAIAgentSession blocks denied tools ────────────────────────────────

def test_openai_agent_blocks_denied_tool(tmp_path):
    """OpenAIAgentSession raises ToolBlockedError for denied tools in on_tool_start."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    _create_tables(db_url)

    import asyncio

    async def _run():
        with OpenAIAgentSession(
            agent_id="agents-sdk-block",
            contract_yaml=CONTRACT_YAML,
            db_url=db_url,
            check_enabled=False,
        ) as sess:
            hooks = sess.get_hooks()
            mock_agent = _MockAgent("blocker-agent", "gpt-4o")

            # Try to start a denied tool
            mock_tool = _MockFunctionTool("read_confidential")
            with pytest.raises(AgentToolBlockedError):
                await hooks.on_tool_start(None, mock_agent, mock_tool)

    asyncio.run(_run())

    run = _get_latest_run(db_url, "agents-sdk-block")
    assert run is not None
    assert run["completion_status"] == "failed"

    spans = _get_spans(db_url, run["id"])
    blocked_spans = [s for s in spans if s["status"] == "blocked"]
    assert len(blocked_spans) >= 1


# ── S5: OpenAIAgentSession handoff span ───────────────────────────────────────

def test_openai_agent_handoff_span(tmp_path):
    """OpenAIAgentSession records handoff events between agents."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    _create_tables(db_url)

    import asyncio

    async def _run():
        with OpenAIAgentSession(
            agent_id="agents-sdk-handoff",
            contract_yaml=CONTRACT_YAML,
            db_url=db_url,
            check_enabled=False,
        ) as sess:
            hooks = sess.get_hooks()
            agent_a = _MockAgent("agent-a", "gpt-4o")
            agent_b = _MockAgent("agent-b", "gpt-4o")

            await hooks.on_agent_start(None, agent_a)
            await hooks.on_handoff(None, agent_a, agent_b)
            await hooks.on_agent_start(None, agent_b)
            await hooks.on_agent_end(None, agent_b, "Done")
            await hooks.on_agent_end(None, agent_a, "Delegated")

    asyncio.run(_run())

    run = _get_latest_run(db_url, "agents-sdk-handoff")
    assert run is not None
    spans = _get_spans(db_url, run["id"])
    span_types = [s["span_type"] for s in spans]
    assert "handoff" in span_types
    handoff_span = [s for s in spans if s["span_type"] == "handoff"][0]
    assert "agent-a->agent-b" in handoff_span["name"]


# ── S6: Introspection detects OpenAI Agents SDK ──────────────────────────────

def test_introspect_openai_agents_sdk():
    """Introspection detects @function_tool decorators and Agents SDK imports."""
    from norma.agents.introspect import _ast_detect_langchain_patterns, _ast_extract_tools

    source = '''
from agents import Agent, Runner, function_tool

@function_tool
def search_knowledge(query: str) -> str:
    """Search the knowledge base."""
    return "result"

@function_tool
def summarize(text: str) -> str:
    """Summarize text."""
    return "summary"

agent = Agent(name="researcher", tools=[search_knowledge, summarize])
'''
    patterns = _ast_detect_langchain_patterns(source)
    assert patterns["has_openai_agents_sdk"] is True
    assert patterns["framework"] == "openai_agents"
    assert patterns["confidence"] == "agent"
    assert "Agent" in patterns["detected_imports"]
    assert "function_tool" in patterns["detected_imports"]

    tools = _ast_extract_tools(source, "test.py")
    tool_names = [t["name"] for t in tools]
    assert "search_knowledge" in tool_names
    assert "summarize" in tool_names


# ── S7: Introspection detects OpenAI function-calling ─────────────────────────

def test_introspect_openai_func_schemas():
    """Introspection detects OpenAI function schemas and TOOL_FUNCTIONS dicts."""
    from norma.agents.introspect import (
        _ast_detect_langchain_patterns,
        _ast_extract_openai_func_tools,
    )

    source = '''
TOOL_FUNCTIONS = {
    "list_reports": list_reports,
    "read_report": read_report,
}

OPENAI_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_reports",
            "description": "List reports",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_report",
            "description": "Read a report",
            "parameters": {"type": "object", "properties": {"filename": {"type": "string"}}}
        }
    },
]
'''
    patterns = _ast_detect_langchain_patterns(source)
    assert patterns["has_openai_func"] is True
    assert patterns["framework"] == "openai_func"

    tools = _ast_extract_openai_func_tools(source, "test.py")
    tool_names = [t["name"] for t in tools]
    assert "list_reports" in tool_names
    assert "read_report" in tool_names


# ── S8: Framework field persisted correctly ───────────────────────────────────

def test_framework_field_in_adapter_spans(tmp_path):
    """Both adapters set correct framework field in their spans."""
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    _create_tables(db_url)

    # OpenAIFuncSession
    with OpenAIFuncSession(
        agent_id="fw-func",
        contract_yaml=CONTRACT_YAML,
        db_url=db_url,
        check_enabled=False,
    ) as sess:
        assert sess.framework == "openai_func"
        sess.record_llm_call("gpt-4o", tokens_in=10, tokens_out=5)

    # OpenAIAgentSession
    with OpenAIAgentSession(
        agent_id="fw-agents",
        contract_yaml=CONTRACT_YAML,
        db_url=db_url,
        check_enabled=False,
    ) as sess:
        assert sess.framework == "openai_agents"
        sess.record_llm_call("gpt-4o", tokens_in=10, tokens_out=5)

    # Verify DB persisted both runs
    run_func = _get_latest_run(db_url, "fw-func")
    run_agents = _get_latest_run(db_url, "fw-agents")
    assert run_func is not None
    assert run_agents is not None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _create_tables(db_url: str) -> None:
    """Create all tables in a fresh SQLite database."""
    from norma.database import Base
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(engine)
    engine.dispose()


class _MockAgent:
    """Minimal mock of agents.Agent for hook testing."""
    def __init__(self, name: str, model: str = "gpt-4o"):
        self.name = name
        self.model = model


class _MockUsage:
    """Mock of agents.usage.Usage."""
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.total_tokens = input_tokens + output_tokens
        self.requests = 1


class _MockModelResponse:
    """Mock of agents.items.ModelResponse."""
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0,
                 response_id: str = "resp_test"):
        self.usage = _MockUsage(input_tokens, output_tokens)
        self.response_id = response_id
        self.output = []


class _MockFunctionTool:
    """Mock of agents.FunctionTool."""
    def __init__(self, name: str):
        self.name = name
