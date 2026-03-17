from __future__ import annotations

import json

from norma.core.compliance.result import ComplianceFinding
from norma.core.compliance.rule import ComplianceContext


class ModelDriftRule:
    rule_id = "MODEL-DRIFT"
    standard = "Model Governance"

    def evaluate(self, ctx: ComplianceContext) -> ComplianceFinding:
        llm_spans = [s for s in ctx.spans if s.span_type == "llm_call"]
        prompt_hashes: set[str] = set()
        for s in llm_spans:
            if not s.attributes:
                continue
            try:
                attrs = json.loads(s.attributes)
            except Exception:
                attrs = {}
            if isinstance(attrs, dict) and attrs.get("prompt_hash"):
                prompt_hashes.add(str(attrs["prompt_hash"]))

        recent_runs = sorted(ctx.runs, key=lambda r: r.id)[-10:]
        quality_values = [r.quality_score for r in recent_runs if r.quality_score is not None]
        quality_drop = False
        if len(quality_values) >= 6:
            half = len(quality_values) // 2
            before = sum(quality_values[:half]) / max(1, half)
            after = sum(quality_values[half:]) / max(1, len(quality_values) - half)
            quality_drop = (before - after) > 0.2

        passed = not (len(prompt_hashes) >= 3 and quality_drop)
        return ComplianceFinding(
            rule_id=self.rule_id,
            standard=self.standard,
            severity="medium",
            passed=passed,
            message="No major drift detected" if passed else "Possible prompt/model drift detected",
            evidence=[f"prompt_hashes:{len(prompt_hashes)}", f"quality_drop:{quality_drop}"],
        )
