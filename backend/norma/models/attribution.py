from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from norma.database import Base

if TYPE_CHECKING:
    from norma.models.run import Run


class AttributionReport(Base):
    __tablename__ = "attribution_reports"

    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    most_likely_node: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON: [{"node": str, "confidence": float}, ...]
    alternative_hypotheses_json: Mapped[str | None] = mapped_column(Text)

    run: Mapped["Run"] = relationship()
