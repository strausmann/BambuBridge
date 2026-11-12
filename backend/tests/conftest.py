"""Shared pytest fixtures and the per-run test database.

The suite needs ``BAMBUBRIDGE_TEST_DATABASE_URL`` (a PostgreSQL 18 server). Each run
creates its own database (``bb_test_…``, see ``unique_database_name``), migrates it once
with ``alembic upgrade head`` and drops it at the end. Every test starts with all tables
truncated.

Tokens are hashed with the cheapest bcrypt cost in tests (``cheap_bcrypt``); tests marked
``production_bcrypt_cost`` run with the cost the application ships with.
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
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.auth import tokens
from app.auth.scopes import Scope
from app.config import Settings
from app.db.engine import make_engine
from app.db.session import make_session_factory
from app.main import create_app
from app.migrations import make_alembic_config
from app.repositories import api_keys as api_keys_repo
from app.repositories import users as users_repo
from tests.db_support import (
    MISSING_URL_MESSAGE,
    TEST_DATABASE_URL_ENV,
    admin_url,
    truncate_all,
    unique_database_name,
    url_for_database,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Obviously fake bootstrap key (>= 32 characters), readable text only.
TEST_BOOTSTRAP_KEY = "test-bootstrap-key-abcdefghijklmnopqrstuvwxyz"
KEY_HEADER = "X-BambuBridge-Key"
# The lowest cost bcrypt accepts. Hashing dominates the suite at the production cost.
TEST_BCRYPT_ROUNDS = 4


def pytest_sessionstart(session: pytest.Session) -> None:
    """Abort the whole run with a clear message when no test database is configured."""
    if not os.environ.get(TEST_DATABASE_URL_ENV):
        pytest.exit(MISSING_URL_MESSAGE, returncode=4)


@pytest.fixture(autouse=True)
def cheap_bcrypt(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Hash tokens with ``TEST_BCRYPT_ROUNDS`` unless the test asks for the production cost.

    Only the test process is affected: the application reads ``tokens.BCRYPT_ROUNDS``,
    which this fixture replaces for the duration of one test. Tests marked
    ``production_bcrypt_cost`` keep the shipped value and pin it.
    """
    if request.node.get_closest_marker("production_bcrypt_cost") is None:
        monkeypatch.setattr(tokens, "BCRYPT_ROUNDS", TEST_BCRYPT_ROUNDS)
        yield
        return
    # The dummy hash is computed once per process; do not reuse a cheap one here and do
    # not leave an expensive one behind for the following tests.
    tokens._dummy_hash.cache_clear()
    try:
        yield
    finally:
        tokens._dummy_hash.cache_clear()


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
    """Create a database for this run (and worker), migrate it to head, drop it at the end."""
    name = unique_database_name("test")
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
    name = unique_database_name("scratch")
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
        bootstrap_admin_key=TEST_BOOTSTRAP_KEY,  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def app(settings: Settings, engine: AsyncEngine) -> AsyncIterator[FastAPI]:
    # ``engine`` makes sure the database is clean before the app touches it.
    application = create_app(settings)
    try:
        yield application
    finally:
        # ASGITransport runs no lifespan, so the app's own engine is disposed here.
        await application.state.engine.dispose()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def issue_token(
    engine: AsyncEngine, scope: Scope, *, name: str | None = None, **fields: object
) -> str:
    """Create a token owned by the single admin user and return its plaintext."""
    async with make_session_factory(engine)() as session:
        owner = await users_repo.get_or_create_admin(session)
        _, plaintext = await api_keys_repo.create(
            session, owner_user_id=owner.id, name=name or f"test {scope}", scope=scope, **fields
        )
        await session.commit()
    return plaintext


@pytest_asyncio.fixture
async def read_token(engine: AsyncEngine) -> str:
    return await issue_token(engine, "read")


@pytest_asyncio.fixture
async def operate_token(engine: AsyncEngine) -> str:
    return await issue_token(engine, "operate")


@pytest_asyncio.fixture
async def admin_token(engine: AsyncEngine) -> str:
    return await issue_token(engine, "admin")


@pytest_asyncio.fixture
async def admin_client(app: FastAPI, admin_token: str) -> AsyncIterator[httpx.AsyncClient]:
    """A client that sends the ``admin_token`` with every request."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={KEY_HEADER: admin_token}
    ) as c:
        yield c
