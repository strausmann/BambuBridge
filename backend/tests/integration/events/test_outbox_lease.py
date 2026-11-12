"""The lease of a claimed delivery: who owns it, for how long, and what a dead worker costs."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events import outbox
from app.events.service import EventService
from app.models.event_delivery import EventDelivery
from app.repositories import events as events_repo
from tests.integration.events.conftest import emit


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


async def _expire_leases(session: AsyncSession) -> None:
    await session.execute(
        update(EventDelivery)
        .where(EventDelivery.claimed_until.is_not(None))
        .values(claimed_until=datetime.now(UTC) - timedelta(seconds=1))
    )
    await session.commit()


async def _db_clock(session: AsyncSession) -> datetime:
    return (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()


async def test_a_committed_claim_is_not_handed_out_again(
    service: EventService, db_session: AsyncSession, session2: AsyncSession
):
    await _emit_committed(service, db_session, 3)

    earliest = await _db_clock(db_session)
    first = await outbox.claim(db_session, "sse", "worker-a")
    latest = await _db_clock(db_session)
    await db_session.commit()  # claim, commit, then process: the lease keeps the batch

    assert len(first) == 3
    assert await outbox.claim(session2, "sse", "worker-b") == []
    assert await outbox.claim(db_session, "sse", "worker-a") == []
    lease = timedelta(seconds=outbox.LEASE_SECONDS)
    for delivery in first:
        row = await _row(db_session, delivery.id)
        assert (row.status, row.attempts, row.claimed_by) == ("pending", 0, "worker-a")
        assert earliest + lease <= row.claimed_until <= latest + lease


def test_the_lease_lasts_five_minutes():
    assert outbox.LEASE_SECONDS == 300


async def test_an_expired_lease_is_taken_over_and_counts_one_attempt(
    service: EventService, db_session: AsyncSession, session2: AsyncSession
):
    await _emit_committed(service, db_session, 2)
    first = await outbox.claim(db_session, "sse", "worker-a", limit=1)
    await db_session.commit()  # worker-a dies here: no complete, no fail
    await _expire_leases(db_session)

    taken = await outbox.claim(session2, "sse", "worker-b")
    await session2.commit()

    # The delivery of the dead worker comes first again, now with one attempt on record.
    assert [(d.id, d.attempts) for d in taken] == [(first[0].id, 1), (first[0].id + 1, 0)]
    row = await _row(db_session, first[0].id)
    assert (row.status, row.attempts, row.claimed_by) == ("pending", 1, "worker-b")
    assert row.last_error == "lease expired"
    assert row.claimed_until > await _db_clock(db_session)
    untouched = await _row(db_session, first[0].id + 1)
    assert (untouched.attempts, untouched.last_error) == (0, None)


async def test_a_delivery_that_kills_its_workers_fails_after_ten_leases(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 2)
    poison = (await outbox.claim(db_session, "sse", "w0", limit=1))[0]
    await db_session.commit()

    for attempt in range(1, outbox.MAX_ATTEMPTS):
        await _expire_leases(db_session)
        (again,) = await outbox.claim(db_session, "sse", f"w{attempt}", limit=1)
        await db_session.commit()
        assert (again.id, again.attempts) == (poison.id, attempt)

    await _expire_leases(db_session)
    rest = await outbox.claim(db_session, "sse", "w10")
    await db_session.commit()

    # The tenth lost lease ends it; the delivery behind it is finally served.
    assert [d.id for d in rest] == [poison.id + 1]
    row = await _row(db_session, poison.id)
    assert (row.status, row.attempts, row.last_error) == ("failed", 10, "lease expired")
    assert (row.claimed_by, row.claimed_until) == (None, None)


async def test_an_uncommitted_claim_leaves_no_trace(
    service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    for _ in range(3):
        (delivery,) = await outbox.claim(db_session, "sse", "worker-a")
        await db_session.rollback()
    row = await _row(db_session, delivery.id)
    assert (row.attempts, row.claimed_by, row.claimed_until) == (0, None, None)


async def test_complete_and_fail_need_the_lease(
    service: EventService, db_session: AsyncSession, session2: AsyncSession
):
    await _emit_committed(service, db_session, 3)
    one, two, three = await outbox.claim(db_session, "sse", "worker-a")
    await db_session.commit()

    # Another worker, and a delivery nobody claimed, are refused.
    assert await outbox.complete(session2, "worker-b", [one.id, two.id]) == 0
    assert await outbox.fail(session2, "worker-b", three.id, "not mine") is False
    await session2.commit()
    for delivery in (one, two, three):
        row = await _row(db_session, delivery.id)
        assert (row.status, row.attempts, row.claimed_by) == ("pending", 0, "worker-a")

    # The holder itself: only its own, only once.
    assert await outbox.complete(db_session, "worker-a", [one.id, two.id, 999_999]) == 2
    assert await outbox.complete(db_session, "worker-a", [one.id]) == 0
    assert await outbox.fail(db_session, "worker-a", one.id, "already done") is False
    assert await outbox.fail(db_session, "worker-a", three.id, "boom") is True
    assert await outbox.fail(db_session, "worker-a", three.id, "boom again") is False
    assert await outbox.complete(db_session, "worker-a", [three.id]) == 0
    await db_session.commit()
    assert (await _row(db_session, one.id)).status == "done"
    row = await _row(db_session, three.id)
    assert (row.status, row.attempts, row.last_error) == ("pending", 1, "boom")


async def test_the_holder_may_finish_after_its_lease_ran_out_until_someone_takes_over(
    service: EventService, db_session: AsyncSession, session2: AsyncSession
):
    await _emit_committed(service, db_session, 2)
    slow, lost = await outbox.claim(db_session, "sse", "worker-a")
    await db_session.commit()
    await _expire_leases(db_session)

    # Late, but nobody took it over: the work was done once, so it counts.
    assert await outbox.complete(db_session, "worker-a", [slow.id]) == 1
    await db_session.commit()

    (taken,) = await outbox.claim(session2, "sse", "worker-b")
    await session2.commit()
    assert (taken.id, taken.attempts) == (lost.id, 1)
    # Now the delivery belongs to worker-b; the late result of worker-a is dropped.
    assert await outbox.complete(db_session, "worker-a", [lost.id]) == 0
    assert await outbox.fail(db_session, "worker-a", lost.id, "late") is False
    await db_session.commit()
    row = await _row(db_session, lost.id)
    assert (row.status, row.attempts, row.claimed_by) == ("pending", 1, "worker-b")


async def test_a_stale_complete_does_not_override_the_fail_of_the_new_holder(
    service: EventService, db_session: AsyncSession, session2: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse", "worker-a")
    await db_session.commit()
    await _expire_leases(db_session)

    # worker-b takes over and keeps its transaction open: it holds the row.
    (taken,) = await outbox.claim(session2, "sse", "worker-b")
    assert taken.id == delivery.id
    stale = asyncio.create_task(outbox.complete(db_session, "worker-a", [delivery.id]))
    await asyncio.sleep(0.3)
    assert not stale.done(), "the stale complete has to wait for the row worker-b holds"

    assert await outbox.fail(session2, "worker-b", delivery.id, "spoolman 500") is True
    await session2.commit()

    assert await asyncio.wait_for(stale, timeout=5) == 0
    await db_session.commit()
    row = await _row(db_session, delivery.id)
    assert (row.status, row.attempts, row.last_error) == ("pending", 2, "spoolman 500")
    assert (row.claimed_by, row.claimed_until) == (None, None)


async def test_two_workers_racing_for_an_expired_lease_get_it_once(
    service: EventService, db_session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
):
    await _emit_committed(service, db_session, 20)
    assert len(await outbox.claim(db_session, "sse", "dead")) == 20
    await db_session.commit()
    await _expire_leases(db_session)

    async def worker(name: str) -> list[outbox.Delivery]:
        got: list[outbox.Delivery] = []
        async with sessions() as session:
            for _ in range(10):
                got += await outbox.claim(session, "sse", name, limit=3)
                await asyncio.sleep(0.01)  # both transactions stay open side by side
                await session.commit()
        return got

    a, b = await asyncio.wait_for(asyncio.gather(worker("worker-a"), worker("worker-b")), 20)

    ids = [d.id for d in a + b]
    assert len(ids) == len(set(ids)) == 20
    # Every delivery was taken over exactly once: one attempt each, one holder each.
    rows = (await db_session.scalars(select(EventDelivery))).all()
    assert {r.attempts for r in rows} == {1}
    assert {r.id for r in rows if r.claimed_by == "worker-a"} == {d.id for d in a}
    assert {r.id for r in rows if r.claimed_by == "worker-b"} == {d.id for d in b}


@pytest.mark.parametrize("limit", [0, -1, 1001, 8000, None, True, 1.0, "5"])
async def test_claim_takes_a_limit_from_1_to_1000(
    limit: object, service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    await db_session.execute(text("SELECT 1"))
    with pytest.raises(ValueError, match="limit"):
        await outbox.claim(db_session, "sse", "worker-a", limit=limit)  # type: ignore[arg-type]
    # Refused before anything was sent: the transaction is intact.
    assert len(await outbox.claim(db_session, "sse", "worker-a", limit=1)) == 1


@pytest.mark.parametrize("worker", ["", "a\x00b", "a\ud800", "w" * 201, None, 5])
async def test_claim_complete_and_fail_refuse_a_bad_worker_id(
    worker: object, service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    await db_session.execute(text("SELECT 1"))
    with pytest.raises(ValueError, match="worker"):
        await outbox.claim(db_session, "sse", worker)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="worker"):
        await outbox.complete(db_session, worker, [1])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="worker"):
        await outbox.fail(db_session, worker, 1, "x")  # type: ignore[arg-type]
    assert len(await outbox.claim(db_session, "sse", "w" * 200)) == 1


@pytest.mark.parametrize("subscriber", ["", "s\x00e", "SSE", "a b", None])
async def test_claim_refuses_a_subscriber_name_outside_the_scheme(
    subscriber: object, db_session: AsyncSession
):
    await db_session.execute(text("SELECT 1"))
    with pytest.raises(ValueError, match="subscriber"):
        await outbox.claim(db_session, subscriber, "worker-a")  # type: ignore[arg-type]
    assert await outbox.claim(db_session, "sse", "worker-a") == []


_BACKLOG = text(
    """
    WITH new_events AS (
        INSERT INTO events (type, source_instance_id, payload, schema_version)
        SELECT 'integration.demo.tick', NULL, jsonb_build_object('n', g), 1
        FROM generate_series(1, :count) AS g
        RETURNING id, occurred_at
    )
    INSERT INTO event_deliveries (event_id, event_occurred_at, subscriber, status, available_at)
    SELECT id, occurred_at, 'sse', CAST(:status AS text), occurred_at FROM new_events
    """
)


async def test_claim_takes_a_full_batch_of_1000(db_session: AsyncSession):
    await db_session.execute(_BACKLOG, {"count": 1005, "status": "pending"})
    await db_session.commit()

    claimed = await outbox.claim(db_session, "sse", "worker-a", limit=outbox.MAX_CLAIM_LIMIT)

    assert outbox.MAX_CLAIM_LIMIT == 1000
    assert len(claimed) == 1000
    assert all(d.event is not None and d.event.id == d.event_id for d in claimed)
    order = [(d.event_occurred_at, d.id) for d in claimed]
    assert order == sorted(order)


async def test_load_events_takes_any_number_of_keys(db_session: AsyncSession):
    await db_session.execute(_BACKLOG, {"count": 3, "status": "pending"})
    await db_session.commit()
    rows = (await db_session.scalars(select(EventDelivery).order_by(EventDelivery.id))).all()
    real = [(r.event_id, r.event_occurred_at) for r in rows]
    # 10 000 pairs sent the old row-value IN list over the stack depth limit (SQLSTATE 54001).
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    absent = [(real[0][0], stamp + timedelta(seconds=n)) for n in range(10_000)]

    events = await events_repo.load_events(db_session, [*absent, *real])

    assert set(events) == set(real)
    assert all(events[key].id == key[0] and events[key].occurred_at == key[1] for key in real)


def _nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = [node]
    for child in node.get("Plans", []):
        found += _nodes(child)
    return found


async def test_claim_reads_a_large_backlog_in_order_from_the_index(db_session: AsyncSession):
    # What the table looks like after a while: many done deliveries, a pending backlog.
    await db_session.execute(_BACKLOG, {"count": 20_000, "status": "done"})
    await db_session.execute(_BACKLOG, {"count": 20_000, "status": "pending"})
    await db_session.commit()
    await db_session.execute(text("ANALYZE event_deliveries"))
    statement = outbox.CLAIM_STATEMENT.bindparams(
        subscriber="sse",
        worker="worker-a",
        limit=100,
        max_attempts=outbox.MAX_ATTEMPTS,
        lease=float(outbox.LEASE_SECONDS),
    ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})

    raw = (await db_session.execute(text(f"EXPLAIN (FORMAT JSON) {statement}"))).scalar_one()
    nodes = _nodes((json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"])

    # The batch comes ready-ordered from the index: no scan and sort of the whole backlog.
    (limit,) = [n for n in nodes if n["Node Type"] == "Limit"]
    below = _nodes(limit)
    assert "ix_event_deliveries_claim" in {n.get("Index Name") for n in below}, below
    assert not {"Sort", "Seq Scan", "Bitmap Heap Scan"} & {n["Node Type"] for n in below}, below


@pytest.mark.parametrize(
    "ids",
    [["1"], [True], [1.0], [None], [0], [-1], [2**63], "12", [1] * 1001],
    ids=["str", "bool", "float", "none", "zero", "negative", "too-big", "text", "too-many"],
)
async def test_complete_takes_up_to_1000_delivery_ids(
    ids: object, service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse", "worker-a")
    with pytest.raises(ValueError, match="ids"):
        await outbox.complete(db_session, "worker-a", ids)  # type: ignore[arg-type]
    # Refused before anything was sent: the transaction and the lease are intact.
    assert await outbox.complete(db_session, "worker-a", [delivery.id]) == 1


@pytest.mark.parametrize("bad", ["1", True, 1.0, None, 0, -1, 2**63])
async def test_fail_takes_one_delivery_id(
    bad: object, service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse", "worker-a")
    with pytest.raises(ValueError, match="id"):
        await outbox.fail(db_session, "worker-a", bad, "boom")  # type: ignore[arg-type]
    assert await outbox.fail(db_session, "worker-a", delivery.id, "boom") is True


async def test_complete_sends_the_ids_as_one_array(db_session: AsyncSession):
    await db_session.execute(_BACKLOG, {"count": 1000, "status": "pending"})
    await db_session.commit()
    claimed = await outbox.claim(db_session, "sse", "worker-a", limit=1000)
    await db_session.commit()
    seen: list[Any] = []

    def record(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:
        if statement.lstrip().upper().startswith("UPDATE"):
            seen.append(parameters)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        done = await outbox.complete(db_session, "worker-a", [d.id for d in claimed])
    finally:
        event.remove(engine, "before_cursor_execute", record)
    await db_session.commit()

    assert done == 1000
    # One array parameter, however long the list: the statement does not grow with it.
    (parameters,) = seen
    assert len(parameters) < 10, len(parameters)
    assert [len(p) for p in parameters if isinstance(p, list)] == [1000]


@pytest.mark.parametrize("status", ["done", "failed"])
async def test_only_a_pending_delivery_can_carry_a_lease(
    status: str, service: EventService, db_session: AsyncSession
):
    await _emit_committed(service, db_session, 1)
    (delivery,) = await outbox.claim(db_session, "sse", "worker-a")
    await db_session.commit()

    with pytest.raises(IntegrityError) as exc:
        await db_session.execute(
            update(EventDelivery).where(EventDelivery.id == delivery.id).values(status=status)
        )
    assert getattr(exc.value.orig, "sqlstate", None) == "23514"  # check_violation
    assert "ck_event_deliveries_lease_pending" in str(exc.value.orig)
    await db_session.rollback()
