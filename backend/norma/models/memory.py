from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from norma.database import Base


class MemoryStore(Base):
    """Topic-keyed run history injection (TTL-based, not semantic memory)."""
    __tablename__ = "memory_store"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.agent_id"), nullable=False)
    topic_key: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=86400)   # 24 h default
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_accessed: Mapped[datetime | None] = mapped_column(DateTime)
