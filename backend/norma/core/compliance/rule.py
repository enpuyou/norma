from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from norma.models.contract import Contract
from norma.models.run import Run
from norma.models.span import Span

from norma.core.compliance.result import ComplianceFinding


@dataclass
class ComplianceContext:
    agent_id: str
    runs: list[Run]
    spans: list[Span]
    active_contract: Contract | None = None


class ComplianceRule(Protocol):
    rule_id: str
    standard: str

    def evaluate(self, ctx: ComplianceContext) -> ComplianceFinding:
        ...
