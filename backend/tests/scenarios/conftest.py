"""Shared fixtures for scenario tests.

These tests validate features end-to-end against the "real scenario or
placeholder" standard from copilot-instructions.md.

Rules enforced here:
  - NO LLM calls by default (monkeypatched out; token conservative)
  - Each test gets a fresh SQLite DB (no leftover state between tests)
  - Inputs are real code / real text / real tool calls — no hardcoded quality scores
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from httpx import ASGITransport, AsyncClient

from norma.database import Base


@pytest.fixture()
def scenario_db(tmp_path: Path) -> str:
    """
    Create a fresh SQLite database with the full norma schema.

    Returns the sync db_url (sqlite:///...) suitable for NormaAgentSession.
    Each test gets its own file under pytest's tmp_path — no shared state.
    """
    # Ensure all ORM models are registered with Base.metadata before create_all
    import norma.models.agent           # noqa: F401
    import norma.models.attribution     # noqa: F401
    import norma.models.budget          # noqa: F401
    import norma.models.context_metric  # noqa: F401
    import norma.models.contract        # noqa: F401
    import norma.models.run             # noqa: F401
    import norma.models.run_step        # noqa: F401
    import norma.models.span            # noqa: F401
    import norma.models.observability   # noqa: F401
    import norma.models.violation       # noqa: F401

    db_file = tmp_path / "scenario.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db_url


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Disable all LLM calls for scenario tests.

    Patches the cached Settings instance directly (env var patching doesn't
    work because get_settings() is lru_cache'd on first import).

    Individual tests that intentionally exercise LLM paths must opt out:
        @pytest.mark.usefixtures("_no_llm")  — inherits the fixture normally
        OR override by calling get_settings() and patching after setup.
    """
    from norma.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "enable_llm_quality_scoring", False)


@pytest.fixture()
async def async_session_factory(scenario_db: str):
    async_db_url = scenario_db.replace("sqlite:///", "sqlite+aiosqlite:///")
    async_engine = create_async_engine(async_db_url)
    factory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await async_engine.dispose()


@pytest.fixture()
async def db(async_session_factory):
    async with async_session_factory() as session:
        yield session


@pytest.fixture()
async def api_client(async_session_factory, scenario_db: str, monkeypatch: pytest.MonkeyPatch):
    from norma.main import app
    from norma.database import get_db
    from norma.config import get_settings

    async def _override_get_db():
        async with async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    settings = get_settings()
    monkeypatch.setattr(settings, "database_url", scenario_db.replace("sqlite:///", "sqlite+aiosqlite:///"))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.pop(get_db, None)
