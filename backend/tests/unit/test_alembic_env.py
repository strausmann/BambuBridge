"""The production path of ``app/migrations/env.py``: URL from ``BAMBUBRIDGE_DATABASE_URL``."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.migrations import make_alembic_config
from tests.db_support import admin_url, unique_database_name, url_for_database


async def _admin(statement: str) -> None:
    admin = create_async_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(statement))
    finally:
        await admin.dispose()


async def _versions(url: str) -> list[str]:
    eng = create_async_engine(url)
    try:
        async with eng.connect() as conn:
            return list((await conn.scalars(text("select version_num from alembic_version"))).all())
    finally:
        await eng.dispose()


@pytest.fixture
def fresh_database_url() -> Iterator[str]:
    name = unique_database_name("env")
    asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    asyncio.run(_admin(f'CREATE DATABASE "{name}"'))
    try:
        yield url_for_database(admin_url(), name)
    finally:
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_upgrade_takes_url_from_environment_when_config_has_none(
    monkeypatch: pytest.MonkeyPatch, fresh_database_url: str
):
    config = make_alembic_config()
    assert config.get_main_option("sqlalchemy.url") is None
    monkeypatch.setenv("BAMBUBRIDGE_DATABASE_URL", fresh_database_url)

    command.upgrade(config, "head")

    head = ScriptDirectory.from_config(config).get_current_head()
    assert asyncio.run(_versions(fresh_database_url)) == [head]


def test_missing_url_exits_without_leaking_any_url(monkeypatch: pytest.MonkeyPatch):
    config = make_alembic_config()
    monkeypatch.delenv("BAMBUBRIDGE_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc:
        command.upgrade(config, "head")

    message = str(exc.value)
    assert message == "BAMBUBRIDGE_DATABASE_URL is not set"
    assert "://" not in message
