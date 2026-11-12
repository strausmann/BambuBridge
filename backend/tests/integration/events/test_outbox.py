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

    held = await outbox.claim(
        db_session, "sse", "a", limit=1
    )  # worker A keeps its transaction open
    assert len(held) == 1

    try:
        others = await asyncio.wait_for(outbox.claim(session2, "sse", "b"), timeout=1.0)
    except TimeoutError:
        pytest.fail("claim waited for a delivery that another worker holds locked")

    assert others, "worker B must get the deliveries that are not locked"
    assert {d.id for d in others}.isdisjoint({d.id for d in held})
    assert [d.event.payload["n"] for d in held] == [0]
    assert [d.event.payload["n"] for d in others] == [1, 2]

    # Neither worker committed its claim: no lease was stored, all three are free again.
    await db_session.rollback()
    await session2.rollback()
    assert len(await outbox.claim(session2, "sse", "b")) == 3


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

    claimed = await outbox.claim(db_session, "sse", "a", limit=3)

    assert [d.id for d in claimed] == [first[0].id, first[1].id, first[2].id]
    assert all(d.subscriber == "sse" and d.attempts == 0 for d in claimed)
    assert [d.event_id for d in claimed] == [r.event_id for r in first[:3]]


async def test_claim_default_limit_is_100(service: EventService, db_session: AsyncSession):
    for n in range(101):
        await emit(service, db_session, n=n)
    await db_session.commit()
    assert len(await outbox.claim(db_session, "sse", "a")) == 100


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

    assert [d.id for d in await outbox.claim(db_session, "sse", "a")] == [rows[3].id]
    assert len(await outbox.claim(db_session, "rules", "a")) == 4
    assert await outbox.claim(db_session, "nobody", "a") == []


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

    claimed = await outbox.claim(db_session, "sse", "a")

    assert [d.event.payload["n"] if d.event else None for d in claimed] == [1, None]
    assert claimed[0].event.type == "integration.demo.tick"
    assert claimed[1].event_id == gone.id


async def test_complete_marks_done_and_is_not_claimed_again(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 3)
    claimed = await outbox.claim(db_session, "sse", "a")

    await outbox.complete(db_session, "a", [claimed[0].id, claimed[2].id])
    await outbox.complete(db_session, "a", [])
    await db_session.commit()

    assert (await _row(db_session, claimed[0].id)).status == "done"
    assert (await _row(db_session, claimed[2].id)).status == "done"
    done = await _row(db_session, claimed[0].id)
    assert (done.claimed_by, done.claimed_until) == (None, None)
    # The third one is still leased to the worker; once the lease is over it comes back,
    # the two done ones never do.
    assert await outbox.claim(db_session, "sse", "b") == []
    await _expire_leases(db_session)
    assert [d.id for d in await outbox.claim(db_session, "sse", "b")] == [claimed[1].id]


async def _make_due(session: AsyncSession) -> None:
    await session.execute(
        update(EventDelivery).values(available_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()


async def _expire_leases(session: AsyncSession) -> None:
    await session.execute(
        update(EventDelivery)
        .where(EventDelivery.claimed_until.is_not(None))
        .values(claimed_until=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()


async def test_fail_backs_off_and_stops_after_10(service: EventService, db_session: AsyncSession):
    await _emit_committed(service, db_session, 1)

    async def db_clock() -> datetime:
        return (await db_session.execute(text("SELECT clock_timestamp()"))).scalar_one()

    delivery_id = 0
    for attempt in range(1, 10):
        (delivery,) = await outbox.claim(db_session, "sse", "a")
        await db_session.commit()
        delivery_id = delivery.id
        assert delivery.attempts == attempt - 1
        earliest = await db_clock()
        assert await outbox.fail(db_session, "a", delivery.id, f"boom {attempt}") is True
        latest = await db_clock()
        await db_session.commit()
        row = await _row(db_session, delivery.id)
        assert (row.status, row.attempts, row.last_error) == ("pending", attempt, f"boom {attempt}")
        # The failure ends the lease, so the wait below is the only thing that holds it back.
        assert (row.claimed_by, row.claimed_until) == (None, None)
        # Retry after 2^attempts seconds, counted from the moment of the failure.
        wait = timedelta(seconds=2**attempt)
        assert earliest + wait <= row.available_at <= latest + wait
        assert await outbox.claim(db_session, "sse", "a") == []
        await _make_due(db_session)

    (delivery,) = await outbox.claim(db_session, "sse", "a")
    await db_session.commit()
    before = (await _row(db_session, delivery_id)).available_at
    assert await outbox.fail(db_session, "a", delivery_id, "boom 10") is True
    await db_session.commit()
    row = await _row(db_session, delivery_id)
    assert (row.status, row.attempts, row.last_error) == ("failed", 10, "boom 10")
    assert (row.claimed_by, row.claimed_until) == (None, None)
    assert row.available_at == before

    # A failed delivery is final: no further attempt is counted and it is never claimed.
    assert await outbox.fail(db_session, "a", delivery_id, "boom 11") is False
    await _make_due(db_session)
    row = await _row(db_session, delivery_id)
    assert (row.status, row.attempts, row.last_error) == ("failed", 10, "boom 10")
    assert await outbox.claim(db_session, "sse", "a") == []


async def test_failed_delivery_is_claimable_again_once_due(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse", "a")
    await outbox.fail(db_session, "a", delivery.id, "boom")
    await _make_due(db_session)

    # Any worker may take it; the failure was counted once, the ended lease is not counted.
    (again,) = await outbox.claim(db_session, "sse", "b")
    assert (again.id, again.attempts) == (delivery.id, 1)


async def test_fail_stores_at_most_2000_characters_of_the_error(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse", "a")
    await outbox.fail(db_session, "a", delivery.id, "e" * 5000)
    await db_session.commit()
    assert (await _row(db_session, delivery.id)).last_error == "e" * 2000


async def test_fail_strips_nul_bytes_from_the_error(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse", "a")
    await outbox.fail(db_session, "a", delivery.id, "bo\x00om\x00")
    await db_session.commit()
    row = await _row(db_session, delivery.id)
    assert (row.last_error, row.attempts) == ("boom", 1)


async def test_fail_replaces_lone_surrogates_in_the_error(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse", "a")
    assert await outbox.fail(db_session, "a", delivery.id, "bad \ud800 name \udfff\x00") is True
    await db_session.commit()
    row = await _row(db_session, delivery.id)
    assert (row.last_error, row.attempts) == ("bad \ufffd name \ufffd", 1)
