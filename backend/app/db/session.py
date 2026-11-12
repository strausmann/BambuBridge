"""Async session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.errors import CONNECTION_ERRORS, DatabaseUnavailableError


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory; objects stay usable after commit."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def connected(session: AsyncSession) -> AsyncSession:
    """Acquire the connection now; an unreachable database -> ``DatabaseUnavailableError``.

    Translating here, at the connection boundary, keeps unrelated ``OSError`` raised later
    in a request a plain 500 instead of a misleading 503.
    """
    try:
        await session.connection()
    except CONNECTION_ERRORS as exc:
        raise DatabaseUnavailableError from exc
    return session


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one connected session per request from the app's factory.

    The connection is acquired up front, which also starts the transaction. Handlers
    therefore finish their work with ``await session.commit()`` (or ``rollback()``) and
    use ``session.begin_nested()`` for a savepoint, never ``session.begin()``, which
    raises because a transaction is already in progress.
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield await connected(session)
