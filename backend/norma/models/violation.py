from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from norma.database import Base

if TYPE_CHECKING:
    from norma.models.agent import Agent
    from norma.models.run import Run


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), nullable=False)
    policy_rule: Mapped[str] = mapped_column(String, nullable=False)   # e.g. "data.deny: confidential/**"
    action_attempted: Mapped[str] = mapped_column(Text, nullable=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=True)
    event_type: Mapped[str] = mapped_column(
        String, default="access_blocked"
    )  # access_blocked | tier_revocation | access_revoked | output_blocked
    scope: Mapped[str | None] = mapped_column(String)   # e.g. "internal" for access_revoked
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="violations")
    agent: Mapped["Agent"] = relationship(back_populates="violations")
