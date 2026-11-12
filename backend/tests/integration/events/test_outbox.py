from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import outbox
from app.events import service as service_module
from app.events.service import EventService
from app.models.event import Event
from app.models.event_delivery import EventDelivery
from tests.integration.events.conftest import SOURCE_A, SOURCE_B, emit


async def _emit_committed(service: EventService, session: AsyncSession, count: int) -> None:
    for n in range(count):
        await emit(service, session, n=n)
        await session.commit()


async def _row(session: AsyncSession, delivery_id: int) -> EventDelivery:
    return (
        await session.scalars(
            select(EventDelivery)
            .where(EventDelivery.id == delivery_id)
            .execution_options(populate_existing=True)
        )
    ).one()


async def test_claim_skip_locked_two_workers_disjoint(
    service: EventService, db_session: AsyncSession, session2: AsyncSession
):
    await _emit_committed(service, db_session, 3)

    held = await outbox.claim(db_session, "sse", limit=1)  # worker A keeps its transaction open
    assert len(held) == 1

    try:
        others = await asyncio.wait_for(outbox.claim(session2, "sse"), timeout=1.0)
    except TimeoutError:
        pytest.fail("claim waited for a delivery that another worker holds locked")

    assert others, "worker B must get the deliveries that are not locked"
    assert {d.id for d in others}.isdisjoint({d.id for d in held})
    assert [d.event.payload["n"] for d in held] == [0]
    assert [d.event.payload["n"] for d in others] == [1, 2]

    # A's lock ends with its transaction; an uncompleted delivery is then claimable again.
    await db_session.rollback()
    await session2.rollback()
    assert len(await outbox.claim(session2, "sse")) == 3


async def test_claim_orders_by_event_time_then_id_and_honours_limit(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 5)
    # Give two deliveries the same event time: the id decides.
    first = (await db_session.scalars(select(EventDelivery).order_by(EventDelivery.id))).all()
    await db_session.execute(
        update(EventDelivery)
        .where(EventDelivery.id == first[1].id)
        .values(event_occurred_at=first[0].event_occurred_at)
    )
    await db_session.commit()

    claimed = await outbox.claim(db_session, "sse", limit=3)

    assert [d.id for d in claimed] == [first[0].id, first[1].id, first[2].id]
    assert all(d.subscriber == "sse" and d.attempts == 0 for d in claimed)
    assert [d.event_id for d in claimed] == [r.event_id for r in first[:3]]


async def test_claim_default_limit_is_100(service: EventService, db_session: AsyncSession):
    for n in range(101):
        await emit(service, db_session, n=n)
    await db_session.commit()
    assert len(await outbox.claim(db_session, "sse")) == 100


async def test_claim_returns_only_due_pending_deliveries_of_the_subscriber(
    service: EventService, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(service_module, "_SUBSCRIBERS", ["sse", "rules"])
    await _emit_committed(service, db_session, 4)
    rows = (
        await db_session.scalars(
            select(EventDelivery)
            .where(EventDelivery.subscriber == "sse")
            .order_by(EventDelivery.id)
        )
    ).all()
    later = datetime.now(UTC) + timedelta(hours=1)
    for row, values in (
        (rows[0], {"status": "done"}),
        (rows[1], {"status": "failed"}),
        (rows[2], {"available_at": later}),
    ):
        await db_session.execute(
            update(EventDelivery).where(EventDelivery.id == row.id).values(**values)
        )
    await db_session.commit()

    assert [d.id for d in await outbox.claim(db_session, "sse")] == [rows[3].id]
    assert len(await outbox.claim(db_session, "rules")) == 4
    assert await outbox.claim(db_session, "nobody") == []


async def test_claim_carries_the_event_and_survives_a_missing_one(
    service: EventService, db_session: AsyncSession
):
    await emit(service, db_session, source=SOURCE_A, n=1)
    await emit(service, db_session, source=SOURCE_B, n=2)
    await db_session.commit()
    gone = (
        await db_session.scalars(select(Event).where(Event.source_instance_id == SOURCE_B))
    ).one()
    await db_session.execute(text("DELETE FROM events WHERE id = :id"), {"id": gone.id})
    await db_session.commit()

    claimed = await outbox.claim(db_session, "sse")

    assert [d.event.payload["n"] if d.event else None for d in claimed] == [1, None]
    assert claimed[0].event.type == "integration.demo.tick"
    assert claimed[1].event_id == gone.id


async def test_complete_marks_done_and_is_not_claimed_again(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 3)
    claimed = await outbox.claim(db_session, "sse")

    await outbox.complete(db_session, [claimed[0].id, claimed[2].id])
    await outbox.complete(db_session, [])
    await db_session.commit()

    assert (await _row(db_session, claimed[0].id)).status == "done"
    assert (await _row(db_session, claimed[2].id)).status == "done"
    assert [d.id for d in await outbox.claim(db_session, "sse")] == [claimed[1].id]


async def test_fail_backs_off_and_stops_after_10(service: EventService, db_session: AsyncSession):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse")
    await db_session.commit()

    for attempt in range(1, 10):
        await outbox.fail(db_session, delivery.id, f"boom {attempt}")
        await db_session.commit()
        row = await _row(db_session, delivery.id)
        now = (await db_session.execute(text("SELECT clock_timestamp()"))).scalar_one()
        wait = (row.available_at - now).total_seconds()
        assert (row.status, row.attempts, row.last_error) == ("pending", attempt, f"boom {attempt}")
        # Retry after 2^attempts seconds.
        assert 2**attempt - 1.5 < wait <= 2**attempt
        assert await outbox.claim(db_session, "sse") == []
        await db_session.commit()

    before = (await _row(db_session, delivery.id)).available_at
    await outbox.fail(db_session, delivery.id, "boom 10")
    await db_session.commit()
    row = await _row(db_session, delivery.id)
    assert (row.status, row.attempts, row.last_error) == ("failed", 10, "boom 10")
    assert row.available_at == before

    # A failed delivery is final: no further attempt is counted and it is never claimed.
    await outbox.fail(db_session, delivery.id, "boom 11")
    await db_session.execute(
        update(EventDelivery).values(available_at=datetime.now(UTC) - timedelta(days=1))
    )
    await db_session.commit()
    row = await _row(db_session, delivery.id)
    assert (row.status, row.attempts, row.last_error) == ("failed", 10, "boom 10")
    assert await outbox.claim(db_session, "sse") == []


async def test_failed_delivery_is_claimable_again_once_due(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse")
    await outbox.fail(db_session, delivery.id, "boom")
    await db_session.execute(
        update(EventDelivery).values(available_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    (again,) = await outbox.claim(db_session, "sse")
    assert (again.id, again.attempts) == (delivery.id, 1)


async def test_fail_stores_at_most_2000_characters_of_the_error(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse")
    await outbox.fail(db_session, delivery.id, "e" * 5000)
    await db_session.commit()
    assert (await _row(db_session, delivery.id)).last_error == "e" * 2000
