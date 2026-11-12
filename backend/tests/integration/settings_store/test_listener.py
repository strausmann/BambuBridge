from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.engine import make_engine
from app.security.secret_box import SecretBox
from app.settings_store import listener as listener_module
from app.settings_store.listener import SettingsListener
from app.settings_store.store import CHANNEL, SettingsStore
from tests.integration.settings_store.conftest import TOKEN


class Changes:
    """Records subscriber calls; ``next`` waits for the next one (outcome, not sleeping)."""

    def __init__(self, store: SettingsStore) -> None:
        self.seen: list[set[str]] = []
        self._queue: asyncio.Queue[set[str]] = asyncio.Queue()
        store.subscribe(self._record)

    def _record(self, keys: set[str]) -> None:
        self.seen.append(keys)
        self._queue.put_nowait(keys)

    async def next(self, timeout: float) -> set[str]:
        return await asyncio.wait_for(self._queue.get(), timeout)


@pytest_asyncio.fixture
async def store_b(box_a: SecretBox) -> SettingsStore:
    return SettingsStore(box_a)


@pytest_asyncio.fixture
async def running(engine: AsyncEngine, store_b: SettingsStore) -> AsyncIterator[SettingsListener]:
    listener = SettingsListener(engine, store_b)
    await listener.start()
    try:
        yield listener
    finally:
        await listener.stop()


async def test_set_many_notifies_other_store_instance(
    store: SettingsStore,
    store_b: SettingsStore,
    running: SettingsListener,
    db_session: AsyncSession,
):
    changes = Changes(store_b)
    await store.set_many(db_session, {"retention.events_days": 11, "sso.trust_token": TOKEN})
    assert await changes.next(2) == {"retention.events_days", "sso.trust_token"}
    assert store_b.get("retention.events_days") == 11
    assert store_b.secret("sso.trust_token") == TOKEN


async def test_the_origin_store_is_not_notified_twice(
    store: SettingsStore,
    engine: AsyncEngine,
    box_a: SecretBox,
    db_session: AsyncSession,
    session2: AsyncSession,
):
    origin = Changes(store)
    listener = SettingsListener(engine, store)
    await listener.start()
    try:
        await store.set_many(db_session, {"retention.events_days": 11})
        # A change from elsewhere arrives later; by then the origin's own notification
        # has long been handled (the reload runs under one lock, in order).
        other = SettingsStore(box_a)
        await other.set_many(session2, {"retention.communication_days": 12})
        assert await origin.next(2) == {"retention.events_days"}
        assert await origin.next(2) == {"retention.communication_days"}
        assert origin.seen == [{"retention.events_days"}, {"retention.communication_days"}]
    finally:
        await listener.stop()


async def test_notification_payload_is_the_json_list_of_keys(
    store: SettingsStore, db_session: AsyncSession, test_database_url: str
):
    conn = await asyncpg.connect(test_database_url.replace("postgresql+asyncpg", "postgresql"))
    received: asyncio.Queue[str] = asyncio.Queue()
    try:
        await conn.add_listener(CHANNEL, lambda _c, _p, _ch, payload: received.put_nowait(payload))
        await store.set_many(
            db_session, {"retention.events_days": 3, "auth.sign_in_limit_per_minute": 4}
        )
        payload = await asyncio.wait_for(received.get(), 2)
    finally:
        await conn.close()
    assert json.loads(payload) == ["auth.sign_in_limit_per_minute", "retention.events_days"]


async def test_nothing_is_sent_when_the_transaction_rolls_back(
    store: SettingsStore, db_session: AsyncSession, test_database_url: str
):
    conn = await asyncpg.connect(test_database_url.replace("postgresql+asyncpg", "postgresql"))
    received: asyncio.Queue[str] = asyncio.Queue()
    try:
        await conn.add_listener(CHANNEL, lambda _c, _p, _ch, payload: received.put_nowait(payload))
        await db_session.execute(text("select pg_notify(:c, 'x')"), {"c": CHANNEL})
        await db_session.rollback()
        await store.set_many(db_session, {"retention.events_days": 3})
        payload = await asyncio.wait_for(received.get(), 2)
        assert received.empty()
    finally:
        await conn.close()
    assert json.loads(payload) == ["retention.events_days"]


async def test_listener_reconnects_and_reloads(
    store: SettingsStore,
    store_b: SettingsStore,
    running: SettingsListener,
    db_session: AsyncSession,
    engine: AsyncEngine,
):
    # Review Focus 4: the LISTEN connection dies; a change made while it is gone is
    # picked up by the full reload after reconnecting.
    changes = Changes(store_b)
    old_pid = running.connection_pid
    assert old_pid is not None
    async with engine.connect() as conn:
        await conn.execute(text("select pg_terminate_backend(:pid)"), {"pid": old_pid})
    await store.set_many(db_session, {"retention.events_days": 42})
    assert await changes.next(35) == {"retention.events_days"}
    assert store_b.get("retention.events_days") == 42
    # Live reload works on the new connection as well.
    await store.set_many(db_session, {"retention.events_days": 43})
    assert await changes.next(5) == {"retention.events_days"}
    assert running.connection_pid is not None and running.connection_pid != old_pid


async def test_failed_reload_forces_a_reconnect_and_full_reload(
    monkeypatch: pytest.MonkeyPatch,
    store: SettingsStore,
    store_b: SettingsStore,
    engine: AsyncEngine,
    db_session: AsyncSession,
):
    changes = Changes(store_b)
    original = store_b.reload_and_notify
    failures = {"left": 1}
    started = asyncio.Event()

    async def flaky(session: AsyncSession) -> set[str]:
        if started.is_set() and failures["left"]:
            failures["left"] -= 1
            raise OSError("database went away")
        return await original(session)

    monkeypatch.setattr(store_b, "reload_and_notify", flaky)
    listener = SettingsListener(engine, store_b, min_delay=0.05)
    await listener.start()
    started.set()
    try:
        await store.set_many(db_session, {"retention.events_days": 21})
        assert await changes.next(10) == {"retention.events_days"}
        assert failures["left"] == 0
    finally:
        await listener.stop()


async def test_start_without_database_keeps_retrying_and_stop_is_clean(
    monkeypatch: pytest.MonkeyPatch, store_b: SettingsStore
):
    monkeypatch.setattr(listener_module, "_START_TIMEOUT_SECONDS", 0.3)
    dead = make_engine("postgresql+asyncpg://postgres:x@127.0.0.1:1/none")
    listener = SettingsListener(dead, store_b, min_delay=0.05, max_delay=0.1)
    try:
        started = time.monotonic()
        await listener.start()
        assert time.monotonic() - started < 3
        assert listener.connection_pid is None
        await listener.start()  # second start is a no-op
        await listener.stop()
        await listener.stop()  # idempotent
    finally:
        await dead.dispose()


async def test_listener_connects_once_the_database_comes_up(
    monkeypatch: pytest.MonkeyPatch,
    store: SettingsStore,
    store_b: SettingsStore,
    engine: AsyncEngine,
    db_session: AsyncSession,
):
    changes = Changes(store_b)
    attempts = {"n": 0}
    real_dsn = SettingsListener._dsn

    def flaky_dsn(self: SettingsListener) -> str:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            return "postgresql://postgres:x@127.0.0.1:1/none"
        return real_dsn(self)

    monkeypatch.setattr(SettingsListener, "_dsn", flaky_dsn)
    await store.set_many(db_session, {"retention.events_days": 8})
    listener = SettingsListener(engine, store_b, min_delay=0.05, max_delay=0.2)
    await listener.start()
    try:
        # The first two connection attempts fail; the full reload after connecting
        # delivers the change that was made before the listener was up.
        assert await changes.next(10) == {"retention.events_days"}
        assert attempts["n"] >= 3
    finally:
        await listener.stop()
