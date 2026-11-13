from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.engine import make_engine
from app.db.session import make_session_factory
from app.events import partitions, retention
from app.events.daily import next_run_at
from app.events.partitions import ensure_partitions
from app.events.retention import (
    STARTUP_DELAY_SECONDS,
    RetentionMaintenance,
    RetentionResult,
    may_drop,
    run_retention,
)
from app.models.communication_entry import CommunicationEntry
from app.models.event import Event
from app.security.secret_box import secret_box_from_key
from app.settings_store.store import SettingsStore
from tests.conftest import DEAD_DATABASE_URL
from tests.integration.events.test_partition_job import FakeTime

INSTANCE = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
# The tests live in 2045: with the default periods (events 90 days, communication log 30)
# the cut-offs are 22 March 12:00 and 21 May 12:00.
NOW = datetime(2045, 6, 20, 12, 0, tzinfo=UTC)
EVENTS_CUTOFF = datetime(2045, 3, 22, 12, 0, tzinfo=UTC)
LOG_CUTOFF = datetime(2045, 5, 21, 12, 0, tzinfo=UTC)
SECOND = timedelta(seconds=1)


def at(month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2045, month, day, hour, minute, second, tzinfo=UTC)


REAL_DATABASE_NOW = retention._database_now


class DatabaseClock:
    """Stands in for the database clock, which a test cannot move to 2045."""

    def __init__(self) -> None:
        self.source: Callable[[], datetime] = lambda: NOW

    async def now(self, session: AsyncSession) -> datetime:
        return self.source()


@pytest.fixture(autouse=True)
def database_clock(monkeypatch: pytest.MonkeyPatch) -> DatabaseClock:
    clock = DatabaseClock()
    monkeypatch.setattr(retention, "_database_now", clock.now)
    return clock


async def _children(sessions: async_sessionmaker[AsyncSession], parent: str) -> list[str]:
    async with sessions() as session:
        rows = await session.scalars(
            text(
                "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                "WHERE i.inhparent = to_regclass(:parent) ORDER BY c.relname"
            ),
            {"parent": parent},
        )
        return list(rows.all())


@pytest_asyncio.fixture(autouse=True)
async def year_2045(sessions: async_sessionmaker[AsyncSession], current_partitions: None) -> None:
    """Only the partitions January to June 2045 exist, for both tables."""
    for parent in ("events", "communication_log"):
        names = await _children(sessions, parent)
        async with sessions() as session:
            for name in names:
                await session.execute(text(f'DROP TABLE "{name}"'))
            await session.commit()
    async with sessions() as session:
        await ensure_partitions(session, at(1, 1), months_ahead=5)
        await session.commit()


async def _add_events(sessions: async_sessionmaker[AsyncSession], *moments: datetime) -> None:
    async with sessions() as session:
        for moment in moments:
            session.add(
                Event(
                    id=uuid.uuid4(),
                    occurred_at=moment,
                    type="integration.demo.tick",
                    payload={},
                    schema_version=1,
                )
            )
        await session.commit()


async def _add_log(sessions: async_sessionmaker[AsyncSession], *moments: datetime) -> None:
    async with sessions() as session:
        for moment in moments:
            session.add(
                CommunicationEntry(
                    id=uuid.uuid4(),
                    occurred_at=moment,
                    instance_id=INSTANCE,
                    direction="outbound",
                    method="GET",
                    target="/",
                    duration_ms=1,
                    request_headers={},
                    response_headers={},
                    truncated=False,
                )
            )
        await session.commit()


async def _event_times(sessions: async_sessionmaker[AsyncSession]) -> list[datetime]:
    async with sessions() as session:
        return list(
            (await session.scalars(select(Event.occurred_at).order_by("occurred_at"))).all()
        )


async def _log_times(sessions: async_sessionmaker[AsyncSession]) -> list[datetime]:
    async with sessions() as session:
        return list(
            (
                await session.scalars(
                    select(CommunicationEntry.occurred_at).order_by("occurred_at")
                )
            ).all()
        )


def _events(*months: int) -> list[str]:
    return [f"events_y2045m{month:02d}" for month in months]


def _log(*months: int) -> list[str]:
    return [f"communication_log_y2045m{month:02d}" for month in months]


_CLOCK: list[DatabaseClock] = []


async def _run(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore, now: datetime = NOW
) -> RetentionResult:
    """One run at ``now``, with the database clock showing the same moment."""
    if _CLOCK:
        _CLOCK[0].source = lambda: now
    async with sessions() as session:
        return await run_retention(session, now, store)


@pytest.fixture(autouse=True)
def _clock_for_run(database_clock: DatabaseClock) -> Iterator[None]:
    _CLOCK[:] = [database_clock]
    yield
    _CLOCK.clear()


async def test_retention_drops_whole_partitions_and_deletes_partial(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    kept_events = [EVENTS_CUTOFF, at(4, 10), at(6, 20, 11)]
    await _add_events(
        sessions,
        at(1, 15),  # January and February go with their partitions
        at(2, 28, 23, 59, 59),
        at(3, 1),  # March is the partial month: these two are deleted
        EVENTS_CUTOFF - SECOND,
        *kept_events,
    )
    kept_log = [LOG_CUTOFF, at(6, 1)]
    await _add_log(
        sessions,
        at(2, 1),
        at(4, 30, 23, 59, 59),  # April ended before the cut-off: dropped whole
        at(5, 1),  # May is the partial month
        LOG_CUTOFF - SECOND,
        *kept_log,
    )

    result = await _run(sessions, store)

    assert result == RetentionResult(
        dropped_partitions=[*_events(1, 2), *_log(1, 2, 3, 4)], deleted_rows=4, deleted_deliveries=0
    )
    assert await _children(sessions, "events") == _events(3, 4, 5, 6)
    assert await _children(sessions, "communication_log") == _log(5, 6)
    assert await _event_times(sessions) == kept_events
    assert await _log_times(sessions) == kept_log

    assert await _run(sessions, store) == RetentionResult()


async def test_retention_follows_setting_change_without_restart(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    await _add_events(sessions, at(2, 1), at(4, 10), at(5, 21, 11), at(5, 21, 12), at(6, 1))
    await _add_log(sessions, at(5, 1), at(5, 25), at(6, 10, 11), at(6, 10, 12))

    # Longer periods first: nothing is old enough.
    async with sessions() as session:
        await store.set_many(
            session, {"retention.events_days": 3650, "retention.communication_days": 3650}
        )
    assert await _run(sessions, store) == RetentionResult()
    assert len(await _event_times(sessions)) == 5

    # Shorter ones: 30 days for events (21 May 12:00), 10 for the log (10 June 12:00).
    async with sessions() as session:
        await store.set_many(
            session, {"retention.events_days": 30, "retention.communication_days": 10}
        )
    result = await _run(sessions, store)

    assert result == RetentionResult(
        dropped_partitions=[*_events(1, 2, 3, 4), *_log(1, 2, 3, 4, 5)],
        deleted_rows=2,
        deleted_deliveries=0,
    )
    assert await _event_times(sessions) == [at(5, 21, 12), at(6, 1)]
    assert await _log_times(sessions) == [at(6, 10, 12)]


async def test_retention_reads_the_periods_from_the_database_before_it_removes_anything(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    await _add_events(sessions, at(1, 15))
    async with sessions() as session:
        await store.set_many(
            session, {"retention.events_days": 3650, "retention.communication_days": 3650}
        )
    # A store that has not loaded anything yet answers with the defaults (90 and 30 days).
    unloaded = SettingsStore(secret_box_from_key(b"A" * 32))
    assert unloaded.get("retention.events_days") == 90

    assert await _run(sessions, unloaded) == RetentionResult()

    assert unloaded.get("retention.events_days") == 3650
    assert await _event_times(sessions) == [at(1, 15)]
    assert await _children(sessions, "events") == _events(1, 2, 3, 4, 5, 6)


async def test_retention_keeps_the_month_that_ends_after_the_cutoff(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    async with sessions() as session:
        await store.set_many(
            session, {"retention.events_days": 1, "retention.communication_days": 1}
        )
    await _add_events(sessions, at(3, 31, 23, 59, 59), at(4, 1), at(4, 1, 0, 0, 1))

    # One second before the cut-off reaches the end of March: March is still partial.
    early = await _run(sessions, store, at(4, 1, 23, 59, 59))
    assert early.dropped_partitions == [*_events(1, 2), *_log(1, 2)]
    assert await _event_times(sessions) == [at(3, 31, 23, 59, 59), at(4, 1), at(4, 1, 0, 0, 1)]

    # The cut-off is 1 April 00:00 exactly: March lies entirely before it.
    result = await _run(sessions, store, at(4, 2))
    assert result == RetentionResult(dropped_partitions=[*_events(3), *_log(3)])
    assert await _event_times(sessions) == [at(4, 1), at(4, 1, 0, 0, 1)]

    # The current month and the ones after it are never dropped, whatever the period.
    assert await _children(sessions, "events") == _events(4, 5, 6)


async def _add_delivery(
    session: AsyncSession,
    *,
    subscriber: str,
    status: str,
    event_occurred_at: datetime,
    lease_seconds: int | None = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO event_deliveries "
            "(event_id, event_occurred_at, subscriber, status, available_at, claimed_by, "
            " claimed_until) VALUES (gen_random_uuid(), :at, :subscriber, :status, :at, "
            " CASE WHEN CAST(:lease AS integer) IS NULL THEN NULL ELSE 'worker-1' END, "
            " clock_timestamp() + make_interval(secs => CAST(:lease AS integer)))"
        ),
        {
            "at": event_occurred_at,
            "subscriber": subscriber,
            "status": status,
            "lease": lease_seconds,
        },
    )


async def _subscribers(sessions: async_sessionmaker[AsyncSession]) -> list[str]:
    async with sessions() as session:
        rows = await session.scalars(
            text("SELECT subscriber FROM event_deliveries ORDER BY subscriber")
        )
        return list(rows.all())


async def test_retention_prunes_deliveries_but_never_one_under_a_live_lease(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    old, recent = at(1, 15), EVENTS_CUTOFF
    async with sessions() as session:
        await _add_delivery(session, subscriber="old_done", status="done", event_occurred_at=old)
        await _add_delivery(
            session, subscriber="old_failed", status="failed", event_occurred_at=old
        )
        await _add_delivery(
            session, subscriber="old_pending", status="pending", event_occurred_at=old
        )
        await _add_delivery(
            session,
            subscriber="old_lease_expired",
            status="pending",
            event_occurred_at=old,
            lease_seconds=-5,
        )
        await _add_delivery(
            session,
            subscriber="old_leased",
            status="pending",
            event_occurred_at=EVENTS_CUTOFF - SECOND,
            lease_seconds=300,
        )
        await _add_delivery(session, subscriber="new_done", status="done", event_occurred_at=recent)
        await _add_delivery(
            session, subscriber="new_pending", status="pending", event_occurred_at=recent
        )
        await session.commit()

    result = await _run(sessions, store)

    # Finished ones and unfinished ones nobody holds are counted apart.
    assert (result.deleted_deliveries, result.deleted_pending_deliveries) == (2, 2)
    assert await _subscribers(sessions) == ["new_done", "new_pending", "old_leased"]

    # Once the worker is done (or its lease has run out) a later run removes it.
    async with sessions() as session:
        await session.execute(
            text(
                "UPDATE event_deliveries "
                "SET claimed_until = clock_timestamp() - interval '1 second' "
                "WHERE subscriber = 'old_leased'"
            )
        )
        await session.commit()
    assert (await _run(sessions, store)).deleted_pending_deliveries == 1
    assert await _subscribers(sessions) == ["new_done", "new_pending"]


async def test_retention_leaves_foreign_partitions_and_lookalikes_alone(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    async with sessions() as session:
        # A partition of events under a name of its own, entirely before the cut-off.
        await session.execute(
            text(
                "CREATE TABLE events_archive PARTITION OF events "
                "FOR VALUES FROM ('2044-01-01 00:00:00+00') TO ('2044-02-01 00:00:00+00')"
            )
        )
        # A partition whose name has the pattern but names no month.
        await session.execute(
            text(
                'CREATE TABLE "events_y2044m13" PARTITION OF events '
                "FOR VALUES FROM ('2044-03-01 00:00:00+00') TO ('2044-04-01 00:00:00+00')"
            )
        )
        # A table that only carries the name of a monthly partition.
        await session.execute(text('CREATE TABLE "events_y2044m05" (id integer)'))
        await session.commit()
    try:
        result = await _run(sessions, store)

        assert result.dropped_partitions == [*_events(1, 2), *_log(1, 2, 3, 4)]
        assert await _children(sessions, "events") == [
            "events_archive",
            "events_y2044m13",
            *_events(3, 4, 5, 6),
        ]
        async with sessions() as session:
            assert await session.scalar(text("SELECT to_regclass('events_y2044m05')")) is not None
    finally:
        async with sessions() as session:
            await session.execute(text('DROP TABLE IF EXISTS "events_y2044m05"'))
            await session.execute(text('DROP TABLE IF EXISTS "events_y2044m13"'))
            await session.execute(text("DROP TABLE IF EXISTS events_archive"))
            await session.commit()


async def test_retention_gives_up_when_the_table_is_in_use_and_keeps_the_deleted_rows(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    await _add_events(sessions, at(1, 15), at(3, 1), at(4, 10))
    monkeypatch.setattr(partitions, "DDL_LOCK_TIMEOUT_SECONDS", 0.3)
    # A reader keeps its transaction open: dropping a partition needs the table exclusively.
    await db_session.execute(text("SELECT count(*) FROM events"))

    with pytest.raises(DBAPIError) as exc:
        await asyncio.wait_for(_run(sessions, store), timeout=5)
    assert getattr(exc.value.orig, "sqlstate", None) == "55P03"  # lock_not_available

    await db_session.rollback()
    # Step one was committed: the row of the partial month is gone, the partitions are not.
    assert await _event_times(sessions) == [at(1, 15), at(4, 10)]
    assert await _children(sessions, "events") == _events(1, 2, 3, 4, 5, 6)

    result = await _run(sessions, store)
    assert result == RetentionResult(dropped_partitions=[*_events(1, 2), *_log(1, 2, 3, 4)])
    assert await _event_times(sessions) == [at(4, 10)]


async def test_concurrent_retention_runs_drop_each_partition_once(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    async def one() -> RetentionResult:
        return await _run(sessions, SettingsStore(secret_box_from_key(b"A" * 32)))

    results = await asyncio.wait_for(asyncio.gather(one(), one(), one()), timeout=10)

    dropped = sorted(name for result in results for name in result.dropped_partitions)
    assert dropped == sorted([*_events(1, 2), *_log(1, 2, 3, 4)])


@pytest.mark.parametrize("now", [datetime(2045, 6, 20), "2045-06-20"])
async def test_retention_needs_an_aware_datetime(
    now: object, db_session: AsyncSession, store: SettingsStore
):
    with pytest.raises(ValueError, match="timezone-aware"):
        await run_retention(db_session, now, store)  # type: ignore[arg-type]


async def test_retention_takes_utc_whatever_the_offset_of_now(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    await _add_events(sessions, EVENTS_CUTOFF - SECOND, EVENTS_CUTOFF)

    result = await _run(sessions, store, NOW.astimezone(timezone(timedelta(hours=9))))

    assert result.deleted_rows == 1
    assert await _event_times(sessions) == [EVENTS_CUTOFF]


# --- the daily job -------------------------------------------------------------------------


def test_the_job_runs_at_0015_utc():
    assert retention.DAILY_RUN_AT.isoformat() == "00:15:00+00:00"
    assert next_run_at(at(6, 20, 0, 14, 59), retention.DAILY_RUN_AT) == at(6, 20, 0, 15)
    assert next_run_at(at(6, 20, 0, 15), retention.DAILY_RUN_AT) == at(6, 21, 0, 15)
    assert next_run_at(at(6, 30, 23, 59), retention.DAILY_RUN_AT) == at(7, 1, 0, 15)


async def test_job_runs_at_start_and_again_at_0015_utc(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    monkeypatch: pytest.MonkeyPatch,
    database_clock: DatabaseClock,
):
    runs: list[datetime] = []
    real = retention.run_retention

    async def recording(
        session: AsyncSession, now: datetime, settings: SettingsStore
    ) -> RetentionResult:
        runs.append(now)
        return await real(session, now, settings)

    monkeypatch.setattr(retention, "run_retention", recording)
    time = FakeTime(at(6, 20, 23, 50), max_sleeps=3)
    database_clock.source = time.clock
    job = RetentionMaintenance(sessions, store, clock=time.clock, sleep=time.sleep)

    await job.start()
    for _ in range(500):
        if len(time.sleeps) >= 3:  # the third sleep starts once the second run is through
            break
        await asyncio.sleep(0.01)
    await job.stop()

    # 15 minutes after the start, then at 00:15.
    assert runs[:2] == [at(6, 21, 0, 5), at(6, 21, 0, 15)]
    assert time.sleeps[:2] == [STARTUP_DELAY_SECONDS, 600.0]
    assert await _children(sessions, "events") == _events(3, 4, 5, 6)


async def test_job_start_does_not_wait_for_the_first_run_and_stop_cancels_it(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    started = asyncio.Event()

    async def hanging(
        session: AsyncSession, now: datetime, settings: SettingsStore
    ) -> RetentionResult:
        await session.execute(text("SELECT count(*) FROM events"))  # an open transaction
        started.set()
        await asyncio.sleep(3600)
        raise AssertionError("not reached")

    monkeypatch.setattr(retention, "run_retention", hanging)
    job = RetentionMaintenance(sessions, store, startup_delay_seconds=0)

    with caplog.at_level(logging.DEBUG, logger="app.events.retention"):
        await asyncio.wait_for(job.start(), timeout=1)
        await asyncio.wait_for(started.wait(), timeout=5)
        task = job._task
        await asyncio.wait_for(job.stop(), timeout=5)

    assert task is not None and task.cancelled()
    assert not caplog.records
    # The cancelled run left no open transaction behind: the table can be changed at once.
    async with sessions() as session:
        await session.execute(text("SET LOCAL lock_timeout = '2s'"))
        await session.execute(text('DROP TABLE "events_y2045m01"'))
        await session.commit()


async def test_job_logs_names_and_counts_only(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    caplog: pytest.LogCaptureFixture,
):
    await _add_events(sessions, at(3, 1))
    async with sessions() as session:
        await _add_delivery(
            session, subscriber="old_done", status="done", event_occurred_at=at(1, 1)
        )
        for name in ("old_pending_1", "old_pending_2"):
            await _add_delivery(
                session, subscriber=name, status="pending", event_occurred_at=at(1, 1)
            )
        await session.commit()
    job = RetentionMaintenance(sessions, store, clock=lambda: NOW)
    cutoffs = (
        "retention cut-offs: events before 2045-03-22T12:00:00+00:00, "
        "communication log before 2045-05-21T12:00:00+00:00"
    )

    with caplog.at_level(logging.INFO, logger="app.events.retention"):
        assert await job.run_once() is True
        assert await job.run_once() is True  # nothing left: only the cut-offs again

    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("INFO", cutoffs),
        ("INFO", "dropped partitions: " + ", ".join([*_events(1, 2), *_log(1, 2, 3, 4)])),
        ("INFO", "deleted 1 rows and 1 finished deliveries past retention"),
        ("WARNING", "deleted 2 pending deliveries whose event is past retention"),
        ("INFO", cutoffs),
    ]


async def test_job_logs_a_failure_by_type_and_retries(
    store: SettingsStore, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    engine = make_engine(DEAD_DATABASE_URL)
    time = FakeTime(at(6, 20, 23, 50), max_sleeps=3)
    # The real database clock: reading it is what fails.
    monkeypatch.setattr(retention, "_database_now", REAL_DATABASE_NOW)
    job = RetentionMaintenance(
        make_session_factory(engine), store, clock=time.clock, sleep=time.sleep, retry_seconds=7.0
    )
    try:
        with caplog.at_level(logging.ERROR, logger="app.events.retention"):
            await job.start()
            for _ in range(200):
                if len(time.sleeps) >= 3:
                    break
                await asyncio.sleep(0.01)
            await job.stop()
    finally:
        await engine.dispose()

    # Not a lock timeout: retried after the fixed time, after the delay at startup.
    assert time.sleeps == [STARTUP_DELAY_SECONDS, 7.0, 7.0]
    messages = [r.getMessage() for r in caplog.records]
    assert messages
    assert all(m.startswith("retention failed (") for m in messages)
    assert not any("127.0.0.1" in m or "://" in m for m in messages)


async def test_job_reports_a_lock_timeout_with_its_sqlstate(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(partitions, "DDL_LOCK_TIMEOUT_SECONDS", 0.3)
    await db_session.execute(text("SELECT count(*) FROM events"))
    job = RetentionMaintenance(sessions, store, clock=lambda: NOW)

    with caplog.at_level(logging.ERROR, logger="app.events.retention"):
        assert await asyncio.wait_for(job.run_once(), timeout=5) is False
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        "retention failed (DBAPIError, SQLSTATE 55P03)"
    ]

    await db_session.rollback()
    assert await job.run_once() is True


async def test_app_runs_retention_in_its_lifespan(app: FastAPI):
    assert app.state.retention_maintenance is None

    async with app.router.lifespan_context(app):
        job = app.state.retention_maintenance
        assert isinstance(job, RetentionMaintenance)
        task = job._task
        assert task is not None and task.get_name() == "retention"

    assert task.done()
    assert app.state.retention_maintenance is None


# --- fix round 1: start delay, logs, back-off, the drop guard ------------------------------


def test_the_first_run_waits_15_minutes_after_startup():
    assert STARTUP_DELAY_SECONDS == 900.0


async def test_cutoffs_are_logged_before_anything_is_deleted(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    seen: list[list[str]] = []
    real = retention._delete_rows

    async def deleting(*args: object) -> object:
        seen.append([r.getMessage() for r in caplog.records])
        return await real(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(retention, "_delete_rows", deleting)
    with caplog.at_level(logging.INFO, logger="app.events.retention"):
        await _run(sessions, store)

    assert len(seen) == 1
    assert seen[0] == [
        "retention cut-offs: events before 2045-03-22T12:00:00+00:00, "
        "communication log before 2045-05-21T12:00:00+00:00"
    ]


async def test_the_cutoffs_come_from_the_database_clock(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    database_clock: DatabaseClock,
):
    await _add_events(sessions, EVENTS_CUTOFF + 60 * SECOND)
    database_clock.source = lambda: NOW
    async with sessions() as session:
        # The application clock runs two minutes ahead (within the allowed difference).
        result = await run_retention(session, NOW + 120 * SECOND, store)

    assert result.deleted_rows == 0
    assert await _event_times(sessions) == [EVENTS_CUTOFF + 60 * SECOND]


@pytest.mark.parametrize("ahead", [timedelta(days=60), timedelta(days=160), -timedelta(hours=1)])
async def test_retention_is_skipped_when_the_clocks_differ(
    ahead: timedelta,
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    database_clock: DatabaseClock,
    caplog: pytest.LogCaptureFixture,
):
    await _add_events(sessions, at(1, 15))
    database_clock.source = lambda: NOW

    with caplog.at_level(logging.INFO, logger="app.events.retention"):
        async with sessions() as session:
            result = await run_retention(session, NOW + ahead, store)

    assert result == RetentionResult(skipped=True)
    assert await _children(sessions, "events") == _events(1, 2, 3, 4, 5, 6)
    assert await _children(sessions, "communication_log") == _log(1, 2, 3, 4, 5, 6)
    seconds = int(abs(ahead).total_seconds())
    assert [r.getMessage() for r in caplog.records] == [
        f"retention skipped: application and database clocks differ by {seconds} s"
    ]


def test_a_partition_is_dropped_only_when_it_ends_before_the_cutoff_and_the_database_now():
    end, cutoff, now = at(4, 1), at(4, 1), at(4, 1)
    assert may_drop(end, cutoff=cutoff, database_now=now)
    assert not may_drop(end, cutoff=cutoff - SECOND, database_now=now)
    # A cut-off after "now" (a period of zero or less) must not drop the current month.
    assert not may_drop(at(5, 1), cutoff=at(6, 1), database_now=at(4, 15))
    assert not may_drop(at(4, 16), cutoff=at(6, 1), database_now=at(4, 15))


def _lock_timeout() -> DBAPIError:
    class OrigError(Exception):
        sqlstate = "55P03"

    return DBAPIError("DROP TABLE x", {}, OrigError())


async def test_job_backs_off_after_a_lock_timeout(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    monkeypatch: pytest.MonkeyPatch,
    database_clock: DatabaseClock,
    caplog: pytest.LogCaptureFixture,
):
    failures = [_lock_timeout() for _ in range(4)]
    real = retention.run_retention

    async def flaky(
        session: AsyncSession, now: datetime, settings: SettingsStore
    ) -> RetentionResult:
        if failures:
            raise failures.pop()
        return await real(session, now, settings)

    monkeypatch.setattr(retention, "run_retention", flaky)
    time = FakeTime(at(6, 20, 23, 0), max_sleeps=5)
    database_clock.source = time.clock
    job = RetentionMaintenance(
        sessions, store, clock=time.clock, sleep=time.sleep, startup_delay_seconds=0
    )

    with caplog.at_level(logging.ERROR, logger="app.events.retention"):
        await job.start()
        for _ in range(500):
            if len(time.sleeps) >= 5:
                break
            await asyncio.sleep(0.01)
        await job.stop()

    # 1, 5 and 15 minutes, then 15 minutes again; after the success the daily schedule.
    assert time.sleeps[:4] == [60.0, 300.0, 900.0, 900.0]
    assert time.sleeps[4] < 3600
    assert [r.getMessage() for r in caplog.records].count(
        "retention failed (DBAPIError, SQLSTATE 55P03)"
    ) == 4


async def test_a_clock_jump_shared_by_host_and_database_keeps_the_newest_rows(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    # Audit run 7, R-H4: both clocks jump to December; the comparison cannot see it.
    await _add_events(sessions, at(5, 3), at(6, 10))
    await _add_log(sessions, at(6, 1))
    jumped = datetime(2045, 12, 20, 12, 0, tzinfo=UTC)

    result = await _run(sessions, store, jumped)

    assert result.dropped_partitions == [*_events(1, 2, 3, 4, 5), *_log(1, 2, 3, 4, 5)]
    assert await _children(sessions, "events") == _events(6)
    assert await _children(sessions, "communication_log") == _log(6)
    assert await _event_times(sessions) == [at(6, 10)]
    assert await _log_times(sessions) == [at(6, 1)]


async def test_an_empty_table_loses_all_its_old_partitions(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    # Nothing to protect: no row anywhere, the partitions before the cut-off go.
    result = await _run(sessions, store)
    assert result.dropped_partitions == [*_events(1, 2), *_log(1, 2, 3, 4)]


async def test_repeated_skipped_runs_are_logged_as_an_error(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    database_clock: DatabaseClock,
    caplog: pytest.LogCaptureFixture,
):
    database_clock.source = lambda: NOW
    job = RetentionMaintenance(sessions, store, clock=lambda: NOW + timedelta(hours=2))

    with caplog.at_level(logging.WARNING, logger="app.events.retention"):
        for _ in range(4):
            assert await job.run_once() is True
        database_clock.source = lambda: NOW + timedelta(hours=2)
        assert await job.run_once() is True  # clocks agree again: the count starts anew
        database_clock.source = lambda: NOW
        assert await job.run_once() is True

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors == [
        "retention skipped 3 runs in a row: the clocks still differ, nothing is pruned",
        "retention skipped 4 runs in a row: the clocks still differ, nothing is pruned",
    ]
