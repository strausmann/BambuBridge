from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events import partitions
from app.events.partitions import PARTITIONED_TABLES, ensure_partitions
from app.events.service import EventService
from app.models.event import Event
from app.repositories import events as events_repo
from tests.integration.events.conftest import counts, emit


async def _partitions(session: AsyncSession, parent: str = "events") -> set[str]:
    rows = await session.scalars(
        text(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE i.inhparent = to_regclass(:parent)"
        ),
        {"parent": parent},
    )
    return set(rows.all())


def _both(*names: str) -> list[str]:
    """The ``events`` partitions named, followed by those of the communication log."""
    return [*names, *(name.replace("events_", "communication_log_", 1) for name in names)]


async def _drop(session: AsyncSession, *names: str) -> None:
    """Drop the named ``events`` partitions and their communication log counterparts."""
    for name in dict.fromkeys(_both(*names)):
        await session.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    await session.commit()


def test_events_and_the_communication_log_are_partitioned():
    assert PARTITIONED_TABLES == ("events", "communication_log")


async def test_partitions_ensured_ahead(db_session: AsyncSession):
    await ensure_partitions(db_session, datetime(2026, 12, 15, 9, 30, tzinfo=UTC))
    await db_session.commit()

    assert {"events_y2026m12", "events_y2027m01", "events_y2027m02"} <= await _partitions(
        db_session
    )
    assert {
        "communication_log_y2026m12",
        "communication_log_y2027m01",
        "communication_log_y2027m02",
    } <= await _partitions(db_session, "communication_log")


async def test_ensure_partitions_returns_what_it_created_and_is_idempotent(
    db_session: AsyncSession,
):
    names = ["events_y2031m11", "events_y2031m12", "events_y2032m01", "events_y2032m02"]
    await _drop(db_session, *names)
    now = datetime(2031, 11, 30, 23, 59, tzinfo=UTC)

    assert await ensure_partitions(db_session, now) == _both(*names[:3])
    assert await ensure_partitions(db_session, now) == []
    assert await ensure_partitions(db_session, now, months_ahead=3) == _both(*names[3:])
    await db_session.commit()
    assert set(names) <= await _partitions(db_session)

    await _drop(db_session, *names)
    assert await ensure_partitions(db_session, now, months_ahead=0) == _both(*names[:1])
    await db_session.rollback()  # the caller owns the transaction: nothing was committed
    assert not set(names) & await _partitions(db_session)


async def test_ensure_partitions_uses_utc_months(db_session: AsyncSession):
    await _drop(db_session, "events_y2033m12", "events_y2034m01")
    # 00:30 on 1 January at UTC+2 is still 31 December in UTC.
    now = datetime(2034, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))

    created = await ensure_partitions(db_session, now, months_ahead=0)
    await db_session.commit()

    assert created == _both("events_y2033m12")
    await _drop(db_session, "events_y2033m12")


@pytest.mark.parametrize("now", [datetime(2026, 12, 15), "2026-12-15"])
async def test_ensure_partitions_needs_an_aware_datetime(db_session: AsyncSession, now: object):
    with pytest.raises(ValueError, match="timezone-aware"):
        await ensure_partitions(db_session, now)  # type: ignore[arg-type]


async def test_ensure_partitions_rejects_negative_months(db_session: AsyncSession):
    with pytest.raises(ValueError, match="months_ahead"):
        await ensure_partitions(db_session, datetime(2026, 12, 15, tzinfo=UTC), months_ahead=-1)


async def test_insert_across_month_boundary(db_session: AsyncSession):
    await ensure_partitions(db_session, datetime(2026, 12, 15, tzinfo=UTC))
    last = datetime(2026, 12, 31, 23, 59, 59, 999000, tzinfo=UTC)
    first = datetime(2027, 1, 1, 0, 0, 0, tzinfo=UTC)
    for moment in (last, first):
        db_session.add(
            Event(
                id=uuid.uuid4(),
                occurred_at=moment,
                type="integration.demo.tick",
                payload={},
                schema_version=1,
            )
        )
    await db_session.commit()

    rows = (
        await db_session.execute(
            text("SELECT tableoid::regclass::text, occurred_at FROM events ORDER BY occurred_at")
        )
    ).all()
    assert [(r[0], r[1]) for r in rows] == [("events_y2026m12", last), ("events_y2027m01", first)]
    assert len((await db_session.scalars(select(Event))).all()) == 2


async def test_there_is_no_default_partition(db_session: AsyncSession):
    await _drop(db_session, "events_y2099m06")
    db_session.add(
        Event(
            id=uuid.uuid4(),
            occurred_at=datetime(2099, 6, 1, tzinfo=UTC),
            type="integration.demo.tick",
            payload={},
            schema_version=1,
        )
    )
    with pytest.raises(DBAPIError) as exc:
        await db_session.flush()
    assert getattr(exc.value.orig, "sqlstate", None) == "23514"  # no partition for the row


async def test_alembic_check_ignores_the_child_partitions(
    db_session: AsyncSession, alembic_config: Config
):
    await ensure_partitions(db_session, datetime(2026, 12, 15, tzinfo=UTC))
    await db_session.commit()
    assert await _partitions(db_session)

    # Alembic's env runs its own event loop, so it gets a thread of its own.
    await asyncio.to_thread(command.check, alembic_config)


async def test_alembic_check_reports_a_table_that_only_looks_like_a_partition(
    db_session: AsyncSession, alembic_config: Config
):
    # Full-width digits: "\d" without re.ASCII took this for a monthly partition.
    lookalike = "events_y\uff12\uff10\uff12\uff16m\uff11\uff12"
    await db_session.execute(text(f'CREATE TABLE "{lookalike}" (id integer)'))
    await db_session.commit()
    try:
        with pytest.raises(CommandError, match="New upgrade operations detected"):
            await asyncio.to_thread(command.check, alembic_config)
    finally:
        await _drop(db_session, lookalike)


async def test_concurrent_ensure_partitions_create_each_partition_once(
    db_session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
):
    names = ["events_y2036m05", "events_y2036m06", "events_y2036m07"]
    await _drop(db_session, *names)
    now = datetime(2036, 5, 10, tzinfo=UTC)

    async def one() -> list[str]:
        async with sessions() as session:
            created = await ensure_partitions(session, now)
            await asyncio.sleep(0.05)  # keep the transaction open while the other one runs
            await session.commit()
            return created

    results = await asyncio.wait_for(asyncio.gather(one(), one(), one()), timeout=10)

    assert sorted(name for created in results for name in created) == sorted(_both(*names))
    assert set(names) <= await _partitions(db_session)
    await _drop(db_session, *names)


async def test_ensure_partitions_does_not_wait_for_the_bootstrap_lock(
    db_session: AsyncSession, session2: AsyncSession
):
    await _drop(db_session, "events_y2037m01")
    # The single-key advisory lock that serialises the first admin token (api_keys repository).
    await db_session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 0x6262_0002})

    created = await asyncio.wait_for(
        ensure_partitions(session2, datetime(2037, 1, 5, tzinfo=UTC), months_ahead=0), timeout=3
    )

    assert created == _both("events_y2037m01")
    await session2.rollback()
    await db_session.rollback()


async def test_ensure_partitions_gives_up_when_the_table_is_in_use(
    service: EventService,
    db_session: AsyncSession,
    session2: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
):
    await _drop(db_session, "events_y2038m01")
    monkeypatch.setattr(partitions, "DDL_LOCK_TIMEOUT_SECONDS", 0.5)
    # A reader keeps its transaction open: the partition DDL needs the table exclusively.
    await db_session.execute(text("SELECT count(*) FROM events"))

    async def emit_committed() -> None:
        async with sessions() as session:
            await emit(service, session)
            await session.commit()

    ddl = asyncio.create_task(
        ensure_partitions(session2, datetime(2038, 1, 5, tzinfo=UTC), months_ahead=0)
    )
    await asyncio.sleep(0.1)
    writer = asyncio.create_task(emit_committed())  # queues behind the waiting DDL

    try:
        with pytest.raises(DBAPIError) as exc:
            await asyncio.wait_for(ddl, timeout=3)
        assert getattr(exc.value.orig, "sqlstate", None) == "55P03"  # lock_not_available
        await asyncio.wait_for(writer, timeout=3)
    finally:
        for task in (ddl, writer):
            task.cancel()
        await session2.rollback()
        await db_session.rollback()

    assert await counts(sessions) == (1, 1)
    assert "events_y2038m01" not in await _partitions(db_session)


async def test_ensure_partitions_leaves_the_callers_lock_timeout_alone(db_session: AsyncSession):
    await _drop(db_session, "events_y2039m01")
    before = (await db_session.execute(text("SHOW lock_timeout"))).scalar_one()

    assert await ensure_partitions(
        db_session, datetime(2039, 1, 5, tzinfo=UTC), months_ahead=0
    ) == _both("events_y2039m01")

    assert (await db_session.execute(text("SHOW lock_timeout"))).scalar_one() == before
    await db_session.rollback()


@pytest.mark.parametrize(
    "squatter",
    [
        'CREATE TABLE "events_y2041m02" (id integer)',
        'CREATE VIEW "events_y2041m02" AS SELECT 1 AS id',
        'CREATE SEQUENCE "events_y2041m02"',
        # A partition, but of another table.
        'CREATE TABLE "events_y2041m02" PARTITION OF other_parent '
        "FOR VALUES FROM ('2041-02-01 00:00:00+00') TO ('2041-03-01 00:00:00+00')",
    ],
    ids=["table", "view", "sequence", "foreign-partition"],
)
async def test_ensure_partitions_reports_a_foreign_object_under_a_partition_name(
    squatter: str, db_session: AsyncSession, caplog: pytest.LogCaptureFixture
):
    names = ["events_y2041m01", "events_y2041m02", "events_y2041m03"]

    async def cleanup() -> None:
        await db_session.rollback()
        kind = await db_session.scalar(
            text("SELECT relkind::text FROM pg_class WHERE oid = to_regclass('events_y2041m02')")
        )
        what = {"v": "VIEW", "S": "SEQUENCE"}.get(kind or "", "TABLE")
        await db_session.execute(text(f'DROP {what} IF EXISTS "events_y2041m02"'))
        await db_session.execute(text("DROP TABLE IF EXISTS other_parent"))
        await db_session.commit()
        await _drop(db_session, *names)

    await cleanup()
    try:
        await db_session.execute(
            text(
                "CREATE TABLE other_parent (occurred_at timestamptz NOT NULL) "
                "PARTITION BY RANGE (occurred_at)"
            )
        )
        await db_session.execute(text(squatter))
        await db_session.commit()

        with caplog.at_level(logging.ERROR, logger="app.events.partitions"):
            created = await ensure_partitions(db_session, datetime(2041, 1, 10, tzinfo=UTC))
            await db_session.commit()

        # The months around it are served; the taken name is reported, not silently accepted.
        # The communication log has all three: the taken name is not one of its partitions.
        assert created == [
            "events_y2041m01",
            "events_y2041m03",
            *_both("events_y2041m01", "events_y2041m02", "events_y2041m03")[3:],
        ]
        assert await _partitions(db_session) >= {"events_y2041m01", "events_y2041m03"}
        assert "events_y2041m02" not in await _partitions(db_session)
        messages = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert messages == [
            "cannot create partition events_y2041m02: the name belongs to another object"
        ]
    finally:
        await cleanup()


async def test_ensure_partitions_gives_up_when_another_run_holds_the_partition_lock(
    db_session: AsyncSession, session2: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(partitions, "DDL_LOCK_TIMEOUT_SECONDS", 0.4)
    await db_session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, 1)"),
        {"namespace": events_repo.EVENTS_LOCK_NAMESPACE},
    )

    try:
        with pytest.raises(DBAPIError) as exc:
            await asyncio.wait_for(
                ensure_partitions(session2, datetime.now(UTC), months_ahead=0), timeout=5
            )
    except TimeoutError:
        pytest.fail("ensure_partitions waited for the partition lock without a bound")
    finally:
        await session2.rollback()
        await db_session.rollback()
    assert getattr(exc.value.orig, "sqlstate", None) == "55P03"  # lock_not_available


async def test_ensure_partitions_restores_the_lock_timeout_when_nothing_is_missing(
    db_session: AsyncSession,
):
    await db_session.execute(text("SET LOCAL lock_timeout = '1234ms'"))
    assert await ensure_partitions(db_session, datetime.now(UTC)) == []
    assert (await db_session.execute(text("SHOW lock_timeout"))).scalar_one() == "1234ms"


async def test_set_local_lock_timeout_returns_the_value_it_replaced(db_session: AsyncSession):
    await db_session.execute(text("SET LOCAL lock_timeout = '1234ms'"))
    assert await events_repo.set_local_lock_timeout(db_session, "250ms") == "1234ms"
    assert await events_repo.set_local_lock_timeout(db_session, "1234ms") == "250ms"
    assert (await db_session.execute(text("SHOW lock_timeout"))).scalar_one() == "1234ms"
    await db_session.rollback()
    # SET LOCAL: gone with the transaction.
    assert (await db_session.execute(text("SHOW lock_timeout"))).scalar_one() == "0"
