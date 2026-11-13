"""Live apply: one dedicated asyncpg connection ``LISTEN``s on ``bambubridge_providers``.

The payload of a notification is the id of the changed instance; the listener has the
manager apply it in the background. When the connection is lost it reconnects with a growing
wait (1 s, 2 s, 4 s ... at most 30 s) and then brings every instance in line with the
database (:meth:`ProviderManager.start_all`), because notifications sent while it was away
are gone. Same pattern as :mod:`app.settings_store.listener`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

import asyncpg
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.repositories.provider_instances import PROVIDERS_CHANNEL

if TYPE_CHECKING:
    from app.providers.manager import ProviderManager

_log = logging.getLogger(__name__)

_START_TIMEOUT_SECONDS = 5.0
_CLOSE_TIMEOUT_SECONDS = 2.0
_PROBE_INTERVAL_SECONDS = 15.0
_PROBE_TIMEOUT_SECONDS = 5.0


class ProviderListener:
    def __init__(
        self,
        engine: AsyncEngine,
        manager: ProviderManager,
        *,
        min_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._engine = engine
        self._manager = manager
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._task: asyncio.Task[None] | None = None
        self._jobs: set[asyncio.Task[None]] = set()
        self._ready = asyncio.Event()
        # Server process id of the LISTEN connection (None while disconnected).
        self.connection_pid: int | None = None

    async def start(self) -> None:
        """Start listening; returns once connected (or after a short grace period)."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="provider-listener")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._ready.wait(), timeout=_START_TIMEOUT_SECONDS)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for job in list(self._jobs):
            job.cancel()
        for job in list(self._jobs):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await job
        self._jobs.clear()
        self._ready.clear()

    def _dsn(self) -> str:
        return self._engine.url.set(drivername="postgresql").render_as_string(hide_password=False)

    def _spawn(self, work: Coroutine[Any, Any, None], name: str) -> None:
        async def guarded() -> None:
            try:
                await work
            except Exception as exc:
                # Type only: the message could carry a value of the instance.
                _log.error("provider %s failed (%s)", name, type(exc).__name__)

        job = asyncio.create_task(guarded())
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)

    async def _run(self) -> None:
        delay = self._min_delay
        while True:
            conn: asyncpg.Connection[Any] | None = None
            try:
                lost = asyncio.Event()
                conn = await asyncpg.connect(self._dsn())
                conn.add_termination_listener(lambda _c, event=lost: event.set())
                await conn.add_listener(PROVIDERS_CHANNEL, self._on_notify)
                self.connection_pid = conn.get_server_pid()
                # LISTEN is active before this, so no change can slip through the gap. In
                # the background: a hanging provider must not hold up the listener.
                self._spawn(self._manager.start_all(), "reconcile")
                self._ready.set()
                delay = self._min_delay
                await self._wait_until_lost(conn, lost)
                _log.warning("provider listener lost its connection; reconnecting")
            except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError, SQLAlchemyError) as exc:
                _log.warning("provider listener cannot connect (%s)", type(exc).__name__)
            except Exception as exc:
                _log.error("provider listener failed unexpectedly (%s)", type(exc).__name__)
            finally:
                self.connection_pid = None
                if conn is not None:
                    await self._close(conn)
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._max_delay)

    @staticmethod
    async def _close(conn: Any) -> None:
        try:
            await asyncio.wait_for(conn.close(), timeout=_CLOSE_TIMEOUT_SECONDS)
        except Exception:
            with contextlib.suppress(Exception):
                conn.terminate()

    async def _wait_until_lost(self, conn: Any, lost: asyncio.Event) -> None:
        while not lost.is_set():
            try:
                await asyncio.wait_for(lost.wait(), timeout=_PROBE_INTERVAL_SECONDS)
            except TimeoutError:
                try:
                    await asyncio.wait_for(
                        conn.fetchval("SELECT 1"), timeout=_PROBE_TIMEOUT_SECONDS
                    )
                except Exception as exc:
                    _log.warning("provider listener probe failed (%s)", type(exc).__name__)
                    lost.set()

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, payload: str) -> None:
        try:
            instance_id = uuid.UUID(payload)
        except ValueError:
            _log.warning("provider notification with a malformed payload ignored")
            return
        self._spawn(self._manager.apply(instance_id), "apply")
