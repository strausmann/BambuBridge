from __future__ import annotations

import dataclasses
import logging

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.security.secret_box import SecretBox
from app.settings_store.registry import (
    SETTINGS,
    InvalidSettingValueError,
    UnknownSettingError,
)
from app.settings_store.store import SettingsStore
from tests.integration.settings_store.conftest import KEY_A, TOKEN, key_id_for


async def test_empty_database_yields_the_defaults(store: SettingsStore, db_session: AsyncSession):
    await store.load(db_session)
    for key, d in SETTINGS.items():
        if d.type != "secret":
            assert store.get(key) == d.default
    assert store.secret("sso.trust_token") is None
    assert store.get("sso.user_header") == "Remote-User"
    assert store.get("retention.events_days") == 90


async def test_store_has_no_env_override(
    monkeypatch: pytest.MonkeyPatch, store: SettingsStore, db_session: AsyncSession
):
    monkeypatch.setenv("BAMBUBRIDGE_SSO_USER_HEADER", "X-Evil")
    monkeypatch.setenv("SSO_USER_HEADER", "X-Evil")
    monkeypatch.setenv("BAMBUBRIDGE_RETENTION_EVENTS_DAYS", "1")
    await store.load(db_session)
    assert store.get("sso.user_header") == "Remote-User"
    assert store.get("retention.events_days") == 90
    await store.set_many(db_session, {"retention.events_days": 7})
    assert store.get("retention.events_days") == 7


async def test_set_many_persists_and_a_fresh_store_loads_it(
    store: SettingsStore, box_a: SecretBox, db_session: AsyncSession, session2: AsyncSession
):
    await store.set_many(
        db_session,
        {
            "sso.user_header": "Remote-Email",
            "sso.trust_header": "X-Token",
            "auth.sign_in_limit_per_minute": 30,
            "sso.trust_token": TOKEN,
        },
    )
    other = SettingsStore(box_a)
    await other.load(session2)
    assert other.get("sso.user_header") == "Remote-Email"
    assert other.get("sso.trust_header") == "X-Token"
    assert other.get("auth.sign_in_limit_per_minute") == 30
    assert other.secret("sso.trust_token") == TOKEN


async def test_secret_is_stored_only_as_sealed_token(
    store: SettingsStore, box_a: SecretBox, db_session: AsyncSession
):
    await store.set_many(db_session, {"sso.trust_token": TOKEN})
    row = (await db_session.execute(select(AppSetting))).scalar_one()
    assert row.key == "sso.trust_token"
    assert row.value is None
    assert row.secret_key_id == key_id_for(KEY_A)
    assert row.secret_token is not None and TOKEN not in row.secret_token
    raw = (await db_session.execute(text("select * from app_settings"))).all()
    assert TOKEN not in repr(raw)


async def test_describe_never_exposes_the_secret(store: SettingsStore, db_session: AsyncSession):
    await store.set_many(db_session, {"sso.trust_token": TOKEN})
    views = {v.key: v for v in store.describe()}
    assert set(views) == set(SETTINGS)
    view = views["sso.trust_token"]
    assert view.set is True and view.undecryptable is False
    assert view.value is None and view.default is None
    assert TOKEN not in repr(dataclasses.asdict(view))
    assert TOKEN not in repr(store.describe())
    assert views["sso.user_header"].set is False
    assert views["sso.user_header"].choices == ("Remote-User", "Remote-User-Id", "Remote-Email")
    assert views["retention.events_days"].min == 1 and views["retention.events_days"].max == 3650


async def test_store_loads_with_foreign_key_marks_undecryptable(
    store: SettingsStore, box_b: SecretBox, db_session: AsyncSession, session2: AsyncSession
):
    # Review Focus 2: a changed BAMBUBRIDGE_SECRET_KEY must not crash the server.
    await store.set_many(db_session, {"sso.trust_token": TOKEN, "retention.events_days": 5})
    foreign = SettingsStore(box_b)
    await foreign.load(session2)
    view = {v.key: v for v in foreign.describe()}["sso.trust_token"]
    assert view.undecryptable is True and view.set is True
    assert foreign.secret("sso.trust_token") is None
    # Plain settings are unaffected.
    assert foreign.get("retention.events_days") == 5


async def test_saving_a_secret_again_clears_the_undecryptable_flag(
    box_b: SecretBox, store: SettingsStore, db_session: AsyncSession, session2: AsyncSession
):
    await store.set_many(db_session, {"sso.trust_token": TOKEN})
    foreign = SettingsStore(box_b)
    await foreign.load(session2)
    assert foreign.secret("sso.trust_token") is None
    await foreign.set_many(session2, {"sso.trust_token": "n" * 40})
    view = {v.key: v for v in foreign.describe()}["sso.trust_token"]
    assert view.undecryptable is False and foreign.secret("sso.trust_token") == "n" * 40


@pytest.mark.parametrize("cleared", [None, ""])
async def test_secret_can_be_cleared(
    cleared: str | None, store: SettingsStore, db_session: AsyncSession
):
    await store.set_many(db_session, {"sso.trust_token": TOKEN})
    await store.set_many(db_session, {"sso.trust_token": cleared})
    assert store.secret("sso.trust_token") is None
    assert {v.key: v for v in store.describe()}["sso.trust_token"].set is False
    assert (await db_session.execute(select(AppSetting))).first() is None


async def test_none_resets_a_plain_setting_to_its_default(
    store: SettingsStore, db_session: AsyncSession
):
    await store.set_many(db_session, {"retention.events_days": 5})
    await store.set_many(db_session, {"retention.events_days": None})
    assert store.get("retention.events_days") == 90
    assert (await db_session.execute(select(AppSetting))).first() is None


async def test_set_many_overwrites_an_existing_row(store: SettingsStore, db_session: AsyncSession):
    await store.set_many(db_session, {"retention.events_days": 5})
    await store.set_many(db_session, {"retention.events_days": 6})
    rows = (await db_session.execute(select(AppSetting))).scalars().all()
    assert [(r.key, r.value) for r in rows] == [("retention.events_days", 6)]


async def test_user_header_outside_choices_rejected(store: SettingsStore, db_session: AsyncSession):
    with pytest.raises(InvalidSettingValueError) as e:
        await store.set_many(db_session, {"sso.user_header": "X-Forwarded-User"})
    assert e.value.keys == ["sso.user_header"]
    assert e.value.code == "invalid_value"
    assert store.get("sso.user_header") == "Remote-User"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("auth.sign_in_limit_per_minute", 0),
        ("auth.sign_in_limit_per_minute", 601),
        ("retention.events_days", 3651),
        ("events.dedup_window_seconds", -1),
        ("events.dedup_window_seconds", 86401),
        ("retention.events_days", True),
        ("retention.events_days", "7"),
        ("sso.trust_header", 5),
        ("sso.trust_header", "x" * 257),
        ("sso.trust_token", "short"),
        ("sso.trust_token", "ü" * 40),
        ("sso.trust_token", 12),
    ],
)
async def test_invalid_values_are_rejected(
    key: str, value: object, store: SettingsStore, db_session: AsyncSession
):
    with pytest.raises(InvalidSettingValueError) as e:
        await store.set_many(db_session, {key: value})
    assert e.value.keys == [key]


async def test_validation_message_never_contains_the_offending_secret(
    store: SettingsStore, db_session: AsyncSession
):
    for bad in ("tooshort-secret-value", "ü" * 40):
        with pytest.raises(InvalidSettingValueError) as e:
            await store.set_many(db_session, {"sso.trust_token": bad})
        assert bad not in str(e.value)


async def test_dedup_window_accepts_zero(store: SettingsStore, db_session: AsyncSession):
    await store.set_many(db_session, {"events.dedup_window_seconds": 0})
    assert store.get("events.dedup_window_seconds") == 0


async def test_unknown_key_is_rejected(store: SettingsStore, db_session: AsyncSession):
    with pytest.raises(UnknownSettingError) as e:
        await store.set_many(db_session, {"nope.key": 1, "also.nope": 2})
    assert e.value.keys == ["also.nope", "nope.key"]
    assert e.value.code == "unknown_setting"
    with pytest.raises(UnknownSettingError):
        store.get("nope.key")


async def test_one_invalid_value_writes_nothing(store: SettingsStore, db_session: AsyncSession):
    with pytest.raises(InvalidSettingValueError):
        await store.set_many(
            db_session, {"retention.events_days": 5, "auth.sign_in_limit_per_minute": 0}
        )
    assert store.get("retention.events_days") == 90
    assert (await db_session.execute(select(AppSetting))).first() is None


async def test_empty_update_is_a_no_op(store: SettingsStore, db_session: AsyncSession):
    calls: list[set[str]] = []
    store.subscribe(calls.append)
    await store.set_many(db_session, {})
    assert calls == []


async def test_database_failure_changes_neither_database_nor_cache(
    monkeypatch: pytest.MonkeyPatch, store: SettingsStore, db_session: AsyncSession
):
    calls: list[set[str]] = []
    store.subscribe(calls.append)

    async def boom() -> None:
        raise OSError("connection lost")

    monkeypatch.setattr(db_session, "commit", boom)
    with pytest.raises(OSError, match="connection lost"):
        await store.set_many(db_session, {"retention.events_days": 5})
    assert store.get("retention.events_days") == 90
    assert calls == []
    monkeypatch.undo()
    assert (await db_session.execute(select(AppSetting))).first() is None


async def test_subscribers_see_local_changes_and_failures_are_contained(
    store: SettingsStore, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    seen: list[set[str]] = []

    def broken(_keys: set[str]) -> None:
        raise RuntimeError(f"leaks {TOKEN}")

    store.subscribe(broken)
    store.subscribe(seen.append)
    with caplog.at_level(logging.ERROR):
        await store.set_many(db_session, {"retention.events_days": 5, "sso.trust_token": TOKEN})
    assert seen == [{"retention.events_days", "sso.trust_token"}]
    assert "RuntimeError" in caplog.text and TOKEN not in caplog.text


async def test_reload_and_notify_reports_only_what_changed(
    store: SettingsStore, box_a: SecretBox, db_session: AsyncSession, session2: AsyncSession
):
    other = SettingsStore(box_a)
    seen: list[set[str]] = []
    other.subscribe(seen.append)
    await other.reload_and_notify(session2)
    assert seen == []
    await store.set_many(db_session, {"retention.events_days": 5, "sso.trust_token": TOKEN})
    assert await other.reload_and_notify(session2) == {"retention.events_days", "sso.trust_token"}
    assert await other.reload_and_notify(session2) == set()
    assert seen == [{"retention.events_days", "sso.trust_token"}]
    await store.set_many(db_session, {"retention.events_days": None})
    assert await other.reload_and_notify(session2) == {"retention.events_days"}


async def test_load_ignores_unknown_keys_and_invalid_stored_values(
    store: SettingsStore, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    await db_session.execute(
        text(
            "insert into app_settings (key, value, updated_at) values "
            "('legacy.thing', '1', now()), "
            "('retention.events_days', '99999', now()), "
            "('sso.user_header', '\"X-Evil\"', now()), "
            "('auth.sign_in_limit_per_minute', 'null'::jsonb, now())"
        )
    )
    with caplog.at_level(logging.WARNING):
        await store.load(db_session)
    assert store.get("retention.events_days") == 90
    assert store.get("sso.user_header") == "Remote-User"
    assert store.get("auth.sign_in_limit_per_minute") == 10
    assert "retention.events_days" in caplog.text
    assert "X-Evil" not in caplog.text and "99999" not in caplog.text


async def test_load_skips_a_secret_row_without_token(
    store: SettingsStore, db_session: AsyncSession
):
    await db_session.execute(
        text("insert into app_settings (key, updated_at) values ('sso.trust_token', now())")
    )
    await store.load(db_session)
    assert store.secret("sso.trust_token") is None
    assert {v.key: v for v in store.describe()}["sso.trust_token"].set is False


async def test_secret_and_plain_accessors_refuse_the_other_kind(store: SettingsStore):
    with pytest.raises(TypeError):
        store.get("sso.trust_token")
    with pytest.raises(TypeError):
        store.secret("sso.user_header")
    with pytest.raises(UnknownSettingError):
        store.secret("nope")


async def test_check_constraint_rejects_half_a_secret(db_session: AsyncSession):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "insert into app_settings (key, secret_token, updated_at) "
                "values ('sso.trust_token', 'v1.a.b', now())"
            )
        )
