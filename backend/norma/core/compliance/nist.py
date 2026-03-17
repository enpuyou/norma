from __future__ import annotations

from norma.core.compliance.result import ComplianceFinding
from norma.core.compliance.rule import ComplianceContext


class NISTMapRule:
    rule_id = "NIST-MAP"
    standard = "NIST AI RMF"

    def evaluate(self, ctx: ComplianceContext) -> ComplianceFinding:
        passed = ctx.active_contract is not None
        return ComplianceFinding(
            rule_id=self.rule_id,
            standard=self.standard,
            severity="high",
            passed=passed,
            message="Active contract present" if passed else "No active contract found",
            evidence=[f"contract:{ctx.active_contract.id}"] if ctx.active_contract else [],
        )


class NISTMeasureRule:
    rule_id = "NIST-MEASURE"
    standard = "NIST AI RMF"

    def evaluate(self, ctx: ComplianceContext) -> ComplianceFinding:
        measurable_runs = [r for r in ctx.runs if r.quality_score is not None and r.cost_usd is not None]
        passed = len(measurable_runs) > 0
        return ComplianceFinding(
            rule_id=self.rule_id,
            standard=self.standard,
            severity="medium",
            passed=passed,
            message="Runs include measurable quality and cost" if passed else "No measurable quality/cost runs",
            evidence=[f"run:{r.id}" for r in measurable_runs[:10]],
        )


class NISTManageRule:
    rule_id = "NIST-MANAGE"
    standard = "NIST AI RMF"

    def evaluate(self, ctx: ComplianceContext) -> ComplianceFinding:
        blocked = [s for s in ctx.spans if s.status == "blocked"]
        passed = len(blocked) == 0
        return ComplianceFinding(
            rule_id=self.rule_id,
            standard=self.standard,
            severity="medium",
            passed=passed,
            message="No blocked operations" if passed else "Blocked operations detected; mitigation required",
            evidence=[s.span_id for s in blocked[:10]],
        )
