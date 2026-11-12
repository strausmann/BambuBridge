"""Shared pytest fixtures and the per-run test database.

The suite needs ``BAMBUBRIDGE_TEST_DATABASE_URL`` (a PostgreSQL 18 server). Each run
creates its own database ``bb_test_<pid>``, migrates it once with ``alembic upgrade
head`` and drops it at the end. Every test starts with all tables truncated.
"""

from __future__ import annotations

import asyncio
import base64
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.config import Settings
from app.db.engine import make_engine
from app.db.session import make_session_factory
from app.main import create_app
from app.migrations import make_alembic_config
from tests.db_support import (
    MISSING_URL_MESSAGE,
    TEST_DATABASE_URL_ENV,
    admin_url,
    truncate_all,
    url_for_database,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]


def pytest_sessionstart(session: pytest.Session) -> None:
    """Abort the whole run with a clear message when no test database is configured."""
    if not os.environ.get(TEST_DATABASE_URL_ENV):
        pytest.exit(MISSING_URL_MESSAGE, returncode=4)


async def _admin_statement(statement: str) -> None:
    admin = create_async_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(statement))
    finally:
        await admin.dispose()


def _alembic_config(url: str) -> Config:
    return make_alembic_config(url)


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """Create ``bb_test_<pid>``, migrate it to head, drop it after the run."""
    name = f"bb_test_{os.getpid()}"
    asyncio.run(_admin_statement(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    asyncio.run(_admin_statement(f'CREATE DATABASE "{name}"'))
    url = url_for_database(admin_url(), name)
    try:
        command.upgrade(_alembic_config(url), "head")
        yield url
    finally:
        asyncio.run(_admin_statement(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def scratch_database_url() -> Iterator[str]:
    """An empty throw-away database for tests that migrate up and down."""
    name = f"bb_scratch_{os.getpid()}"
    asyncio.run(_admin_statement(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    asyncio.run(_admin_statement(f'CREATE DATABASE "{name}"'))
    try:
        yield url_for_database(admin_url(), name)
    finally:
        asyncio.run(_admin_statement(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def alembic_config(test_database_url: str) -> Config:
    return _alembic_config(test_database_url)


@pytest_asyncio.fixture
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    """Engine on the per-run database; all tables are empty when the test starts."""
    eng = make_engine(test_database_url)
    try:
        await truncate_all(eng)
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with make_session_factory(engine)() as session:
        yield session
        await session.rollback()


@pytest.fixture
def settings(test_database_url: str) -> Settings:
    # Obviously fake secrets, derived at runtime from readable text.
    key = base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode()
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=test_database_url,
        secret_key=key,  # type: ignore[arg-type]
        public_url="https://bb.example.com",  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def client(settings: Settings, engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    # ``engine`` makes sure the database is clean before the request is made.
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
