from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from norma.database import Base

if TYPE_CHECKING:
    from norma.models.agent import Agent
    from norma.models.context_metric import ContextMetric
    from norma.models.outcome import Outcome
    from norma.models.run_step import RunStep
    from norma.models.span import Span
    from norma.models.violation import Violation
    from norma.models.observability import PromptSnapshot, SharedContext


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), nullable=False)
    parent_run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))   # multi-agent tree
    initiated_by: Mapped[str | None] = mapped_column(String)  # "user" | "api" | "orchestrator:<agent-id>"
    contract_version: Mapped[str | None] = mapped_column(String)
    session_id: Mapped[str | None] = mapped_column(String)  # groups multi-turn conversation runs

    # Telemetry
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    # Outcome
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_rationale: Mapped[str | None] = mapped_column(Text)   # LLM judge explanation
    quality_breakdown: Mapped[str | None] = mapped_column(Text)   # JSON: per-check scores
    trust_score_after: Mapped[float | None] = mapped_column(Float)  # trust score immediately after this run
    completion_status: Mapped[str] = mapped_column(
        String, default="success"
    )  # success | failed | timeout | escalated

    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="runs")
    children: Mapped[list["Run"]] = relationship(
        "Run",
        back_populates="parent",
        foreign_keys="[Run.parent_run_id]",
    )
    parent: Mapped["Run | None"] = relationship(
        "Run",
        back_populates="children",
        foreign_keys="[Run.parent_run_id]",
        remote_side="Run.id",
    )
    violations: Mapped[list["Violation"]] = relationship(back_populates="run")
    outcome: Mapped["Outcome | None"] = relationship(back_populates="run", uselist=False)
    context_metrics: Mapped[list["ContextMetric"]] = relationship(back_populates="run")
    steps: Mapped[list["RunStep"]] = relationship(back_populates="run", order_by="RunStep.step_index")
    spans: Mapped[list["Span"]] = relationship(back_populates="run", order_by="Span.id")
    prompt_snapshots: Mapped[list["PromptSnapshot"]] = relationship(back_populates="run", order_by="PromptSnapshot.id")
