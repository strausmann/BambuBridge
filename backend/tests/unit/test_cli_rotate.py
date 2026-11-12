from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.cli import main
from app.db.engine import make_engine
from app.db.session import make_session_factory
from app.models.app_setting import AppSetting
from app.security.rotation import RotationError, rotate_secrets
from app.security.secret_box import SecretBox, key_id_for, secret_box_from_key
from app.settings_store.rotation import reencrypt_app_settings
from app.settings_store.store import SettingsStore
from tests.db_support import truncate_all

RAW_OLD = b"o" * 32
RAW_NEW = b"n" * 32
OLD = base64.urlsafe_b64encode(RAW_OLD).decode()
NEW = base64.urlsafe_b64encode(RAW_NEW).decode()
TOKEN = "t" * 40


Work = Callable[[AsyncSession], Awaitable[Any]]


def _query(test_database_url: str, work: Work, *, truncate: bool = False) -> Any:
    """Run ``work(session)`` in a throw-away event loop on the test database."""

    async def go() -> Any:
        engine = make_engine(test_database_url)
        try:
            if truncate:
                await truncate_all(engine)
            async with make_session_factory(engine)() as session:
                return await work(session)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _run(test_database_url: str, work: Work) -> Any:
    """Like ``_query`` but starts from empty tables (the seeding step of a test)."""
    return _query(test_database_url, work, truncate=True)


async def _seed(session: AsyncSession) -> None:
    store = SettingsStore(secret_box_from_key(RAW_OLD))
    await store.set_many(session, {"sso.trust_token": TOKEN, "retention.events_days": 5})


async def _load_with(session: AsyncSession, box: SecretBox) -> tuple[str | None, bool, str | None]:
    store = SettingsStore(box)
    await store.load(session)
    view = {v.key: v for v in store.describe()}["sso.trust_token"]
    row = (
        await session.execute(select(AppSetting).where(AppSetting.key == "sso.trust_token"))
    ).scalar_one()
    return store.secret("sso.trust_token"), view.undecryptable, row.secret_key_id


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, test_database_url: str) -> pytest.MonkeyPatch:
    monkeypatch.setenv("BAMBUBRIDGE_DATABASE_URL", test_database_url)
    monkeypatch.setenv("BAMBUBRIDGE_SECRET_KEY", NEW)
    monkeypatch.setenv("BAMBUBRIDGE_SECRET_KEY_OLD", OLD)
    return monkeypatch


def test_rotate_reencrypts_all_and_old_key_no_longer_needed(
    env: pytest.MonkeyPatch, test_database_url: str, capsys: pytest.CaptureFixture[str]
):
    _run(test_database_url, _seed)
    assert main(["secrets", "rotate"]) == 0
    out = capsys.readouterr()
    assert out.out == "re-encrypted 1 secrets\n"
    assert OLD not in out.out + out.err and NEW not in out.out + out.err

    # Opens with the new key alone, and the stored key id is the new one ...
    plain, undecryptable, key_id = _query(
        test_database_url, lambda s: _load_with(s, secret_box_from_key(RAW_NEW))
    )
    assert (plain, undecryptable, key_id) == (TOKEN, False, key_id_for(RAW_NEW))
    # ... and the old key alone no longer opens it.
    plain, undecryptable, _ = _query(
        test_database_url, lambda s: _load_with(s, secret_box_from_key(RAW_OLD))
    )
    assert (plain, undecryptable) == (None, True)


def test_rotate_leaves_plain_settings_alone_and_counts_zero_without_secrets(
    env: pytest.MonkeyPatch, test_database_url: str, capsys: pytest.CaptureFixture[str]
):
    async def seed_plain(session: AsyncSession) -> None:
        await SettingsStore(secret_box_from_key(RAW_OLD)).set_many(
            session, {"retention.events_days": 5}
        )

    _run(test_database_url, seed_plain)
    assert main(["secrets", "rotate"]) == 0
    assert capsys.readouterr().out == "re-encrypted 0 secrets\n"

    async def value(session: AsyncSession) -> object:
        return (await session.execute(select(AppSetting.value))).scalar_one()

    assert _query(test_database_url, value) == 5


def test_rotate_can_be_repeated_after_it_already_ran(
    env: pytest.MonkeyPatch, test_database_url: str, capsys: pytest.CaptureFixture[str]
):
    _run(test_database_url, _seed)
    assert main(["secrets", "rotate"]) == 0
    assert main(["secrets", "rotate"]) == 0
    assert capsys.readouterr().out == "re-encrypted 1 secrets\nre-encrypted 1 secrets\n"
    plain, _, _ = _query(test_database_url, lambda s: _load_with(s, secret_box_from_key(RAW_NEW)))
    assert plain == TOKEN


def test_rotate_without_old_key_exits_2(
    env: pytest.MonkeyPatch, test_database_url: str, capsys: pytest.CaptureFixture[str]
):
    _run(test_database_url, _seed)
    env.delenv("BAMBUBRIDGE_SECRET_KEY_OLD")
    assert main(["secrets", "rotate"]) == 2
    assert "BAMBUBRIDGE_SECRET_KEY_OLD is not set" in capsys.readouterr().err
    # Nothing was touched: the old key still opens the secret.
    plain, _, key_id = _query(
        test_database_url, lambda s: _load_with(s, secret_box_from_key(RAW_OLD))
    )
    assert (plain, key_id) == (TOKEN, key_id_for(RAW_OLD))


@pytest.mark.parametrize(
    ("variable", "message"),
    [
        ("BAMBUBRIDGE_SECRET_KEY", "BAMBUBRIDGE_SECRET_KEY is not set"),
        ("BAMBUBRIDGE_DATABASE_URL", "BAMBUBRIDGE_DATABASE_URL is not set"),
    ],
)
def test_rotate_without_the_other_inputs_exits_2(
    variable: str, message: str, env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    env.delenv(variable)
    assert main(["secrets", "rotate"]) == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("variable", ["BAMBUBRIDGE_SECRET_KEY_OLD", "BAMBUBRIDGE_SECRET_KEY"])
def test_rotate_with_a_malformed_key_exits_2_without_echoing_it(
    variable: str, env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    bad = "not+a/valid base64url!! key"
    env.setenv(variable, bad)
    assert main(["secrets", "rotate"]) == 2
    err = capsys.readouterr().err
    assert variable in err and bad not in err


def test_rotate_with_identical_keys_exits_2(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    env.setenv("BAMBUBRIDGE_SECRET_KEY_OLD", NEW)
    assert main(["secrets", "rotate"]) == 2
    assert "identical" in capsys.readouterr().err


def test_rotate_aborts_without_changes_when_a_secret_opens_with_neither_key(
    env: pytest.MonkeyPatch, test_database_url: str, capsys: pytest.CaptureFixture[str]
):
    foreign = SettingsStore(secret_box_from_key(b"f" * 32))

    async def seed_foreign(session: AsyncSession) -> None:
        await foreign.set_many(session, {"sso.trust_token": TOKEN})

    _run(test_database_url, seed_foreign)

    async def token(session: AsyncSession) -> str | None:
        return (await session.execute(select(AppSetting.secret_token))).scalar_one()

    before = _query(test_database_url, token)
    assert main(["secrets", "rotate"]) == 1
    err = capsys.readouterr().err
    assert "sso.trust_token" in err and "nothing was changed" in err and TOKEN not in err
    assert _query(test_database_url, token) == before


def test_rotate_reports_an_unreachable_database_with_exit_1(
    env: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    env.setenv("BAMBUBRIDGE_DATABASE_URL", "postgresql+asyncpg://postgres:x@127.0.0.1:1/none")
    assert main(["secrets", "rotate"]) == 1
    assert "database error" in capsys.readouterr().err


def test_the_cli_runs_the_registered_steps(env: pytest.MonkeyPatch):
    assert [reencrypt_app_settings] == cli.REENCRYPT_STEPS


async def test_all_steps_share_one_transaction(engine, db_session: AsyncSession):  # type: ignore[no-untyped-def]
    # Task 11 adds a step for provider_instances; a failure there must undo the rest.
    await SettingsStore(secret_box_from_key(RAW_OLD)).set_many(
        db_session, {"sso.trust_token": TOKEN}
    )
    before = (await db_session.execute(select(AppSetting.secret_token))).scalar_one()

    async def failing_second_step(_session: AsyncSession, _box: SecretBox) -> int:
        raise RotationError("second table failed")

    with pytest.raises(RotationError):
        await rotate_secrets(
            engine,
            [reencrypt_app_settings, failing_second_step],
            old_key=RAW_OLD,
            new_key=RAW_NEW,
        )
    await db_session.rollback()
    assert (await db_session.execute(select(AppSetting.secret_token))).scalar_one() == before
    await db_session.execute(text("select 1"))
    total = await rotate_secrets(engine, [reencrypt_app_settings], old_key=RAW_OLD, new_key=RAW_NEW)
    assert total == 1
