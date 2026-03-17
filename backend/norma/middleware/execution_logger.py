"""Execution Tree Logger — records parent-child run relationships and per-node telemetry."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class ExecutionLogger:
    """
    Logs every run node with:
      - parent_run_id for tree structure
      - input/output token counts
      - cost estimate
      - latency
      - quality score (if available post-run)
      - enforcement events
    """

    def __init__(self, agent_id: str, parent_run_id: int | None = None) -> None:
        self.agent_id = agent_id
        self.parent_run_id = parent_run_id
        self.started_at: datetime | None = None
        self.events: list[dict[str, Any]] = []

    def start(self) -> None:
        self.started_at = datetime.utcnow()

    def log_enforcement_event(self, event: dict[str, Any]) -> None:
        self.events.append({"type": "enforcement", **event})

    def log_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.events.append({"type": "tokens", "input": input_tokens, "output": output_tokens})

    def finalize(self, quality_score: float | None = None) -> dict[str, Any]:
        """Return a run record ready for DB insertion."""
        # TODO Phase 2: flush to DB
        return {
            "agent_id": self.agent_id,
            "parent_run_id": self.parent_run_id,
            "events": self.events,
            "quality_score": quality_score,
            "started_at": self.started_at,
        }
