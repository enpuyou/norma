from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from norma.database import Base

if TYPE_CHECKING:
    from norma.models.run import Run


class Outcome(Base):
    __tablename__ = "outcomes"

    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), primary_key=True)
    deterministic_score: Mapped[float | None] = mapped_column(Float)
    llm_score: Mapped[float | None] = mapped_column(Float)
    human_score: Mapped[float | None] = mapped_column(Float)
    confidence_interval_low: Mapped[float | None] = mapped_column(Float)
    confidence_interval_high: Mapped[float | None] = mapped_column(Float)
    assessment_method: Mapped[str] = mapped_column(
        String, default="deterministic"
    )  # deterministic | llm | human | hybrid

    run: Mapped["Run"] = relationship(back_populates="outcome")
