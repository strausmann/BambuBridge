"""Monthly partitions of the partitioned tables, created ahead of time.

There is no default partition: a row for a month without a partition is refused by the
database. :func:`ensure_partitions` therefore keeps the partitions of the current and the
next months in place; :class:`PartitionMaintenance` runs it at startup and every day at
00:05 UTC.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_log = logging.getLogger(__name__)

# Parent tables partitioned by month on a timestamptz column. Fixed names from this module
# only: they are put into DDL, which cannot take bind parameters.
PARTITIONED_TABLES: tuple[str, ...] = ("events",)

# Serialises concurrent runs (several server processes starting at once) per transaction.
_LOCK_KEY = 0x6262_0002  # "bb" + 2

DAILY_RUN_AT = time(0, 5, tzinfo=UTC)
_START_TIMEOUT_SECONDS = 5.0
_MAX_SLEEP_SECONDS = 3600.0


def partition_name(table: str, year: int, month: int) -> str:
    return f"{table}_y{year:04d}m{month:02d}"


def _months(now: datetime, months_ahead: int) -> list[tuple[int, int]]:
    index = now.year * 12 + now.month - 1
    return [divmod(i, 12) for i in range(index, index + months_ahead + 1)]


async def ensure_partitions(
    session: AsyncSession, now: datetime, months_ahead: int = 2
) -> list[str]:
    """Create the missing partitions for the month of ``now`` (UTC) and ``months_ahead`` more.

    Returns the names of the partitions it created (``events_y2026m12``), oldest first; an
    empty list when all were there. Existing partitions are not touched, and no lock on the
    parent table is taken when nothing is missing. The caller commits.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    if months_ahead < 0:
        raise ValueError("months_ahead must not be negative")
    now = now.astimezone(UTC)
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})
    created: list[str] = []
    for table in PARTITIONED_TABLES:
        for year, month0 in _months(now, months_ahead):
            name = partition_name(table, year, month0 + 1)
            exists = await session.scalar(text("SELECT to_regclass(:name)"), {"name": name})
            if exists is not None:
                continue
            next_year, next_month0 = divmod(year * 12 + month0 + 1, 12)
            # Identifiers and bounds are built from the fixed table list and integers.
            await session.execute(
                text(
                    f'CREATE TABLE "{name}" PARTITION OF "{table}" FOR VALUES '
                    f"FROM ('{year:04d}-{month0 + 1:02d}-01 00:00:00+00') "
                    f"TO ('{next_year:04d}-{next_month0 + 1:02d}-01 00:00:00+00')"
                )
            )
            created.append(name)
    return created


def next_daily_run(now: datetime) -> datetime:
    """The next 00:05 UTC strictly after ``now``."""
    now = now.astimezone(UTC)
    today = datetime.combine(now.date(), DAILY_RUN_AT)
    return today if now < today else today + timedelta(days=1)


def _describe(exc: BaseException) -> str:
    """Class and SQLSTATE only: the driver text can carry values or a connection string."""
    if isinstance(exc, DBAPIError):
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        return f"{type(exc).__name__}, SQLSTATE {code or 'unknown'}"
    return type(exc).__name__


class PartitionMaintenance:
    """Background task: ensure the partitions at startup and daily at 00:05 UTC.

    A failed run (database away) is logged by type and repeated after ``retry_seconds``
    until it succeeds; the task itself never ends on an error. ``clock`` and ``sleep`` can
    be replaced in tests.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_seconds: float = 60.0,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._sleep = sleep
        self._retry_seconds = retry_seconds
        self._task: asyncio.Task[None] | None = None
        self._first_run_done = asyncio.Event()

    async def start(self) -> None:
        """Start the task; returns after the first run, or after a short grace period."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="partition-maintenance")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._first_run_done.wait(), timeout=_START_TIMEOUT_SECONDS)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._first_run_done.clear()

    async def run_once(self) -> bool:
        """Ensure the partitions now; ``False`` (and a log line) when that failed."""
        try:
            async with self._sessions() as session:
                created = await ensure_partitions(session, self._clock())
                await session.commit()
        except Exception as exc:
            # ``CancelledError`` is a BaseException and still propagates.
            _log.error("partition maintenance failed (%s)", _describe(exc))
            return False
        if created:
            _log.info("created partitions: %s", ", ".join(created))
        return True

    async def _run(self) -> None:
        while True:
            ok = await self.run_once()
            self._first_run_done.set()
            if not ok:
                await self._sleep(self._retry_seconds)
                continue
            due = next_daily_run(self._clock())
            # Sleep in bounded steps and re-read the clock: a suspended host or a clock
            # change must not shift the run by the time that was missed.
            while (remaining := (due - self._clock()).total_seconds()) > 0:
                await self._sleep(min(remaining, _MAX_SLEEP_SECONDS))
