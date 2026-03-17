from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from norma.database import Base


class PromptSnapshot(Base):
    __tablename__ = "prompt_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    span_id: Mapped[str] = mapped_column(
        String, ForeignKey("spans.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String)  # system, user, assistant, tool
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    run = relationship("Run", back_populates="prompt_snapshots")
    span = relationship("Span", back_populates="prompt_snapshots")


class SharedContext(Base):
    __tablename__ = "shared_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    from_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    to_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    context_type: Mapped[str] = mapped_column(String)  # state_key, handoff, memory
    data_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # We don't necessarily need back_populates for this table right now unless we query it bidirectionally.
    from_run = relationship("Run", foreign_keys=[from_run_id])
    to_run = relationship("Run", foreign_keys=[to_run_id])
