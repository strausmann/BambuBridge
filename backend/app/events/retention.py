"""Retention: remove events and communication log entries older than the configured days.

The periods are the runtime settings ``retention.events_days`` and
``retention.communication_days``. :func:`run_retention` reads them from the database on
every run, so a change applies to the next run without a restart, and a store that has not
loaded yet can never apply the defaults over what the operator stored.

One run, with the cut-off ``now - days`` per table:

1. **Rows.** In the month the cut-off falls into, rows older than it are deleted
   (``DELETE ... WHERE occurred_at < cutoff``, limited to that month's partition). Outbox
   deliveries of events older than the events cut-off are deleted too: their event is gone
   after this run. That covers finished ones (``done``, ``failed``) and pending ones nobody
   holds; a pending delivery under a live lease is being worked on and stays until a later
   run. This step takes row locks only and is committed.
2. **Partitions.** Monthly partitions that lie entirely before the cut-off are dropped
   whole. Dropping needs the parent table exclusively for a moment, so every wait is bounded
   as for creating partitions (``DDL_LOCK_TIMEOUT_SECONDS``); if the time runs out the
   database error is raised and the next run tries again. Committed as well, right away,
   so the exclusive lock is held for the drop only.

Only partitions named like the ones :mod:`app.events.partitions` creates are dropped
(``events_y2026m12``); a partition somebody attached under another name is left alone, and
so are its rows older than the partial month.

:class:`RetentionMaintenance` runs this at startup and every day at 00:15 UTC.
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
from app.events.daily import DailyJob
from app.repositories.events import EVENTS_LOCK_NAMESPACE, set_local_lock_timeout
from app.settings_store.store import SettingsStore

_log = logging.getLogger(__name__)

# Partitioned table -> the setting that holds its retention period in days.
RETENTION_SETTINGS: dict[str, str] = {
    "events": "retention.events_days",
    "communication_log": "retention.communication_days",
}

DAILY_RUN_AT = time(0, 15, tzinfo=UTC)

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
    DELETE FROM event_deliveries
    WHERE event_occurred_at < :cutoff
      AND NOT (
          status = 'pending'
          AND claimed_until IS NOT NULL
          AND claimed_until >= clock_timestamp()
      )
    """
)


@dataclass(frozen=True)
class RetentionResult:
    """What one run removed. ``deleted_rows`` counts events and communication log entries."""

    dropped_partitions: list[str] = field(default_factory=list)
    deleted_rows: int = 0
    deleted_deliveries: int = 0


def _month_start(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, 1, tzinfo=UTC)


def _rowcount(result: Any) -> int:
    return int(cast("CursorResult[Any]", result).rowcount)


async def _delete_rows(session: AsyncSession, cutoffs: dict[str, datetime]) -> tuple[int, int]:
    deleted = 0
    for table, cutoff in cutoffs.items():
        # The table name comes from the fixed mapping above. The lower bound keeps the
        # statement inside the partition of the cut-off month; the older ones are dropped.
        result = await session.execute(
            text(f'DELETE FROM "{table}" WHERE occurred_at >= :start AND occurred_at < :cutoff'),  # noqa: S608
            {"start": _month_start(cutoff), "cutoff": cutoff},
        )
        deleted += _rowcount(result)
    deliveries = _rowcount(await session.execute(_DELETE_DELIVERIES, {"cutoff": cutoffs["events"]}))
    return deleted, deliveries


async def _drop_partitions(session: AsyncSession, cutoffs: dict[str, datetime]) -> list[str]:
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
        pattern = re.compile(rf"{table}_y(\d{{4}})m(\d{{2}})", re.ASCII)
        for name in (await session.scalars(_CHILDREN, {"parent": table})).all():
            match = pattern.fullmatch(name)
            if match is None:
                continue
            year, month = int(match.group(1)), int(match.group(2))
            if not (1 <= year <= 9998 and 1 <= month <= 12):
                continue
            next_year, next_month0 = divmod(year * 12 + month, 12)
            if datetime(next_year, next_month0 + 1, 1, tzinfo=UTC) > cutoff:
                continue
            # The name matched the pattern above: fixed table name and digits only.
            await session.execute(text(f'DROP TABLE "{name}"'))
            dropped.append(name)
    await set_local_lock_timeout(session, previous_timeout)
    return dropped


async def run_retention(
    session: AsyncSession, now: datetime, settings: SettingsStore
) -> RetentionResult:
    """Remove what is older than the retention periods, counted back from ``now``.

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
    await settings.reload_and_notify(session)
    cutoffs = {
        table: now - timedelta(days=int(settings.get(key)))
        for table, key in RETENTION_SETTINGS.items()
    }

    deleted_rows, deleted_deliveries = await _delete_rows(session, cutoffs)
    await session.commit()

    dropped = await _drop_partitions(session, cutoffs)
    await session.commit()
    return RetentionResult(
        dropped_partitions=dropped,
        deleted_rows=deleted_rows,
        deleted_deliveries=deleted_deliveries,
    )


class RetentionMaintenance(DailyJob):
    """Background task: run retention at startup and daily at 00:15 UTC.

    ``start`` does not wait for the first run. See :class:`app.events.daily.DailyJob` for
    failures and retries; the log lines carry partition names and counts, nothing else.
    """

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        retry_seconds: float = 60.0,
    ) -> None:
        super().__init__(
            label="retention",
            log=_log,
            run_at=DAILY_RUN_AT,
            clock=clock,
            sleep=sleep,
            retry_seconds=retry_seconds,
        )
        self._sessions = sessions
        self._settings = settings

    async def _work(self) -> None:
        async with self._sessions() as session:
            result = await run_retention(session, self._clock(), self._settings)
        if result.dropped_partitions:
            _log.info("dropped partitions: %s", ", ".join(result.dropped_partitions))
        if result.deleted_rows or result.deleted_deliveries:
            _log.info(
                "deleted %d rows and %d deliveries past retention",
                result.deleted_rows,
                result.deleted_deliveries,
            )
