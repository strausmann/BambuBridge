"""A background task that runs once at startup (optionally after a delay) and then every day
at a fixed UTC time."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta

from sqlalchemy.exc import DBAPIError

_MAX_SLEEP_SECONDS = 3600.0


def next_run_at(now: datetime, at: time) -> datetime:
    """The next moment the UTC clock shows ``at``, strictly after ``now``."""
    now = now.astimezone(UTC)
    today = datetime.combine(now.date(), at)
    return today if now < today else today + timedelta(days=1)


def sqlstate(exc: BaseException) -> str | None:
    """The SQLSTATE of a database error, ``None`` for anything else."""
    if isinstance(exc, DBAPIError):
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        return str(code) if code else None
    return None


def describe_error(exc: BaseException) -> str:
    """Class and SQLSTATE only: the driver text can carry values or a connection string."""
    if isinstance(exc, DBAPIError):
        return f"{type(exc).__name__}, SQLSTATE {sqlstate(exc) or 'unknown'}"
    return type(exc).__name__


class DailyJob:
    """Runs :meth:`_work` at startup (after ``startup_delay_seconds``) and every day at
    ``run_at`` (UTC).

    A failed run (database away) is logged by type and repeated after
    :meth:`_retry_delay` (``retry_seconds`` unless a subclass decides otherwise) until it
    succeeds; the task itself never ends on an error. Cancelling it (``stop``) is
    safe at any point: a run in progress loses its open transaction, nothing else.
    ``clock`` and ``sleep`` can be replaced in tests.
    """

    def __init__(
        self,
        *,
        label: str,
        log: logging.Logger,
        run_at: time,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_seconds: float = 60.0,
        start_timeout_seconds: float = 0.0,
        startup_delay_seconds: float = 0.0,
    ) -> None:
        self._label = label
        self._log = log
        self._run_at = run_at
        self._clock = clock
        self._sleep = sleep
        self._retry_seconds = retry_seconds
        self._start_timeout_seconds = start_timeout_seconds
        self._startup_delay_seconds = startup_delay_seconds
        self._task: asyncio.Task[None] | None = None
        self._first_run_done = asyncio.Event()

    async def _work(self) -> None:
        """One run. Raise to have it logged and repeated."""
        raise NotImplementedError

    async def start(self) -> None:
        """Start the task; waits up to ``start_timeout_seconds`` for the first run."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name=self._label.replace(" ", "-"))
        if self._start_timeout_seconds > 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._first_run_done.wait(), timeout=self._start_timeout_seconds
                )

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                # The task had already died. Shutdown goes on (the caller still has to stop
                # the listener and dispose of the engine), so this is logged, by type only.
                self._log.error("%s task ended unexpectedly (%s)", self._label, type(exc).__name__)
        self._first_run_done.clear()

    async def run_once(self) -> bool:
        """Run now; ``False`` (and a log line) when that failed."""
        return await self._attempt() is None

    async def _attempt(self) -> Exception | None:
        try:
            await self._work()
        except Exception as exc:
            # ``CancelledError`` is a BaseException and still propagates.
            self._log.error("%s failed (%s)", self._label, describe_error(exc))
            return exc
        return None

    def _retry_delay(self, error: Exception, failures: int) -> float:  # noqa: ARG002
        """Seconds to wait after the ``failures``-th failed run in a row (a hook: the
        default ignores both and waits ``retry_seconds``)."""
        return self._retry_seconds

    async def _run(self) -> None:
        if self._startup_delay_seconds > 0:
            await self._sleep(self._startup_delay_seconds)
        failures = 0
        while True:
            error = await self._attempt()
            self._first_run_done.set()
            if error is not None:
                failures += 1
                await self._sleep(self._retry_delay(error, failures))
                continue
            failures = 0
            due = next_run_at(self._clock(), self._run_at)
            # Sleep in bounded steps and re-read the clock: a suspended host or a clock
            # change must not shift the run by the time that was missed.
            while (remaining := (due - self._clock()).total_seconds()) > 0:
                await self._sleep(min(remaining, _MAX_SLEEP_SECONDS))
