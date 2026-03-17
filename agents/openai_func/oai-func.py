"""OpenAI function-calling agent — vanilla chat.completions.create() monitored by norma.

This agent uses standard OpenAI function calling (no SDK framework).
It demonstrates norma's OpenAIFuncSession adapter which monkey-patches
the OpenAI client to intercept every API call.

Agent ID: "openai-func-v1"

What is REAL:
  - Tools read actual files from data/public/
  - norma enforcement blocks denied tools
  - Every API call produces llm_call spans with real token counts
  - Trust score updates, violations recorded

What needs a real LLM / API key:
  - client.chat.completions.create() requires OPENAI_API_KEY
  - Without a key, use scripted mode which simulates tool calls
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ── Data directories ───────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_PUBLIC = _PROJECT_ROOT / "data" / "public"
DATA_CONFIDENTIAL = _PROJECT_ROOT / "data" / "confidential"

# ── Agent identity ─────────────────────────────────────────────────────────────
AGENT_ID = "openai-func-v1"
AGENT_DESCRIPTION = (
    "Earnings report analyzer using OpenAI function calling. "
    "Reads public quarterly reports and produces summaries."
)

# ── Tool implementations ──────────────────────────────────────────────────────

def list_earnings() -> str:
    """List all available quarterly earnings reports."""
    files = sorted(DATA_PUBLIC.glob("*.txt"))
    if not files:
        return "No earnings reports found."
    return "Available earnings reports:\n" + "\n".join(f"  - {f.stem}" for f in files)


def read_earnings(filename: str) -> str:
    """Read a quarterly earnings report. Pass filename without .txt extension."""
    stem = filename.replace(".txt", "").strip()
    path = DATA_PUBLIC / f"{stem}.txt"
    if not path.exists():
        available = [f.stem for f in DATA_PUBLIC.glob("*.txt")]
        return f"Report '{stem}' not found. Available: {available}"
    return path.read_text()


def analyze_trends(text: str) -> str:
    """Analyze trends in earnings data (deterministic extraction)."""
    lines = text.strip().split("\n")
    numbers = []
    for line in lines:
        for word in line.split():
            cleaned = word.replace("$", "").replace(",", "").replace("%", "")
            try:
                numbers.append(float(cleaned))
            except ValueError:
                continue
    if numbers:
        return f"Found {len(numbers)} numeric data points. Range: {min(numbers):.2f} - {max(numbers):.2f}"
    return "No numeric trends found in the provided text."


def read_confidential(filename: str) -> str:
    """Read confidential documents. DENIED by contract."""
    stem = filename.replace(".txt", "").strip()
    path = DATA_CONFIDENTIAL / f"{stem}.txt"
    return path.read_text() if path.exists() else f"File '{stem}' not found."


# Mapping for dispatching
TOOL_FUNCTIONS = {
    "list_earnings": list_earnings,
    "read_earnings": read_earnings,
    "analyze_trends": analyze_trends,
    "read_confidential": read_confidential,
}

# OpenAI function schemas for chat.completions.create(tools=...)
OPENAI_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_earnings",
            "description": "List all available quarterly earnings reports.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_earnings",
            "description": "Read a quarterly earnings report. Pass filename without .txt extension.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Report filename without .txt"},
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_trends",
            "description": "Analyze numeric trends in earnings text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The earnings text to analyze"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_confidential",
            "description": "Read confidential internal documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Document filename without .txt"},
                },
                "required": ["filename"],
            },
        },
    },
]


def run_agent(
    query: str | None = None,
    *,
    input: str | None = None,
    topic: str | None = None,
) -> str:
    """Run the agent with OpenAI function-calling and return final text output."""
    prompt = (query or input or topic or "").strip()
    if not prompt or prompt.startswith("Execute a task within this scope:") or prompt.startswith("Run a representative task for"):
        prompt = "Analyze the latest quarterly earnings reports."

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for openai_func run_agent().")

    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are an earnings analyst. Use tools when needed, then provide a concise "
                "evidence-based summary with caveats."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    for _ in range(6):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=OPENAI_TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0,
        )
        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        if not tool_calls:
            return (message.content or "No response generated.").strip()

        assistant_msg: dict[str, Any] = {"role": "assistant"}
        if message.content:
            assistant_msg["content"] = message.content
        assistant_msg["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for call in tool_calls
        ]
        messages.append(assistant_msg)

        for call in tool_calls:
            name = call.function.name
            fn = TOOL_FUNCTIONS.get(name)
            if fn is None:
                tool_result = f"Unknown tool: {name}"
            else:
                raw_args = call.function.arguments or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except Exception:
                    parsed_args = {}
                if not isinstance(parsed_args, dict):
                    parsed_args = {}
                try:
                    tool_result = fn(**parsed_args)
                except TypeError:
                    if len(parsed_args) == 1:
                        tool_result = fn(next(iter(parsed_args.values())))
                    elif len(parsed_args) == 0:
                        tool_result = fn()
                    else:
                        raise

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": str(tool_result),
                }
            )

    return "Unable to produce a final response within tool-call budget."
