"""Async engine factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    """Create the async engine for a PostgreSQL URL (``postgresql+asyncpg://``).

    Isolation is the PostgreSQL default ``READ COMMITTED``; code that needs more
    takes row locks or sets a stronger level for its own transaction.
    """
    # hide_parameters: bound values (hashes, settings) stay out of exception messages.
    return create_async_engine(
        url, isolation_level="READ COMMITTED", pool_pre_ping=True, hide_parameters=True
    )
