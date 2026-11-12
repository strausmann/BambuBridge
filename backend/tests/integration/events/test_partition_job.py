from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.engine import make_engine
from app.db.session import make_session_factory
from app.events import partitions
from app.events.partitions import PartitionMaintenance, next_daily_run, partition_name
from app.events.service import EventService
from tests.conftest import DEAD_DATABASE_URL


class FakeTime:
    """A clock that only moves when the job sleeps; stops the job after ``max_sleeps``."""

    def __init__(self, start: datetime, max_sleeps: int) -> None:
        self.now = start
        self.sleeps: list[float] = []
        self._max_sleeps = max_sleeps

    def clock(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        if len(self.sleeps) >= self._max_sleeps:
            raise asyncio.CancelledError
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)
        await asyncio.sleep(0)


async def _exists(sessions: async_sessionmaker[AsyncSession], name: str) -> bool:
    async with sessions() as session:
        return await session.scalar(text("SELECT to_regclass(:n)"), {"n": name}) is not None


async def _drop(sessions: async_sessionmaker[AsyncSession], *names: str) -> None:
    async with sessions() as session:
        for name in names:
            await session.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        await session.commit()


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 12, 15, 10, 0, tzinfo=UTC), datetime(2026, 12, 16, 0, 5, tzinfo=UTC)),
        (datetime(2026, 12, 15, 0, 4, 59, tzinfo=UTC), datetime(2026, 12, 15, 0, 5, tzinfo=UTC)),
        (datetime(2026, 12, 15, 0, 5, tzinfo=UTC), datetime(2026, 12, 16, 0, 5, tzinfo=UTC)),
        (datetime(2026, 12, 31, 23, 59, tzinfo=UTC), datetime(2027, 1, 1, 0, 5, tzinfo=UTC)),
    ],
)
def test_next_daily_run_is_the_next_0005_utc(now: datetime, expected: datetime):
    assert next_daily_run(now) == expected


def test_partition_name():
    assert partition_name("events", 2027, 1) == "events_y2027m01"


async def test_job_runs_at_start_and_again_at_0005_utc(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
):
    names = ["events_y2035m01", "events_y2035m02", "events_y2035m03", "events_y2035m04"]
    await _drop(sessions, *names)
    runs: list[datetime] = []
    real = partitions.ensure_partitions

    async def recording(session: AsyncSession, now: datetime, months_ahead: int = 2) -> list[str]:
        runs.append(now)
        return await real(session, now, months_ahead)

    monkeypatch.setattr(partitions, "ensure_partitions", recording)
    # 31 January, 22:30 UTC: the next run at 00:05 is in February and adds April.
    time = FakeTime(datetime(2035, 1, 31, 22, 30, tzinfo=UTC), max_sleeps=3)
    job = PartitionMaintenance(sessions, clock=time.clock, sleep=time.sleep)

    await job.start()
    assert [await _exists(sessions, n) for n in names] == [True, True, True, False]
    for _ in range(500):
        if len(time.sleeps) >= 3:  # the third sleep starts once the second run is through
            break
        await asyncio.sleep(0.01)
    await job.stop()

    assert runs[:2] == [
        datetime(2035, 1, 31, 22, 30, tzinfo=UTC),
        datetime(2035, 2, 1, 0, 5, tzinfo=UTC),
    ]
    # Sleeps are capped at one hour and re-read the clock: 60 min, then the remaining 35.
    assert time.sleeps[:2] == [3600.0, 2100.0]
    assert await _exists(sessions, names[3])
    await _drop(sessions, *names)


async def test_job_logs_a_failure_by_type_and_retries(caplog: pytest.LogCaptureFixture):
    engine = make_engine(DEAD_DATABASE_URL)
    time = FakeTime(datetime(2035, 1, 31, 22, 30, tzinfo=UTC), max_sleeps=2)
    job = PartitionMaintenance(
        make_session_factory(engine), clock=time.clock, sleep=time.sleep, retry_seconds=7.0
    )
    try:
        with caplog.at_level(logging.ERROR, logger="app.events.partitions"):
            await job.start()
            for _ in range(200):
                if len(time.sleeps) >= 2:
                    break
                await asyncio.sleep(0.01)
            await job.stop()
    finally:
        await engine.dispose()

    assert time.sleeps == [7.0, 7.0]
    messages = [r.getMessage() for r in caplog.records]
    assert messages
    assert all(m.startswith("partition maintenance failed (") for m in messages)
    assert not any("127.0.0.1" in m or "://" in m for m in messages)


async def test_job_logs_class_and_sqlstate_of_a_database_error(
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    async def broken(session: AsyncSession, now: datetime, months_ahead: int = 2) -> list[str]:
        await session.execute(text("SELECT * FROM no_such_table_here"))
        return []

    monkeypatch.setattr(partitions, "ensure_partitions", broken)
    job = PartitionMaintenance(sessions)

    with caplog.at_level(logging.ERROR, logger="app.events.partitions"):
        assert await job.run_once() is False

    (message,) = [r.getMessage() for r in caplog.records]
    assert message == "partition maintenance failed (ProgrammingError, SQLSTATE 42P01)"


async def test_job_start_twice_and_stop_twice_are_harmless(
    sessions: async_sessionmaker[AsyncSession],
):
    job = PartitionMaintenance(sessions)
    await job.start()
    task = job._task
    await job.start()
    assert job._task is task
    await job.stop()
    await job.stop()
    assert task is not None and task.cancelled()


async def test_app_ensures_partitions_at_startup_and_has_an_event_service(
    app: FastAPI, sessions: async_sessionmaker[AsyncSession]
):
    now = datetime.now(UTC)
    index = now.year * 12 + now.month - 1
    names = [partition_name("events", *_ym(index + i)) for i in range(3)]
    await _drop(sessions, *names)
    assert isinstance(app.state.event_service, EventService)

    async with app.router.lifespan_context(app):
        assert [await _exists(sessions, n) for n in names] == [True, True, True]
        task = app.state.partition_maintenance._task
        assert task is not None and not task.done()

    assert task.cancelled()
    assert app.state.partition_maintenance is None


def _ym(index: int) -> tuple[int, int]:
    year, month0 = divmod(index, 12)
    return year, month0 + 1
