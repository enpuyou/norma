from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from norma.database import Base

if TYPE_CHECKING:
    from norma.models.run import Run


class ContextMetric(Base):
    __tablename__ = "context_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    subagent_id: Mapped[str] = mapped_column(String, nullable=False)
    tokens_available: Mapped[int | None] = mapped_column(Integer)
    tokens_sent: Mapped[int | None] = mapped_column(Integer)
    utilization_ratio: Mapped[float | None] = mapped_column(Float)
    routing_rules_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    # JSON-serialised routing policy snapshot
    routing_policy_json: Mapped[str | None] = mapped_column(Text)
    # Approximated by n-gram overlap of output vs. sent context (not semantic)
    output_overlap_ratio: Mapped[float | None] = mapped_column(Float)

    run: Mapped["Run"] = relationship(back_populates="context_metrics")
