"""SQLAlchemy async engine + session factory.

We only persist OPERATIONAL state — session rows and the event-stream
history needed for SSE replay. Vera holds the audit truth (every
recorded action, every approval decision, every routed/routing_blocked
record lives on Vera's cryptographic chain).
"""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from simulator.customers.triageguard.backend.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all backend models."""


# Engine is created lazily so tests can override the URL before first use.
_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _ensure_engine():
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.db_url, future=True)
        _sessionmaker = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine, _sessionmaker


async def init_db() -> None:
    """Create tables. Idempotent."""
    # Late-import models so SQLAlchemy registers them on Base.metadata.
    from simulator.customers.triageguard.backend import models  # noqa: F401

    engine, _ = _ensure_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_db() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields an `AsyncSession`."""
    _, sm = _ensure_engine()
    assert sm is not None
    async with sm() as session:
        yield session


def reset_engine_for_tests() -> None:
    """Drop the cached engine/sessionmaker so the next call re-reads
    settings. Used by the smoke test to swap the DB URL before any model
    touches the engine."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None
