"""Explicit SQLAlchemy session ownership; never creates a schema at startup."""
from collections.abc import AsyncIterator
from hashlib import sha256

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_sessions(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Return an async engine and per-unit-of-work session factory."""
    engine = create_async_engine(url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def database(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request, rolled back on any raised exception."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.sessions
    async with factory() as session, session.begin():
        yield session


async def lock_scope(session: AsyncSession, scope: str) -> None:
    """Serialize a business scope without UPDATE rights on immutable source rows.

    Stable signed 64-bit keys fit PostgreSQL's advisory-lock API. A hash collision
    only serializes unrelated transactions; it cannot bypass the protected check.
    The lock is released automatically at transaction commit or rollback.
    """
    key = int.from_bytes(sha256(scope.encode("utf-8")).digest()[:8], "big", signed=True)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
