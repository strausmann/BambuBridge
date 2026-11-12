"""Live reload: one dedicated asyncpg connection ``LISTEN``s on the settings channel.

A notification makes the store reload from the database and tell its subscribers what
changed. When the connection is lost (Postgres restart, network), the listener reconnects
with a growing wait (1 s, 2 s, 4 s ... at most 30 s) and then reloads everything, because
notifications sent while it was away are gone.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

import asyncpg
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import make_session_factory
from app.settings_store.store import CHANNEL, SettingsStore

_log = logging.getLogger(__name__)

_START_TIMEOUT_SECONDS = 5.0
_CLOSE_TIMEOUT_SECONDS = 2.0


class SettingsListener:
    def __init__(
        self,
        engine: AsyncEngine,
        store: SettingsStore,
        *,
        min_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._engine = engine
        self._store = store
        self._sessions = make_session_factory(engine)
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._task: asyncio.Task[None] | None = None
        self._reloads: set[asyncio.Task[None]] = set()
        self._reload_lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._lost = asyncio.Event()
        # Server process id of the LISTEN connection (None while disconnected); lets tests
        # and operators terminate exactly this connection.
        self.connection_pid: int | None = None

    async def start(self) -> None:
        """Start listening; returns once connected (or after a short grace period).

        If the database is down at start, the listener keeps retrying in the background.
        """
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="settings-listener")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._ready.wait(), timeout=_START_TIMEOUT_SECONDS)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for reload_task in list(self._reloads):
            reload_task.cancel()
        self._reloads.clear()
        self._ready.clear()

    # -- internals ----------------------------------------------------------

    def _dsn(self) -> str:
        return self._engine.url.set(drivername="postgresql").render_as_string(hide_password=False)

    async def _run(self) -> None:
        delay = self._min_delay
        while True:
            conn: asyncpg.Connection[Any] | None = None
            try:
                self._lost = lost = asyncio.Event()
                conn = await asyncpg.connect(self._dsn())
                conn.add_termination_listener(lambda _c, event=lost: event.set())
                await conn.add_listener(CHANNEL, self._on_notify)
                self.connection_pid = conn.get_server_pid()
                # LISTEN is active before this load, so nothing can slip through the gap.
                await self._reload()
                self._ready.set()
                delay = self._min_delay
                await lost.wait()
                _log.warning("settings listener lost its connection; reconnecting")
            except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError, SQLAlchemyError) as exc:
                _log.warning("settings listener cannot connect (%s)", type(exc).__name__)
            finally:
                self.connection_pid = None
                if conn is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(conn.close(), timeout=_CLOSE_TIMEOUT_SECONDS)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._max_delay)

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, _payload: str) -> None:
        task = asyncio.create_task(self._reload_after_notification())
        self._reloads.add(task)
        task.add_done_callback(self._reloads.discard)

    async def _reload_after_notification(self) -> None:
        try:
            await self._reload()
        except (OSError, SQLAlchemyError) as exc:
            # The connection may look alive while the database is not; reconnect and reload.
            _log.warning("settings reload failed (%s); reconnecting", type(exc).__name__)
            self._lost.set()

    async def _reload(self) -> None:
        async with self._reload_lock, self._sessions() as session:
            await self._store.reload_and_notify(session)
