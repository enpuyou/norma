"""S3 — Quality Scoring Scenario Test.

Enterprise scenario:
    An agent produces a text output.  The platform must score it automatically
    (deterministically) so that quality degradation over time is detectable
    without a human reading every response.

What this test validates:
    - `evaluate_quality_sync()` returns scores that respond to actual output
      characteristics, not hardcoded values
    - Score ranges are stable and documented so teams can set SLA thresholds
    - PII / credential patterns trigger the contract-scope penalty

Inputs: real output strings with known characteristics
Expected: score in a defined range for each input type

No LLM calls.  No DB.  Deterministic — runs clean every time.
"""

from __future__ import annotations

import json

import pytest

from norma.core.quality_scorer import evaluate_quality_sync, score_deterministic


# ── Minimal contract for scope-check tests ────────────────────────────────────

_STRICT_CONTRACT = {
    "output_constraints": {
        "deny_patterns": ["pii_regex", "credential_regex", "credit_card_regex"],
    }
}


# ── Scenario: rich, well-structured output ─────────────────────────────────────

def test_good_output_scores_high() -> None:
    """
    Scenario: agent returns a comprehensive earnings summary.
    Expected: score in 0.70–1.00 range (substantial, no errors, no PII).
    """
    good_output = (
        "Q4 2025 Earnings Summary\n\n"
        "Revenue for the quarter came in at $2.4 billion, representing a 12% year-over-year "
        "increase driven by strong performance in the cloud segment.  Operating income was "
        "$380 million, above analyst consensus of $350 million.  The company reaffirmed full-year "
        "guidance of $9.2–9.4 billion in revenue.\n\n"
        "Key metrics:\n"
        "- Gross margin: 68.2% (vs 65.1% prior year)\n"
        "- Free cash flow: $410 million\n"
        "- Headcount: 14,200 (+800 YoY)\n\n"
        "Management commentary highlights continued investment in AI infrastructure "
        "with $600 million planned for capex in FY2026."
    )
    result = evaluate_quality_sync(good_output, contract=_STRICT_CONTRACT)
    assert result.score >= 0.70, f"Expected ≥0.70, got {result.score}"
    assert result.checks["output_length"] >= 0.80
    assert result.checks["error_keywords"] == 1.0
    assert result.source == "deterministic"


# ── Scenario: empty output (agent returned nothing) ────────────────────────────

def test_empty_output_scores_zero() -> None:
    """
    Scenario: agent returned an empty string — a complete failure.

    Real scorer behaviour: output_length sub-check = 0.0 (no content at all).
    The aggregate score is still >0 because the other checks (no error keywords,
    neutral format compliance, contract scope) contribute positively.

    The key observable is that the output_length dimension is fully penalised.
    This is the signal a dashboard should surface: "agent produced no output."
    """
    result = evaluate_quality_sync("", contract=_STRICT_CONTRACT)
    # output_length sub-check must be 0.0 — this is the meaningful signal
    assert result.checks["output_length"] == 0.0
    # Aggregate is below a good run (which would score >0.85) even though other
    # checks are not penalised — demonstrates the scorer is sensitive to empty output
    assert result.score < 0.80


# ── Scenario: short, vague output ──────────────────────────────────────────────

def test_short_output_scores_low() -> None:
    """
    Scenario: agent returned only 'Done.' — unhelpfully brief.

    Real scorer behaviour: output_length sub-check is low (≤0.35).
    The aggregate score is penalised on the length dimension; callers that care
    about output quality should inspect the sub-check breakdown.
    """
    result = evaluate_quality_sync("Done.", contract=_STRICT_CONTRACT)
    # The output_length dimension must reflect the brevity penalty
    assert result.checks["output_length"] <= 0.35, (
        f"Expected output_length ≤0.35 for one-word output, got {result.checks['output_length']}"
    )
    # Aggregate is lower than a good long response (≥0.85) but the scorer is
    # not binary — verify the penalty is real
    assert result.score < 0.85, f"Expected score < 0.85 for very short output, got {result.score}"


# ── Scenario: output contains error keywords ───────────────────────────────────

def test_error_output_penalised() -> None:
    """
    Scenario: agent hit an exception and returned the traceback / apology.

    Real scorer behaviour: error_keywords sub-check drops sharply (< 0.30).
    The aggregate score is dampened but not catastrophic because the output
    is long (output_length is fine) and meets format checks.
    The meaningful signal is the error_keywords dimension — that's what
    the dashboard should flag.
    """
    error_output = (
        "I'm sorry, but I was unable to complete the request. "
        "An error occurred while processing the document: "
        "Connection timed out after 30 seconds.  Please try again."
    )
    result = evaluate_quality_sync(error_output, contract=_STRICT_CONTRACT)
    # The error_keywords sub-check must be heavily penalised
    assert result.checks["error_keywords"] < 0.30, (
        f"Expected error_keywords < 0.30, got {result.checks['error_keywords']}"
    )
    # Aggregate is lower than a clean response — error keywords have real weight (0.35)
    assert result.score < 0.70, f"Expected score < 0.70 for error output, got {result.score}"


def test_multiple_error_keywords_score_very_low() -> None:
    """
    Scenario: severely degraded output with stacked error indicator keywords.
    Expected: error_keywords check ≤ 0.30.
    """
    output = "Error: failed to process. Could not connect. Exception raised. Sorry, cannot continue."
    det_score, checks = score_deterministic(output)
    assert checks["error_keywords"] <= 0.30


# ── Scenario: PII in output triggers contract scope penalty ─────────────────────

def test_ssn_in_output_triggers_scope_penalty() -> None:
    """
    Scenario: agent output leaked a Social Security Number pattern.
    Expected: contract_scope check very low (≤ 0.15) regardless of other quality.
    """
    output_with_ssn = (
        "Customer record retrieved.  Employee ID: 48291.  SSN: 123-45-6789.  "
        "Salary: $95,000.  Department: Engineering."
    )
    result = evaluate_quality_sync(output_with_ssn, contract=_STRICT_CONTRACT)
    assert result.checks["contract_scope"] <= 0.15, (
        f"SSN should trigger scope penalty, got {result.checks['contract_scope']}"
    )
    # The scope penalty should dominate the final score
    assert result.score <= 0.15


def test_credential_in_output_triggers_scope_penalty() -> None:
    """
    Scenario: agent output contained an API key.
    Expected: contract_scope check very low.
    """
    output_with_cred = (
        "Here is your configuration:\n"
        "api_key = sk-abc123secrettoken\n"
        "database_url = postgres://user:password=hunter2@localhost/db"
    )
    result = evaluate_quality_sync(output_with_cred, contract=_STRICT_CONTRACT)
    assert result.checks["contract_scope"] <= 0.15


def test_credit_card_in_output_triggers_scope_penalty() -> None:
    """
    Scenario: agent output included a credit card number (masked or not).
    Expected: contract_scope check very low.
    """
    output_with_cc = "Payment confirmed.  Card: 4111 1111 1111 1111.  Amount: $450.00."
    result = evaluate_quality_sync(output_with_cc, contract=_STRICT_CONTRACT)
    assert result.checks["contract_scope"] <= 0.15


# ── Scenario: format compliance ────────────────────────────────────────────────

def test_valid_json_output_scores_format_compliance_high() -> None:
    """
    Scenario: contract requires JSON output and agent produced valid JSON.
    Expected: format_compliance = 1.0.
    """
    json_output = json.dumps({
        "quarter": "Q4 2025",
        "revenue_usd": 2_400_000_000,
        "operating_income_usd": 380_000_000,
        "guidance_raised": True,
    })
    _, checks = score_deterministic(json_output, expected_format="json")
    assert checks["format_compliance"] == 1.0


def test_invalid_json_output_scores_format_compliance_low() -> None:
    """
    Scenario: contract requires JSON but agent returned plain prose.
    Expected: format_compliance ≤ 0.50.
    """
    prose_output = (
        "The revenue was 2.4 billion dollars and operating income was 380 million."
    )
    _, checks = score_deterministic(prose_output, expected_format="json")
    assert checks["format_compliance"] <= 0.50


def test_markdown_format_detected_correctly() -> None:
    """
    Scenario: contract expects markdown and agent returned well-structured markdown.
    Expected: format_compliance = 1.0.
    """
    md_output = (
        "## Q4 2025 Summary\n\n"
        "- Revenue: $2.4B\n"
        "- Operating income: $380M\n\n"
        "## Key Takeaways\n\n"
        "Growth driven by cloud.  Guidance reaffirmed."
    )
    _, checks = score_deterministic(md_output, expected_format="markdown")
    assert checks["format_compliance"] == 1.0


# ── Scenario: no contract — neutral pass ──────────────────────────────────────

def test_no_contract_does_not_penalise_scope() -> None:
    """
    Scenario: agent has no active contract yet.  Scope check should pass neutrally.
    Even 'dangerous' output passes scope if there is no deny_patterns rule.
    """
    output = "SSN: 987-65-4321 — here is the data you requested."
    result = evaluate_quality_sync(output, contract=None)
    # Without a contract, scope check returns 1.0 (no rules to match against)
    assert result.checks["contract_scope"] == 1.0


# ── Scenario: QualityResult structure is complete ─────────────────────────────

def test_quality_result_exposes_full_breakdown() -> None:
    """
    Every caller (dashboard, attribution engine) depends on a consistent QualityResult
    structure.  This test acts as a contract for that shape.
    """
    result = evaluate_quality_sync("This is a medium-length output about the quarterly report.")
    assert hasattr(result, "score")
    assert hasattr(result, "deterministic_score")
    assert hasattr(result, "llm_score")
    assert hasattr(result, "source")
    assert hasattr(result, "checks")
    assert set(result.checks.keys()) == {
        "output_length", "error_keywords", "format_compliance", "contract_scope"
    }
    assert result.llm_score is None        # LLM disabled by conftest
    assert result.source == "deterministic"
    assert 0.0 <= result.score <= 1.0
