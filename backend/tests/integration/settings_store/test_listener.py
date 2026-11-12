from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from typing import Any

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


async def test_the_origin_store_converges_and_is_told_only_about_written_keys(
    store: SettingsStore,
    engine: AsyncEngine,
    box_a: SecretBox,
    db_session: AsyncSession,
    session2: AsyncSession,
):
    # The store that wrote a change also receives its own NOTIFY. It may be told about a
    # key twice (a reload can run between the commit and the local cache update; see the
    # ``SettingsStore.set_many`` docstring), but never about a key nobody wrote, and its
    # state converges.
    origin = Changes(store)
    listener = SettingsListener(engine, store)
    await listener.start()
    try:
        await store.set_many(db_session, {"retention.events_days": 11})
        other = SettingsStore(box_a)
        await other.set_many(session2, {"retention.communication_days": 12})
        reported: set[str] = set()
        while "retention.communication_days" not in reported:
            reported |= await origin.next(5)
        assert reported == {"retention.events_days", "retention.communication_days"}
        assert all(
            keys <= {"retention.events_days", "retention.communication_days"}
            for keys in origin.seen
        )
        assert store.get("retention.events_days") == 11
        assert store.get("retention.communication_days") == 12
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


def _patch_connect(
    monkeypatch: pytest.MonkeyPatch,
    wrap: Callable[[int, Any], Awaitable[Any]],
) -> None:
    """Route the listener's ``asyncpg.connect`` through ``wrap(attempt_number, real_connect)``."""
    real_connect = asyncpg.connect
    attempts = {"n": 0}

    async def connect(*args: Any, **kwargs: Any) -> Any:
        attempts["n"] += 1

        async def real() -> Any:
            return await real_connect(*args, **kwargs)

        return await wrap(attempts["n"], real)

    # Only the listener's view of asyncpg is replaced; the engine keeps the real module.
    monkeypatch.setattr(
        listener_module,
        "asyncpg",
        SimpleNamespace(
            connect=connect,
            PostgresError=asyncpg.PostgresError,
            InterfaceError=asyncpg.InterfaceError,
        ),
    )


async def test_unexpected_exception_is_logged_by_type_and_followed_by_reconnect_and_reload(
    monkeypatch: pytest.MonkeyPatch,
    store: SettingsStore,
    store_b: SettingsStore,
    engine: AsyncEngine,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
):
    async def wrap(attempt: int, real: Callable[[], Awaitable[Any]]) -> Any:
        if attempt == 1:
            raise ValueError("secret-dsn-in-message")  # not in the listener's expected list
        return await real()

    _patch_connect(monkeypatch, wrap)
    monkeypatch.setattr(listener_module, "_START_TIMEOUT_SECONDS", 0.2)
    changes = Changes(store_b)
    await store.set_many(db_session, {"retention.events_days": 17})
    listener = SettingsListener(engine, store_b, min_delay=0.05)
    with caplog.at_level(logging.ERROR):
        await listener.start()
        try:
            assert await changes.next(10) == {"retention.events_days"}
        finally:
            await listener.stop()
    assert "ValueError" in caplog.text
    assert "secret-dsn-in-message" not in caplog.text


async def test_cancellation_still_propagates_out_of_the_listener(
    monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine, store_b: SettingsStore
):
    entered = asyncio.Event()

    async def wrap(_attempt: int, _real: Callable[[], Awaitable[Any]]) -> Any:
        entered.set()
        await asyncio.sleep(3600)

    _patch_connect(monkeypatch, wrap)
    monkeypatch.setattr(listener_module, "_START_TIMEOUT_SECONDS", 0.05)
    listener = SettingsListener(engine, store_b)
    await listener.start()
    assert entered.is_set()
    task = listener._task
    assert task is not None
    await asyncio.wait_for(listener.stop(), 2)
    assert task.cancelled()


class _HalfOpen:
    """A connection that looks alive but is deaf: no notifications, and the probe is gated.

    ``release`` lets the test decide when the first probe runs, so a change made before
    that moment can only arrive through the reconnect's full reload.
    """

    def __init__(self, real: Any, release: asyncio.Event, mode: str) -> None:
        self._real = real
        self._release = release
        self._mode = mode

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    async def add_listener(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def fetchval(self, *_args: Any, **_kwargs: Any) -> Any:
        await self._release.wait()
        if self._mode == "hang":
            await asyncio.sleep(3600)
        raise ConnectionResetError("probe failed")


@pytest.mark.parametrize("mode", ["hang", "fail"])
async def test_failed_liveness_probe_triggers_reconnect_and_full_reload(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    store: SettingsStore,
    store_b: SettingsStore,
    engine: AsyncEngine,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
):
    release = asyncio.Event()

    async def wrap(attempt: int, real: Callable[[], Awaitable[Any]]) -> Any:
        conn = await real()
        return _HalfOpen(conn, release, mode) if attempt == 1 else conn

    _patch_connect(monkeypatch, wrap)
    monkeypatch.setattr(listener_module, "_PROBE_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(listener_module, "_PROBE_TIMEOUT_SECONDS", 0.2)
    changes = Changes(store_b)
    listener = SettingsListener(engine, store_b, min_delay=0.05)
    with caplog.at_level(logging.WARNING):
        await listener.start()
        try:
            # The first connection is deaf, so this notification never reaches store_b.
            await store.set_many(db_session, {"retention.events_days": 33})
            assert changes.seen == []
            release.set()  # now the probe fails (or hangs until its timeout)
            assert await changes.next(10) == {"retention.events_days"}
        finally:
            await listener.stop()
    assert store_b.get("retention.events_days") == 33
    assert "probe failed" in caplog.text  # type name logged: ConnectionResetError / TimeoutError


async def test_healthy_probe_keeps_the_connection(
    monkeypatch: pytest.MonkeyPatch, engine: AsyncEngine, store_b: SettingsStore
):
    probes = {"n": 0}
    enough = asyncio.Event()

    class Counting:
        def __init__(self, real: Any) -> None:
            self._real = real

        def __getattr__(self, name: str) -> Any:
            return getattr(self._real, name)

        async def fetchval(self, *args: Any, **kwargs: Any) -> Any:
            probes["n"] += 1
            if probes["n"] >= 3:
                enough.set()
            return await self._real.fetchval(*args, **kwargs)

    async def wrap(_attempt: int, real: Callable[[], Awaitable[Any]]) -> Any:
        return Counting(await real())

    _patch_connect(monkeypatch, wrap)
    monkeypatch.setattr(listener_module, "_PROBE_INTERVAL_SECONDS", 0.02)
    listener = SettingsListener(engine, store_b)
    await listener.start()
    try:
        pid = listener.connection_pid
        await asyncio.wait_for(enough.wait(), 10)
        assert listener.connection_pid == pid
    finally:
        await listener.stop()


async def _listen(test_database_url: str) -> tuple[Any, asyncio.Queue[str]]:
    conn = await asyncpg.connect(test_database_url.replace("postgresql+asyncpg", "postgresql"))
    received: asyncio.Queue[str] = asyncio.Queue()
    await conn.add_listener(CHANNEL, lambda _c, _p, _ch, payload: received.put_nowait(payload))
    return conn, received


async def test_rotation_notifies_the_rotated_keys_when_it_commits(
    store: SettingsStore, engine: AsyncEngine, db_session: AsyncSession, test_database_url: str
):
    from app.security.rotation import rotate_secrets
    from app.settings_store.rotation import reencrypt_app_settings
    from tests.integration.settings_store.conftest import KEY_A, KEY_B

    await store.set_many(db_session, {"sso.trust_token": TOKEN, "retention.events_days": 5})
    conn, received = await _listen(test_database_url)
    try:
        count = await rotate_secrets(engine, [reencrypt_app_settings], old_key=KEY_A, new_key=KEY_B)
        payload = await asyncio.wait_for(received.get(), 2)
    finally:
        await conn.close()
    assert count == 1
    assert json.loads(payload) == ["sso.trust_token"]  # only the re-encrypted secret


async def test_rotation_sends_nothing_when_it_rolls_back_or_rotates_nothing(
    engine: AsyncEngine, store: SettingsStore, db_session: AsyncSession, test_database_url: str
):
    from app.security.rotation import RotationError, rotate_secrets
    from app.settings_store.rotation import reencrypt_app_settings
    from tests.integration.settings_store.conftest import KEY_A, KEY_B

    async def failing(_session: AsyncSession, _box: SecretBox) -> int:
        raise RotationError("later step failed")

    conn, received = await _listen(test_database_url)
    try:
        # Nothing to rotate: no notification.
        await rotate_secrets(engine, [reencrypt_app_settings], old_key=KEY_A, new_key=KEY_B)
        # A later step fails: the transaction (and with it the NOTIFY) is rolled back.
        await store.set_many(db_session, {"sso.trust_token": TOKEN})
        await asyncio.wait_for(received.get(), 2)  # the set_many notification
        with pytest.raises(RotationError):
            await rotate_secrets(
                engine, [reencrypt_app_settings, failing], old_key=KEY_A, new_key=KEY_B
            )
        # A marker proves the queue would have delivered an earlier notification.
        await store.set_many(db_session, {"retention.events_days": 6})
        payload = await asyncio.wait_for(received.get(), 2)
    finally:
        await conn.close()
    assert json.loads(payload) == ["retention.events_days"]


async def test_unexpected_exception_in_a_notification_reload_is_contained_and_recovered(
    monkeypatch: pytest.MonkeyPatch,
    store: SettingsStore,
    store_b: SettingsStore,
    engine: AsyncEngine,
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
):
    changes = Changes(store_b)
    original = store_b.reload_and_notify
    state = {"armed": False, "failed": 0}

    async def flaky(session: AsyncSession) -> set[str]:
        if state["armed"] and not state["failed"]:
            state["failed"] = 1
            raise RuntimeError("secret-detail-in-message")  # not OSError / SQLAlchemyError
        return await original(session)

    monkeypatch.setattr(store_b, "reload_and_notify", flaky)
    listener = SettingsListener(engine, store_b, min_delay=0.05)
    await listener.start()
    state["armed"] = True
    try:
        with caplog.at_level(logging.WARNING):
            await store.set_many(db_session, {"retention.events_days": 21})
            # The failed reload falls back to reconnect + full reload: the change arrives
            # although its own notification was lost. Wait for it before the next write, so
            # a later full reload cannot hide a missing recovery.
            assert await changes.next(10) == {"retention.events_days"}
        assert state["failed"] == 1
        # A later notification still reloads.
        await store.set_many(db_session, {"retention.communication_days": 22})
        assert await changes.next(10) == {"retention.communication_days"}
    finally:
        await listener.stop()
    assert "RuntimeError" in caplog.text and "secret-detail-in-message" not in caplog.text
