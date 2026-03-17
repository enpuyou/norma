from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from norma.config import get_settings

settings = get_settings()


def _sync_url_from_async(url: str) -> str:
    if url.startswith("sqlite+aiosqlite"):
        return url.replace("sqlite+aiosqlite", "sqlite", 1)
    if url.startswith("postgresql+asyncpg"):
        return url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
    return url

# ── Async engine (used by FastAPI / seed) ─────────────────────────────────────
engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Sync engine (used by agent monitoring callbacks — runs outside event loop) ─
_sync_db_url = _sync_url_from_async(settings.database_url)
sync_engine = create_engine(_sync_db_url, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables on startup (dev/test only — use Alembic in prod).

    Also applies lightweight column migrations for new columns added to existing
    tables.  SQLAlchemy create_all only creates missing tables, not missing columns,
    so we handle that here for the common case of adding a nullable/default column.
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _apply_schema_migrations(conn)


async def _apply_schema_migrations(conn) -> None:  # type: ignore[type-arg]
    """Add any model columns that are missing from existing DB tables.

    Safe to call on every startup — checks PRAGMA table_info before altering.
    Only handles additive changes (new columns); never drops or renames.
    """
    from sqlalchemy import text

    # Lightweight additive migrations are currently implemented for SQLite.
    if conn.dialect.name != "sqlite":
        return

    # Each entry: (table_name, column_name, sqlite_type_and_default)
    _MIGRATIONS = [
        ("agents", "clean_run_count", "INTEGER NOT NULL DEFAULT 0"),
        # Phase 4: registry versioning
        ("agents", "entry_point",        "TEXT"),
        ("agents", "directory",          "TEXT"),
        ("agents", "file_hash",          "TEXT"),
        ("agents", "agent_code_version", "INTEGER NOT NULL DEFAULT 1"),
        ("agents", "code_status",        "TEXT NOT NULL DEFAULT 'ok'"),
        ("agents", "last_seen_at",       "DATETIME"),
        # Phase 6: multi-agent type
        ("agents", "agent_type",         "TEXT NOT NULL DEFAULT 'standard'"),
        ("agents", "framework",          "TEXT"),
        # Run parent tracking
        ("runs", "parent_run_id", "INTEGER"),
        # Contract human-readable summary
        ("contracts", "summary_text", "TEXT"),
        # Run initiator tracking
        ("runs", "initiated_by", "TEXT"),
        # Sub-agent parent tracking
        ("agents", "parent_agent_id", "TEXT"),
        # Phase 5: run step trace (table created by create_all if missing)
        # Phase 1 v2: span-based tracing + session tracking
        ("runs", "session_id", "TEXT"),
        # Quality scoring enrichment: LLM rationale + per-check breakdown
        ("runs", "quality_rationale", "TEXT"),
        ("runs", "quality_breakdown", "TEXT"),
    ]

    for table, col, col_def in _MIGRATIONS:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        existing_cols = {row[1] for row in result.fetchall()}
        if col not in existing_cols:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
            # Log via print since structlog may not be configured at DB init time
            print(f"[norma] schema migration: added column {table}.{col}")


# Import all models at module level so SQLAlchemy registers them with metadata.
# Must be at the bottom to avoid circular imports (models import Base from here).
from norma.models import *  # noqa: F401, F403
