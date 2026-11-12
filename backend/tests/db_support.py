"""Helpers for the shared test database (used by ``conftest.py`` and the db tests)."""

from __future__ import annotations

import os
import secrets

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

TEST_DATABASE_URL_ENV = "BAMBUBRIDGE_TEST_DATABASE_URL"
MISSING_URL_MESSAGE = (
    f"{TEST_DATABASE_URL_ENV} is not set. The test suite needs a PostgreSQL 18 server; "
    "SQLite is not supported. Start one with\n"
    "  docker run -d --rm -p 55432:5432 -e POSTGRES_PASSWORD=test postgres:18.6-trixie\n"
    f"and export {TEST_DATABASE_URL_ENV}="
    "postgresql+asyncpg://postgres:test@localhost:55432/postgres"
)


def admin_url() -> str:
    """URL of the maintenance database from which per-run databases are created."""
    value = os.environ.get(TEST_DATABASE_URL_ENV, "")
    if not value:
        raise RuntimeError(MISSING_URL_MESSAGE)
    return value


def unique_database_name(kind: str) -> str:
    """Return ``bb_<kind>_<pid>_<worker>_<random>`` for a throw-away database.

    The process id alone is not unique: in a container every run tends to get the same
    one, and two runs may share a server. The random part separates runs, the
    pytest-xdist worker id (``main`` without xdist) makes parallel workers readable.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    return f"bb_{kind}_{os.getpid()}_{worker}_{secrets.token_hex(4)}"


def url_for_database(base_url: str, database: str) -> str:
    """Return ``base_url`` pointing at ``database`` (password kept)."""
    return make_url(base_url).set(database=database).render_as_string(hide_password=False)


async def truncate_all(engine: AsyncEngine) -> None:
    """``TRUNCATE ... RESTART IDENTITY CASCADE`` every table except Alembic's bookkeeping."""
    async with engine.begin() as conn:
        names = (
            await conn.scalars(
                text(
                    "select tablename from pg_tables "
                    "where schemaname = 'public' and tablename <> 'alembic_version'"
                )
            )
        ).all()
        if not names:
            return
        quote = engine.dialect.identifier_preparer.quote
        listed = ", ".join(quote(n) for n in names)
        await conn.execute(text(f"TRUNCATE {listed} RESTART IDENTITY CASCADE"))
