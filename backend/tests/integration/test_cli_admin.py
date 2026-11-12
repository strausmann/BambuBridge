from __future__ import annotations

import asyncio
import re

import pytest
from sqlalchemy import select

from app.cli import main
from app.db.engine import make_engine
from app.db.session import make_session_factory
from app.models.api_key import ApiKey
from app.models.user import User
from tests.db_support import truncate_all

_TOKEN = re.compile(r"^bb_pat_[0-9A-Za-z]{40}$")


# These tests are synchronous because the CLI runs its own event loop (asyncio.run); each
# helper therefore uses its own short-lived engine instead of the async ``engine`` fixture.


async def _truncate(url: str) -> None:
    engine = make_engine(url)
    try:
        await truncate_all(engine)
    finally:
        await engine.dispose()


async def _rows(url: str) -> list[tuple[ApiKey, User]]:
    engine = make_engine(url)
    try:
        async with make_session_factory(engine)() as session:
            result = await session.execute(select(ApiKey, User).join(User))
            return [(k, u) for k, u in result]
    finally:
        await engine.dispose()


def test_create_key_prints_plaintext_once(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    asyncio.run(_truncate(test_database_url))
    monkeypatch.setenv("BAMBUBRIDGE_DATABASE_URL", test_database_url)
    assert main(["admin", "create-key", "--scope", "operate", "--name", "ci"]) == 0
    out, err = capsys.readouterr()
    lines = out.strip().splitlines()
    assert len(lines) == 1
    assert _TOKEN.fullmatch(lines[0])
    assert lines[0] not in err

    rows = asyncio.run(_rows(test_database_url))
    assert len(rows) == 1
    key, owner = rows[0]
    assert (key.name, key.scope, key.prefix) == ("ci", "operate", lines[0][:16])
    assert (owner.display_name, owner.role) == ("admin", "admin")


def test_create_key_requires_scope_and_name(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as e:
        main(["admin", "create-key", "--scope", "root", "--name", "x"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        main(["admin", "create-key", "--scope", "read"])
    assert e.value.code == 2


def test_create_key_without_database_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.delenv("BAMBUBRIDGE_DATABASE_URL", raising=False)
    assert main(["admin", "create-key", "--scope", "read", "--name", "x"]) == 2
    assert "BAMBUBRIDGE_DATABASE_URL is not set" in capsys.readouterr().err


def test_create_key_database_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    # Nothing listens on port 1; the password must not show up in the error.
    monkeypatch.setenv(
        "BAMBUBRIDGE_DATABASE_URL", "postgresql+asyncpg://u:hunter2-secret@127.0.0.1:1/bb"
    )
    assert main(["admin", "create-key", "--scope", "read", "--name", "x"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "database error" in err
    assert "hunter2-secret" not in err


def test_create_key_rejects_blank_name(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("BAMBUBRIDGE_DATABASE_URL", test_database_url)
    assert main(["admin", "create-key", "--scope", "read", "--name", "  "]) == 2
    assert "name" in capsys.readouterr().err


async def _seed_admin(url: str, *, enabled: bool, role: str) -> None:
    engine = make_engine(url)
    try:
        await truncate_all(engine)
        async with make_session_factory(engine)() as session:
            session.add(User(display_name="admin", role=role, enabled=enabled))
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("enabled", "role", "reason"),
    [(False, "admin", "disabled"), (True, "read", "role")],
)
def test_create_key_refuses_unusable_admin_user(
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    enabled: bool,
    role: str,
    reason: str,
):
    # A token for a disabled or demoted admin user could never be used.
    asyncio.run(_seed_admin(test_database_url, enabled=enabled, role=role))
    monkeypatch.setenv("BAMBUBRIDGE_DATABASE_URL", test_database_url)
    assert main(["admin", "create-key", "--scope", "admin", "--name", "x"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert reason in err
    assert asyncio.run(_rows(test_database_url)) == []
