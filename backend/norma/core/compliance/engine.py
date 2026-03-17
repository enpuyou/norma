from __future__ import annotations

from norma.core.compliance.drift import ModelDriftRule
from norma.core.compliance.eu_ai_act import (
    EUAIActArt17RiskManagementRule,
    EUAIActArt18LoggingRule,
    EUAIActArt19TransparencyRule,
)
from norma.core.compliance.nist import NISTManageRule, NISTMapRule, NISTMeasureRule
from norma.core.compliance.owasp import (
    OWASPLLM01PromptInjectionRule,
    OWASPLLM02InsecureOutputRule,
    OWASPLLM06SensitiveDisclosureRule,
    OWASPLLM08ExcessiveAgencyRule,
    OWASPLLM09OverrelianceRule,
)
from norma.core.compliance.result import ComplianceResult
from norma.core.compliance.rule import ComplianceContext, ComplianceRule


class ComplianceEngine:
    def __init__(self, rules: list[ComplianceRule] | None = None) -> None:
        self.rules = rules or [
            OWASPLLM01PromptInjectionRule(),
            OWASPLLM02InsecureOutputRule(),
            OWASPLLM06SensitiveDisclosureRule(),
            OWASPLLM08ExcessiveAgencyRule(),
            OWASPLLM09OverrelianceRule(),
            NISTMapRule(),
            NISTMeasureRule(),
            NISTManageRule(),
            EUAIActArt17RiskManagementRule(),
            EUAIActArt18LoggingRule(),
            EUAIActArt19TransparencyRule(),
            ModelDriftRule(),
        ]

    def evaluate(self, ctx: ComplianceContext) -> ComplianceResult:
        findings = [rule.evaluate(ctx) for rule in self.rules]
        return ComplianceResult(agent_id=ctx.agent_id, findings=findings)
