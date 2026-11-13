"""Retention: remove events and communication log entries older than the configured days.

The periods are the runtime settings ``retention.events_days`` and
``retention.communication_days``. :func:`run_retention` reads them from the database on
every run, so a change applies to the next run without a restart, and a store that has not
loaded yet can never apply the defaults over what the operator stored.

The run counts back from the **database clock** (``clock_timestamp()``), not the host clock:
a host clock that runs ahead must not delete what is still current. If the two clocks
differ by more than ``MAX_CLOCK_DIFFERENCE`` the run is skipped altogether (one warning
line). The cut-offs are logged before anything is removed.

One run, with the cut-off ``database now - days`` per table:

1. **Rows.** In the month the cut-off falls into, rows older than it are deleted
   (``DELETE ... WHERE occurred_at < cutoff``, limited to that month's partition). Outbox
   deliveries of events older than the events cut-off are deleted too: their event is gone
   after this run. That covers finished ones (``done``, ``failed``) and pending ones nobody
   holds; a pending delivery under a live lease is being worked on and stays until a later
   run. Finished and unfinished ones are counted (and logged) apart: an unfinished delivery
   that goes is work a subscriber never did. This step takes row locks only and is
   committed.
2. **Partitions.** Monthly partitions that lie entirely before the cut-off are dropped
   whole; never one whose range holds or follows the database's present moment, whatever
   the period says. Dropping needs the parent table exclusively for a moment, so every
   wait is bounded as for creating partitions (``DDL_LOCK_TIMEOUT_SECONDS``); if the time
   runs out the database error is raised and the job tries again later. Committed as
   well, right away, so the exclusive lock is held for the drop only.

Only partitions named like the ones :mod:`app.events.partitions` creates are dropped
(``events_y2026m12``); a partition somebody attached under another name is left alone, and
so are its rows older than the partial month.

:class:`RetentionMaintenance` runs this ``STARTUP_DELAY_SECONDS`` (15 minutes) after startup
and every day at 00:15 UTC. The delay gives an operator who just shortened a period, or a
host whose clock is still being set, a moment before anything is deleted. A run that runs
into a lock (SQLSTATE 55P03, a long reader on the table) is repeated after 1, 5 and then
every 15 minutes, not every minute: each attempt holds up the inserts for a moment.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events import partitions
from app.events.daily import DailyJob, sqlstate
from app.repositories.events import EVENTS_LOCK_NAMESPACE, set_local_lock_timeout
from app.settings_store.store import SettingsStore

_log = logging.getLogger(__name__)

# Partitioned table -> the setting that holds its retention period in days.
RETENTION_SETTINGS: dict[str, str] = {
    "events": "retention.events_days",
    "communication_log": "retention.communication_days",
}

DAILY_RUN_AT = time(0, 15, tzinfo=UTC)
STARTUP_DELAY_SECONDS = 900.0
# A larger difference between the host clock and the database clock skips the run.
MAX_CLOCK_DIFFERENCE = timedelta(minutes=5)
# Waits after the first, second and every further run in a row that failed on a lock.
LOCK_BACKOFF_SECONDS = (60.0, 300.0, 900.0)
LOCK_NOT_AVAILABLE = "55P03"
# From this many skipped runs in a row on, each one is logged as an error.
SKIPPED_RUNS_ERROR = 3

# Children of ``parent`` that are ordinary tables and that the bare name resolves to.
_CHILDREN = text(
    """
    SELECT c.relname
    FROM pg_inherits AS i
    JOIN pg_class AS c ON c.oid = i.inhrelid
    WHERE i.inhparent = to_regclass(:parent)
      AND c.relkind = 'r'
      AND c.oid = to_regclass(quote_ident(c.relname))
    ORDER BY c.relname
    """
)

# A pending delivery whose lease has not run out belongs to a worker right now (the same
# test as in ``outbox.CLAIM_STATEMENT``, negated).
_DELETE_DELIVERIES = text(
    """
    WITH deleted AS (
        DELETE FROM event_deliveries
        WHERE event_occurred_at < :cutoff
          AND NOT (
              status = 'pending'
              AND claimed_until IS NOT NULL
              AND claimed_until >= clock_timestamp()
          )
        RETURNING status
    )
    SELECT count(*) FILTER (WHERE status <> 'pending') AS finished,
           count(*) FILTER (WHERE status = 'pending') AS pending
    FROM deleted
    """
)


@dataclass(frozen=True)
class RetentionResult:
    """What one run removed. ``deleted_rows`` counts events and communication log entries;
    ``deleted_deliveries`` the finished outbox deliveries (``done``, ``failed``) and
    ``deleted_pending_deliveries`` the unfinished ones. ``skipped``: the clocks differed."""

    dropped_partitions: list[str] = field(default_factory=list)
    deleted_rows: int = 0
    deleted_deliveries: int = 0
    deleted_pending_deliveries: int = 0
    skipped: bool = False


def _month_start(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, 1, tzinfo=UTC)


def _rowcount(result: Any) -> int:
    return int(cast("CursorResult[Any]", result).rowcount)


async def _database_now(session: AsyncSession) -> datetime:
    value = await session.scalar(text("SELECT clock_timestamp()"))
    return cast("datetime", value)


def may_drop(partition_end: datetime, *, cutoff: datetime, database_now: datetime) -> bool:
    """Whether a partition that ends at ``partition_end`` lies entirely before the cut-off,
    and entirely before the database's present moment (whatever the cut-off is)."""
    return partition_end <= cutoff and partition_end <= database_now


async def _delete_rows(session: AsyncSession, cutoffs: dict[str, datetime]) -> tuple[int, int, int]:
    deleted = 0
    for table, cutoff in cutoffs.items():
        # The table name comes from the fixed mapping above. The lower bound keeps the
        # statement inside the partition of the cut-off month; the older ones are dropped.
        result = await session.execute(
            text(f'DELETE FROM "{table}" WHERE occurred_at >= :start AND occurred_at < :cutoff'),  # noqa: S608
            {"start": _month_start(cutoff), "cutoff": cutoff},
        )
        deleted += _rowcount(result)
    counts = (await session.execute(_DELETE_DELIVERIES, {"cutoff": cutoffs["events"]})).one()
    return deleted, int(counts.finished), int(counts.pending)


async def _partition_with_newest_row(
    session: AsyncSession, table: str, candidates: list[tuple[datetime, str]]
) -> str | None:
    """The candidate partition that holds the newest row of ``table``, if any.

    A guard for a clock jump that host and database share (the comparison of the two
    cannot see it): whatever the cut-off says, the newest data stays. Cheap: ``EXISTS``
    stops at the first row, and the range condition is pruned to the later partitions.
    """
    if not candidates:
        return None
    # Names and the table come from the catalog and the fixed mapping (digits only).
    newer = await session.scalar(
        text(f'SELECT EXISTS (SELECT 1 FROM "{table}" WHERE occurred_at >= :end)'),  # noqa: S608
        {"end": candidates[-1][0]},
    )
    if newer:
        return None
    for _, name in reversed(candidates):
        if await session.scalar(text(f'SELECT EXISTS (SELECT 1 FROM "{name}")')):  # noqa: S608
            return name
    return None


async def _drop_partitions(
    session: AsyncSession, cutoffs: dict[str, datetime], database_now: datetime
) -> list[str]:
    # Both waits are bounded: for another run (the advisory lock shared with
    # ``ensure_partitions``) and for the parent table.
    previous_timeout = await set_local_lock_timeout(
        session, f"{int(partitions.DDL_LOCK_TIMEOUT_SECONDS * 1000)}ms"
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :key)"),
        {"namespace": EVENTS_LOCK_NAMESPACE, "key": partitions.PARTITIONS_LOCK_KEY},
    )
    dropped: list[str] = []
    for table, cutoff in cutoffs.items():
        candidates: list[tuple[datetime, str]] = []
        pattern = re.compile(rf"{table}_y(\d{{4}})m(\d{{2}})", re.ASCII)
        for name in (await session.scalars(_CHILDREN, {"parent": table})).all():
            match = pattern.fullmatch(name)
            if match is None:
                continue
            year, month = int(match.group(1)), int(match.group(2))
            if not (1 <= year <= 9998 and 1 <= month <= 12):
                continue
            next_year, next_month0 = divmod(year * 12 + month, 12)
            end = datetime(next_year, next_month0 + 1, 1, tzinfo=UTC)
            if may_drop(end, cutoff=cutoff, database_now=database_now):
                candidates.append((end, name))
        keep = await _partition_with_newest_row(session, table, sorted(candidates))
        for _, name in sorted(candidates):
            if name == keep:
                _log.warning("kept partition %s: it holds the newest rows of %s", name, table)
                continue
            # The name matched the pattern above: fixed table name and digits only.
            await session.execute(text(f'DROP TABLE "{name}"'))
            dropped.append(name)
    await set_local_lock_timeout(session, previous_timeout)
    return dropped


async def run_retention(
    session: AsyncSession, now: datetime, settings: SettingsStore
) -> RetentionResult:
    """Remove what is older than the retention periods, counted back from the database clock.

    ``now`` is the host clock; it only serves to compare the two. If they differ by more
    than ``MAX_CLOCK_DIFFERENCE`` nothing is removed and the result says ``skipped``.

    Unlike the rest of the event code this **commits**, twice (after the rows and after the
    partitions; see the module text): give it a session of its own, never one with other
    work in it. Before anything is removed, ``settings`` is reloaded from the database
    through ``session``; its subscribers are told about changes as usual.

    Raises the database error if a wait runs out (SQLSTATE 55P03); the rows deleted in step
    one stay deleted, and the caller has to roll back.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    now = now.astimezone(UTC)
    database_now = (await _database_now(session)).astimezone(UTC)
    difference = abs(database_now - now)
    if difference > MAX_CLOCK_DIFFERENCE:
        await session.rollback()
        _log.warning(
            "retention skipped: application and database clocks differ by %d s",
            int(difference.total_seconds()),
        )
        return RetentionResult(skipped=True)
    await settings.reload_and_notify(session)
    cutoffs = {
        table: database_now - timedelta(days=int(settings.get(key)))
        for table, key in RETENTION_SETTINGS.items()
    }
    _log.info(
        "retention cut-offs: events before %s, communication log before %s",
        cutoffs["events"].isoformat(),
        cutoffs["communication_log"].isoformat(),
    )

    deleted_rows, finished, pending = await _delete_rows(session, cutoffs)
    await session.commit()

    dropped = await _drop_partitions(session, cutoffs, database_now)
    await session.commit()
    return RetentionResult(
        dropped_partitions=dropped,
        deleted_rows=deleted_rows,
        deleted_deliveries=finished,
        deleted_pending_deliveries=pending,
    )


class RetentionMaintenance(DailyJob):
    """Background task: run retention ``startup_delay_seconds`` after startup and daily at
    00:15 UTC.

    ``start`` does not wait for the first run. See :class:`app.events.daily.DailyJob` for
    failures; a lock timeout backs off (``LOCK_BACKOFF_SECONDS``), any other failure is
    repeated after ``retry_seconds``. The log lines carry cut-offs, partition names and
    counts, nothing else.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_seconds: float = 60.0,
        startup_delay_seconds: float = STARTUP_DELAY_SECONDS,
    ) -> None:
        super().__init__(
            label="retention",
            log=_log,
            run_at=DAILY_RUN_AT,
            clock=clock,
            sleep=sleep,
            retry_seconds=retry_seconds,
            startup_delay_seconds=startup_delay_seconds,
        )
        self._sessions = sessions
        self._settings = settings
        self._skipped_in_a_row = 0

    async def _work(self) -> None:
        async with self._sessions() as session:
            result = await run_retention(session, self._clock(), self._settings)
        if result.skipped:
            self._skipped_in_a_row += 1
            if self._skipped_in_a_row >= SKIPPED_RUNS_ERROR:
                _log.error(
                    "retention skipped %d runs in a row: the clocks still differ, "
                    "nothing is pruned",
                    self._skipped_in_a_row,
                )
            return
        self._skipped_in_a_row = 0
        if result.dropped_partitions:
            _log.info("dropped partitions: %s", ", ".join(result.dropped_partitions))
        if result.deleted_rows or result.deleted_deliveries:
            _log.info(
                "deleted %d rows and %d finished deliveries past retention",
                result.deleted_rows,
                result.deleted_deliveries,
            )
        if result.deleted_pending_deliveries:
            _log.warning(
                "deleted %d pending deliveries whose event is past retention",
                result.deleted_pending_deliveries,
            )

    def _retry_delay(self, error: Exception, failures: int) -> float:
        if sqlstate(error) == LOCK_NOT_AVAILABLE:
            return LOCK_BACKOFF_SECONDS[min(failures, len(LOCK_BACKOFF_SECONDS)) - 1]
        return super()._retry_delay(error, failures)
