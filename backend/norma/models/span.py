"""Span — OpenTelemetry-compatible trace record for a single operation within a Run.

Each Span captures one logical unit of work: an LLM call, a tool call,
an agent handoff, or an enforcement check.  Spans form a tree via
parent_span_id, enabling nested trace visualization.

This replaces the flat RunStep model for new instrumentation while
keeping RunStep for backward compatibility with existing data.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from norma.database import Base

if TYPE_CHECKING:
    from norma.models.run import Run
    from norma.models.observability import PromptSnapshot


def _new_span_id() -> str:
    return uuid.uuid4().hex[:16]


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    span_id: Mapped[str] = mapped_column(String(16), nullable=False, default=_new_span_id, index=True)
    trace_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(16))  # None = root span

    # Type: llm_call | tool_call | agent_handoff | enforcement_check | guardrail | session
    span_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)  # tool name, model name, or agent name
    status: Mapped[str] = mapped_column(String(10), default="ok")  # ok | error | blocked

    # Timing
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)

    # I/O (truncated for storage)
    input_data: Mapped[str | None] = mapped_column(Text)   # JSON — prompt, tool args, context
    output_data: Mapped[str | None] = mapped_column(Text)  # JSON — response, tool return

    # Metrics
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    model_name: Mapped[str | None] = mapped_column(String(100), index=True)  # e.g. "gpt-4o", "gpt-4o-mini"

    # Extensible metadata (JSON string)
    # model name, temperature, enforcement result, quality sub-scores, prompt_hash, etc.
    attributes: Mapped[str | None] = mapped_column(Text)  # JSON

    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    run: Mapped["Run"] = relationship(back_populates="spans")
    prompt_snapshots: Mapped[list["PromptSnapshot"]] = relationship(back_populates="span", order_by="PromptSnapshot.id")
