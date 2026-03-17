from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from norma.database import Base

if TYPE_CHECKING:
    from norma.models.agent import Agent


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)          # e.g. "1.0", "2.0"
    yaml_content: Mapped[str] = mapped_column(Text, nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[str | None] = mapped_column(String)
    approved_by: Mapped[str | None] = mapped_column(String)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agent: Mapped["Agent"] = relationship(back_populates="contracts")
    versions: Mapped[list["ContractVersion"]] = relationship(
        back_populates="contract",
        cascade="all, delete-orphan",
    )


class ContractVersion(Base):
    __tablename__ = "contract_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), nullable=False)
    diff_json: Mapped[str | None] = mapped_column(Text)   # JSON-serialised diff
    changed_by: Mapped[str | None] = mapped_column(String)
    approved_by: Mapped[str | None] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    contract: Mapped["Contract"] = relationship(back_populates="versions")
