"""RunStep — per-tool-call trace record for a single Run.

Each RunStep captures one tool invocation: what was called, with what input,
what came back, how long it took, and whether norma blocked it.
These records power the Run Detail View in the dashboard.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from norma.database import Base

if TYPE_CHECKING:
    from norma.models.run import Run


class RunStep(Base):
    __tablename__ = "run_steps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    input_text: Mapped[str | None] = mapped_column(Text)
    output_text: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_rule: Mapped[str | None] = mapped_column(String)  # rule that triggered block
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="steps")
