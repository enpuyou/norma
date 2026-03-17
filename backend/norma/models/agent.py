from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Text

from norma.database import Base

if TYPE_CHECKING:
    from norma.models.contract import Contract
    from norma.models.run import Run
    from norma.models.violation import Violation


class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)        # single | orchestrator | subagent
    department: Mapped[str | None] = mapped_column(String)
    owner: Mapped[str | None] = mapped_column(String)

    # Dynamic authority calibration state
    current_tier: Mapped[str] = mapped_column(String, default="restricted")   # restricted | standard | trusted
    trust_score: Mapped[float] = mapped_column(Float, default=0.40)
    clean_run_count: Mapped[int] = mapped_column(Integer, default=0)  # cumulative clean runs (no violations)
    pending_contract_version: Mapped[str | None] = mapped_column(String)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Registry / code-change tracking (Phase 4)
    entry_point: Mapped[str | None] = mapped_column(String)        # relative path to agent.py
    directory: Mapped[str | None] = mapped_column(String)          # parent directory path
    file_hash: Mapped[str | None] = mapped_column(String(32))      # 16-char SHA-256 prefix
    agent_code_version: Mapped[int] = mapped_column(Integer, default=1)  # increments on hash change
    code_status: Mapped[str] = mapped_column(String, default="ok")       # ok | changed | missing
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime)
    agent_type: Mapped[str] = mapped_column(String, default="standard")  # standard | orchestrator | subagent
    parent_agent_id: Mapped[str | None] = mapped_column(String)  # orchestrator that owns this sub-agent
    framework: Mapped[str | None] = mapped_column(String)  # langchain | openai_func | openai_agents | langgraph

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    contracts: Mapped[list["Contract"]] = relationship(back_populates="agent")
    runs: Mapped[list["Run"]] = relationship(back_populates="agent")
    violations: Mapped[list["Violation"]] = relationship(back_populates="agent")
