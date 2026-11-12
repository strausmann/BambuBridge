from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.partitions import PARTITIONED_TABLES, ensure_partitions
from app.models.event import Event


async def _partitions(session: AsyncSession, parent: str = "events") -> set[str]:
    rows = await session.scalars(
        text(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE i.inhparent = to_regclass(:parent)"
        ),
        {"parent": parent},
    )
    return set(rows.all())


async def _drop(session: AsyncSession, *names: str) -> None:
    for name in names:
        await session.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    await session.commit()


def test_only_events_is_partitioned_for_now():
    assert PARTITIONED_TABLES == ("events",)


async def test_partitions_ensured_ahead(db_session: AsyncSession):
    await ensure_partitions(db_session, datetime(2026, 12, 15, 9, 30, tzinfo=UTC))
    await db_session.commit()

    assert {"events_y2026m12", "events_y2027m01", "events_y2027m02"} <= await _partitions(
        db_session
    )


async def test_ensure_partitions_returns_what_it_created_and_is_idempotent(
    db_session: AsyncSession,
):
    names = ["events_y2031m11", "events_y2031m12", "events_y2032m01", "events_y2032m02"]
    await _drop(db_session, *names)
    now = datetime(2031, 11, 30, 23, 59, tzinfo=UTC)

    assert await ensure_partitions(db_session, now) == names[:3]
    assert await ensure_partitions(db_session, now) == []
    assert await ensure_partitions(db_session, now, months_ahead=3) == names[3:]
    await db_session.commit()
    assert set(names) <= await _partitions(db_session)

    await _drop(db_session, *names)
    assert await ensure_partitions(db_session, now, months_ahead=0) == names[:1]
    await db_session.rollback()  # the caller owns the transaction: nothing was committed
    assert not set(names) & await _partitions(db_session)


async def test_ensure_partitions_uses_utc_months(db_session: AsyncSession):
    await _drop(db_session, "events_y2033m12", "events_y2034m01")
    # 00:30 on 1 January at UTC+2 is still 31 December in UTC.
    now = datetime(2034, 1, 1, 0, 30, tzinfo=timezone(timedelta(hours=2)))

    created = await ensure_partitions(db_session, now, months_ahead=0)
    await db_session.commit()

    assert created == ["events_y2033m12"]
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
