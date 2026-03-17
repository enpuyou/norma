"""Quality Scorer — deterministic + optional LLM-as-judge quality evaluation.

Two layers, composable:

1. **Deterministic (always runs)**
   - Output length check (did the agent produce substantial output?)
   - Error keyword detection (did it fail or apologize?)
   - Format compliance (JSON parseable? Required fields present?)
   - Contract scope check (output mentions denied entities?)

2. **LLM-as-judge (when enabled)**
   - Sends output + task description to GPT-4o-mini with a rubric
   - Returns a 0.0–1.0 score with a rationale
   - Feature-flagged behind `enable_llm_quality_scoring` config

Combined score: if LLM is enabled, score = 0.4 * deterministic + 0.6 * llm.
Otherwise, score = deterministic only.

The quality score is a real measurement, not a mock value.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from norma.config import get_settings

settings = get_settings()

# ─── Constants ─────────────────────────────────────────────────────────────────

_ERROR_KEYWORDS = [
    "error", "failed", "could not", "unable", "sorry",
    "cannot", "not permitted", "blocked", "exception",
    "timeout", "timed out", "refused",
]

_QUALITY_RUBRIC = """\
You are a quality evaluator for an AI agent's output. Score the output on a 0.0–1.0 scale.

Scoring rubric:
- 0.0–0.2: Output is empty, nonsensical, or completely wrong
- 0.2–0.4: Output exists but is mostly wrong or unhelpful
- 0.4–0.6: Output is partially correct but has significant issues
- 0.6–0.8: Output is mostly correct and useful, with minor issues
- 0.8–1.0: Output is correct, complete, and well-formatted

Consider:
1. Relevance: Does the output address the task?
2. Completeness: Is key information present?
3. Accuracy: Are there factual errors or hallucinations?
4. Format: Is the output well-structured?

Respond with ONLY a JSON object: {"score": <float>, "rationale": "<brief explanation>"}
"""


@dataclass
class QualityResult:
    """Quality evaluation result with breakdown."""
    score: float                 # 0.0–1.0 final composite
    deterministic_score: float   # 0.0–1.0 from rule checks
    llm_score: float | None      # 0.0–1.0 from LLM judge, or None
    source: str                  # "deterministic" | "composite"
    checks: dict[str, Any]      # individual check results
    rationale: str | None        # LLM rationale if applicable


# ─── Deterministic Checks ──────────────────────────────────────────────────────

def _check_output_length(output: str) -> float:
    """Score based on output substance. Empty or very short = low quality."""
    length = len(output.strip())
    if length == 0:
        return 0.0
    if length < 20:
        return 0.2
    if length < 50:
        return 0.4
    if length < 100:
        return 0.6
    if length < 200:
        return 0.8
    return 1.0


def _check_error_keywords(output: str) -> float:
    """Penalize outputs containing error/failure indicators."""
    text = output.lower()
    matches = sum(1 for kw in _ERROR_KEYWORDS if kw in text)
    if matches == 0:
        return 1.0
    if matches == 1:
        return 0.6
    if matches == 2:
        return 0.3
    return 0.1


def _check_format_compliance(output: str, expected_format: str | None = None) -> float:
    """Check if output meets expected format requirements."""
    if not expected_format:
        # No format requirement — pass
        return 0.85

    if expected_format == "json":
        try:
            json.loads(output)
            return 1.0
        except (json.JSONDecodeError, ValueError):
            # Check if it contains JSON-like structure
            if "{" in output and "}" in output:
                return 0.5
            return 0.2

    if expected_format == "markdown":
        has_headers = bool(re.search(r"^#+\s", output, re.MULTILINE))
        has_lists = bool(re.search(r"^[-*]\s", output, re.MULTILINE))
        if has_headers or has_lists:
            return 1.0
        return 0.6

    return 0.85  # unknown format, neutral


def _check_contract_scope(output: str, contract: dict[str, Any] | None = None) -> float:
    """Check if output violates contract deny patterns."""
    if not contract:
        return 1.0

    deny_patterns = (
        contract.get("output_constraints", {})
        .get("deny_patterns", [])
    )

    text = output.lower()
    for pattern_name in deny_patterns:
        # Check for common PII patterns
        if pattern_name == "pii_regex" and re.search(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b", output):
            return 0.1
        if pattern_name == "credential_regex" and re.search(
            r"(?i)(password|api_key|secret|token)\s*[:=]\s*\S+", output
        ):
            return 0.1
        if pattern_name == "credit_card_regex" and re.search(r"\b(?:\d[ -]?){13,16}\b", output):
            return 0.1

    return 1.0


def score_deterministic(
    output: str,
    *,
    contract: dict[str, Any] | None = None,
    expected_format: str | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    Run all deterministic quality checks.

    Returns (score, checks_detail).
    """
    checks = {
        "output_length": _check_output_length(output),
        "error_keywords": _check_error_keywords(output),
        "format_compliance": _check_format_compliance(output, expected_format),
        "contract_scope": _check_contract_scope(output, contract),
    }

    # Weighted average — contract_scope is a hard gate
    if checks["contract_scope"] < 0.5:
        # PII/credential leak = automatic low score
        score = checks["contract_scope"]
    else:
        score = (
            checks["output_length"] * 0.25
            + checks["error_keywords"] * 0.35
            + checks["format_compliance"] * 0.20
            + checks["contract_scope"] * 0.20
        )

    return round(min(1.0, max(0.0, score)), 4), checks


# ─── LLM-as-Judge ─────────────────────────────────────────────────────────────

async def score_with_llm(
    output: str,
    task_description: str = "",
) -> tuple[float, str]:
    """
    Call GPT-4o-mini to evaluate output quality.
    Returns (score, rationale).
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    user_msg = f"Task: {task_description}\n\nAgent output:\n{output[:2000]}"

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _QUALITY_RUBRIC},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        text = response.choices[0].message.content or ""
        # Parse JSON response
        match = re.search(r"\{[^}]+\}", text)
        if match:
            data = json.loads(match.group())
            score = float(data.get("score", 0.5))
            rationale = data.get("rationale", "")
            return round(min(1.0, max(0.0, score)), 4), rationale
    except Exception:
        pass

    return 0.5, "LLM evaluation failed — defaulting to 0.5"


# ─── Public API ────────────────────────────────────────────────────────────────

async def evaluate_quality(
    output: str,
    *,
    task_description: str = "",
    contract: dict[str, Any] | None = None,
    expected_format: str | None = None,
) -> QualityResult:
    """
    Run the full quality evaluation pipeline.

    - Always runs deterministic checks
    - Runs LLM-as-judge when `enable_llm_quality_scoring` is True and API key is set
    - Returns composite score with full breakdown
    """
    det_score, checks = score_deterministic(
        output,
        contract=contract,
        expected_format=expected_format,
    )

    llm_score = None
    rationale = None
    source = "deterministic"

    if settings.enable_llm_quality_scoring and settings.openai_api_key:
        llm_score, rationale = await score_with_llm(output, task_description)
        # Composite: 40% deterministic + 60% LLM
        final_score = round(det_score * 0.4 + llm_score * 0.6, 4)
        source = "composite"
    else:
        final_score = det_score

    return QualityResult(
        score=final_score,
        deterministic_score=det_score,
        llm_score=llm_score,
        source=source,
        checks=checks,
        rationale=rationale,
    )


def evaluate_quality_sync(
    output: str,
    *,
    task_description: str = "",
    contract: dict[str, Any] | None = None,
    expected_format: str | None = None,
) -> QualityResult:
    """
    Synchronous wrapper for evaluate_quality.
    Uses deterministic scoring only (LLM scoring requires async).
    """
    det_score, checks = score_deterministic(
        output,
        contract=contract,
        expected_format=expected_format,
    )

    return QualityResult(
        score=det_score,
        deterministic_score=det_score,
        llm_score=None,
        source="deterministic",
        checks=checks,
        rationale=None,
    )
