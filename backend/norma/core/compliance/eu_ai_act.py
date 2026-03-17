from __future__ import annotations

import json

from norma.core.compliance.result import ComplianceFinding
from norma.core.compliance.rule import ComplianceContext


class EUAIActArt17RiskManagementRule:
    rule_id = "EU-AIACT-ART17"
    standard = "EU AI Act"

    def evaluate(self, ctx: ComplianceContext) -> ComplianceFinding:
        checks = [s for s in ctx.spans if s.span_type == "enforcement_check"]
        passed = len(checks) > 0
        return ComplianceFinding(
            rule_id=self.rule_id,
            standard=self.standard,
            severity="high",
            passed=passed,
            message="Risk controls evidenced by enforcement checks" if passed else "No enforcement checks found",
            evidence=[s.span_id for s in checks[:10]],
        )


class EUAIActArt18LoggingRule:
    rule_id = "EU-AIACT-ART18"
    standard = "EU AI Act"

    def evaluate(self, ctx: ComplianceContext) -> ComplianceFinding:
        passed = len(ctx.spans) > 0
        return ComplianceFinding(
            rule_id=self.rule_id,
            standard=self.standard,
            severity="high",
            passed=passed,
            message="Trace logs present" if passed else "No trace logs found",
            evidence=[s.span_id for s in ctx.spans[:10]],
        )


class EUAIActArt19TransparencyRule:
    rule_id = "EU-AIACT-ART19"
    standard = "EU AI Act"

    def evaluate(self, ctx: ComplianceContext) -> ComplianceFinding:
        llm_spans = [s for s in ctx.spans if s.span_type == "llm_call"]
        with_prompt_hash = 0
        for s in llm_spans:
            if not s.attributes:
                continue
            try:
                attrs = json.loads(s.attributes)
            except Exception:
                attrs = {}
            if isinstance(attrs, dict) and attrs.get("prompt_hash"):
                with_prompt_hash += 1
        passed = len(llm_spans) == 0 or with_prompt_hash == len(llm_spans)
        return ComplianceFinding(
            rule_id=self.rule_id,
            standard=self.standard,
            severity="medium",
            passed=passed,
            message="LLM spans include prompt traceability" if passed else "Some LLM spans missing prompt_hash",
            evidence=[f"llm_spans:{len(llm_spans)}", f"with_prompt_hash:{with_prompt_hash}"],
        )
