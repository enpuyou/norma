from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComplianceFinding:
    rule_id: str
    standard: str
    severity: str
    passed: bool
    message: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "standard": self.standard,
            "severity": self.severity,
            "passed": self.passed,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass
class ComplianceResult:
    agent_id: str
    findings: list[ComplianceFinding]

    @property
    def passed(self) -> bool:
        return all(f.passed for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        passed_count = sum(1 for f in self.findings if f.passed)
        return {
            "agent_id": self.agent_id,
            "passed": self.passed,
            "summary": {
                "total_rules": len(self.findings),
                "passed_rules": passed_count,
                "failed_rules": len(self.findings) - passed_count,
            },
            "findings": [f.to_dict() for f in self.findings],
        }
