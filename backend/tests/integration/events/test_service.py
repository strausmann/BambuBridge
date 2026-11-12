from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events import outbox
from app.events import service as service_module
from app.events.partitions import ensure_partitions, partition_name
from app.events.service import EventService, InvalidEventTypeError, register_subscriber
from app.models.event import Event
from app.models.event_delivery import EventDelivery
from app.repositories import events as events_repo
from app.settings_store.store import SettingsStore
from tests.integration.events.conftest import EVENT_TYPE, SOURCE_A, SOURCE_B, counts, emit


async def test_emit_writes_event_and_delivery_atomically(
    service: EventService, db_session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
):
    event_id = await emit(service, db_session)

    assert isinstance(event_id, uuid.UUID)
    # Written, but only inside the caller's transaction: emit does not commit.
    assert len((await db_session.scalars(select(Event))).all()) == 1
    assert len((await db_session.scalars(select(EventDelivery))).all()) == 1
    assert await counts(sessions) == (0, 0)

    await db_session.rollback()

    assert await counts(sessions) == (0, 0)
    assert (await db_session.scalars(select(Event))).all() == []
    assert (await db_session.scalars(select(EventDelivery))).all() == []


async def test_emit_stores_the_event_and_a_pending_delivery(
    service: EventService, db_session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
):
    correlation = uuid.uuid4()
    event_id = await service.emit(
        db_session,
        type=EVENT_TYPE,
        source_instance_id=SOURCE_A,
        payload={"label": "x", "sequence": 3},
        schema_version=2,
        dedup_key="3",
        correlation_id=correlation,
    )
    await db_session.commit()

    assert await counts(sessions) == (1, 1)
    event = (await db_session.scalars(select(Event))).one()
    assert (event.id, event.type, event.source_instance_id) == (event_id, EVENT_TYPE, SOURCE_A)
    assert event.payload == {"label": "x", "sequence": 3}
    assert (event.schema_version, event.dedup_key, event.correlation_id) == (2, "3", correlation)
    assert event.occurred_at.utcoffset() is not None
    delivery = (await db_session.scalars(select(EventDelivery))).one()
    assert (delivery.event_id, delivery.event_occurred_at) == (event.id, event.occurred_at)
    assert (delivery.subscriber, delivery.status, delivery.attempts) == ("sse", "pending", 0)
    assert delivery.available_at == event.occurred_at
    assert delivery.last_error is None


async def test_emit_writes_one_delivery_per_registered_subscriber(
    service: EventService, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(service_module, "_SUBSCRIBERS", ["sse"])
    register_subscriber("rules")
    register_subscriber("rules")  # registering twice changes nothing

    await emit(service, db_session)
    await db_session.commit()

    rows = (await db_session.scalars(select(EventDelivery).order_by(EventDelivery.id))).all()
    assert [r.subscriber for r in rows] == ["sse", "rules"]
    assert service_module.subscribers() == ("sse", "rules")


async def test_emit_without_subscribers_writes_the_event_only(
    service: EventService,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(service_module, "_SUBSCRIBERS", [])
    assert await emit(service, db_session) is not None
    await db_session.commit()
    assert await counts(sessions) == (1, 0)


@pytest.mark.parametrize("name", ["", "SSE", "has space", "a-b", "1abc", "x" * 65])
def test_register_subscriber_rejects_bad_names(name: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(service_module, "_SUBSCRIBERS", ["sse"])
    with pytest.raises(ValueError, match="subscriber name"):
        register_subscriber(name)
    assert service_module.subscribers() == ("sse",)


async def test_dedup_key_within_window_returns_none(
    service: EventService, db_session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
):
    first = await emit(service, db_session, dedup_key="k1")
    await db_session.commit()

    assert first is not None
    assert await emit(service, db_session, dedup_key="k1") is None
    await db_session.commit()
    assert await counts(sessions) == (1, 1)

    # Another key, another source and the source-less stream are different streams.
    assert await emit(service, db_session, dedup_key="k2") is not None
    assert await emit(service, db_session, source=SOURCE_B, dedup_key="k1") is not None
    assert await emit(service, db_session, source=None, dedup_key="k1") is not None
    assert await emit(service, db_session, source=None, dedup_key="k1") is None
    await db_session.commit()
    assert await counts(sessions) == (4, 4)


async def test_dedup_applies_inside_one_transaction(
    service: EventService, db_session: AsyncSession
):
    assert await emit(service, db_session, dedup_key="same") is not None
    assert await emit(service, db_session, dedup_key="same") is None


async def test_events_without_dedup_key_are_never_deduplicated(
    service: EventService, db_session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
):
    assert await emit(service, db_session) is not None
    assert await emit(service, db_session) is not None
    await db_session.commit()
    assert await counts(sessions) == (2, 2)


async def test_dedup_key_after_window_creates_event(
    service: EventService,
    store: SettingsStore,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
):
    # The window is a runtime setting: changing it takes effect without a restart.
    await store.set_many(db_session, {"events.dedup_window_seconds": 1})
    assert await emit(service, db_session, dedup_key="k1") is not None
    await db_session.commit()
    assert await emit(service, db_session, dedup_key="k1") is None
    await db_session.rollback()

    await asyncio.sleep(1.2)

    assert await emit(service, db_session, dedup_key="k1") is not None
    await db_session.commit()
    assert await counts(sessions) == (2, 2)


async def test_dedup_window_zero_switches_dedup_off(
    service: EventService, store: SettingsStore, db_session: AsyncSession
):
    await store.set_many(db_session, {"events.dedup_window_seconds": 0})
    assert await emit(service, db_session, dedup_key="k1") is not None
    assert await emit(service, db_session, dedup_key="k1") is not None


@pytest.mark.parametrize(
    "name",
    [
        "",
        "demo.tick",
        "integration.demo",
        "integration.demo.tick.extra",
        "other.demo.tick",
        "Integration.demo.tick",
        "integration.Demo.tick",
        "integration.de-mo.tick",
        "integration..tick",
        "integration.demo.tick\n",
        " integration.demo.tick",
    ],
)
async def test_invalid_event_type_rejected(
    name: str,
    service: EventService,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
):
    with pytest.raises(InvalidEventTypeError):
        await service.emit(
            db_session, type=name, source_instance_id=SOURCE_A, payload={}, schema_version=1
        )
    await db_session.commit()
    assert await counts(sessions) == (0, 0)


@pytest.mark.parametrize(
    "name",
    ["account.user.created", "inventory.spool_1.updated", "integration.demo.tick", "display.x.y"],
)
async def test_valid_event_types_accepted(
    name: str, service: EventService, db_session: AsyncSession
):
    assert await service.emit(
        db_session, type=name, source_instance_id=None, payload={}, schema_version=1
    )


async def test_order_per_source_preserved_under_concurrency(
    service: EventService, sessions: async_sessionmaker[AsyncSession], db_session: AsyncSession
):
    total = 50
    committed: list[int] = []

    async def one(n: int) -> None:
        async with sessions() as session:
            await emit(service, session, n=n)
            # The caller's transaction does other work for a varying time before it commits.
            await asyncio.sleep(((n * 7) % 5) * 0.004)
            await session.commit()
            committed.append(n)

    await asyncio.gather(*(one(n) for n in range(total)))

    claimed = await outbox.claim(db_session, "sse", "w1", limit=total)
    assert len(claimed) == total
    order = [d.event.payload["n"] for d in claimed if d.event is not None]
    # A consumer sees the events of one source in the order their transactions committed.
    assert order == committed
    stamps = [d.event_occurred_at for d in claimed]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == total


async def test_emit_waits_for_an_open_emit_of_the_same_source_only(
    service: EventService, db_session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
):
    await emit(service, db_session, n=1)  # transaction stays open

    async def other(source: uuid.UUID, n: int) -> None:
        async with sessions() as session:
            await emit(service, session, source=source, n=n)
            await session.commit()

    await asyncio.wait_for(other(SOURCE_B, 2), timeout=5)  # another source is not held up
    same = asyncio.create_task(other(SOURCE_A, 3))
    await asyncio.sleep(0.3)
    assert not same.done()

    await db_session.commit()
    await asyncio.wait_for(same, timeout=5)

    claimed = await outbox.claim(db_session, "sse", "w1")
    by_source = [d.event.payload["n"] for d in claimed if d.event.source_instance_id == SOURCE_A]
    assert by_source == [1, 3]


async def test_concurrent_emits_with_one_dedup_key_write_one_event(
    service: EventService, sessions: async_sessionmaker[AsyncSession]
):
    async def one() -> uuid.UUID | None:
        async with sessions() as session:
            event_id = await emit(service, session, dedup_key="same")
            await asyncio.sleep(0.05)  # both transactions are open at the same time
            await session.commit()
            return event_id

    results = await asyncio.gather(one(), one())

    assert sorted(r is None for r in results) == [False, True]
    assert await counts(sessions) == (1, 1)


def _relations(node: dict[str, Any]) -> set[str]:
    found = {node["Relation Name"]} if "Relation Name" in node else set()
    for child in node.get("Plans", []):
        found |= _relations(child)
    return found


async def test_dedup_lookup_reads_only_the_partitions_of_the_window(db_session: AsyncSession):
    now = datetime.now(UTC)
    index = now.year * 12 + now.month - 1

    def name(offset: int) -> str:
        return partition_name("events", (index + offset) // 12, (index + offset) % 12 + 1)

    # Partitions of the three months before this one, as a server running for a while has.
    await ensure_partitions(
        db_session, datetime((index - 3) // 12, (index - 3) % 12 + 1, 1, tzinfo=UTC)
    )
    await db_session.commit()
    statement = events_repo.duplicate_query(
        source_instance_id=SOURCE_A, type=EVENT_TYPE, dedup_key="k", window_seconds=60
    ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})

    raw = (await db_session.execute(text(f"EXPLAIN (FORMAT JSON) {statement}"))).scalar_one()
    plan = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]

    # The lower time bound is fixed when the statement starts, so the partitions that end
    # before the window are left out. (The month just before this one is not asserted: in
    # the first minute of a month it is part of the window.)
    scanned = _relations(plan)
    assert name(0) in scanned, plan
    assert not scanned & {name(-3), name(-2)}, scanned


@pytest.mark.parametrize("payload", [None, [], "text", 3, [("a", 1)]])
async def test_emit_rejects_a_payload_that_is_not_a_dict(
    payload: object,
    service: EventService,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
):
    with pytest.raises(ValueError, match="payload"):
        await service.emit(
            db_session,
            type=EVENT_TYPE,
            source_instance_id=SOURCE_A,
            payload=payload,  # type: ignore[arg-type]
            schema_version=1,
        )
    await db_session.commit()
    assert await counts(sessions) == (0, 0)


@pytest.mark.parametrize("version", [0, -1, True, False, 1.0, "1", None])
async def test_emit_rejects_a_schema_version_that_is_not_a_positive_int(
    version: object,
    service: EventService,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
):
    with pytest.raises(ValueError, match="schema_version"):
        await service.emit(
            db_session,
            type=EVENT_TYPE,
            source_instance_id=SOURCE_A,
            payload={},
            schema_version=version,  # type: ignore[arg-type]
        )
    await db_session.commit()
    assert await counts(sessions) == (0, 0)


def _plan_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = [node]
    for child in node.get("Plans", []):
        found += _plan_nodes(child)
    return found


@pytest.mark.parametrize("source", [SOURCE_A, None], ids=["source", "no-source"])
async def test_dedup_lookup_uses_the_dedup_index(
    source: uuid.UUID | None, db_session: AsyncSession
):
    # A source with history: the index on (source, time) alone would read all of it.
    await db_session.execute(
        text(
            "INSERT INTO events (type, source_instance_id, payload, schema_version, dedup_key) "
            "SELECT CAST(:type AS text), CAST(:source AS uuid), '{}'::jsonb, 1, 'k' || g "
            "FROM generate_series(1, 3000) AS g"
        ),
        {"type": EVENT_TYPE, "source": source},
    )
    await db_session.commit()
    await db_session.execute(text("ANALYZE events"))
    statement = events_repo.duplicate_query(
        source_instance_id=source, type=EVENT_TYPE, dedup_key="k77", window_seconds=600
    ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})

    raw = (await db_session.execute(text(f"EXPLAIN (FORMAT JSON) {statement}"))).scalar_one()
    plan = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]

    children = set(
        (
            await db_session.scalars(
                text(
                    "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                    "WHERE i.inhparent = to_regclass('ix_events_dedup')"
                )
            )
        ).all()
    )
    # Asserted for the partition that holds the rows; the empty ones of the next months
    # are planned without statistics.
    now = datetime.now(UTC)
    current = partition_name("events", now.year, now.month)
    used = {n.get("Index Name") for n in _plan_nodes(plan) if n.get("Relation Name") == current}
    assert used, plan
    assert used <= children, (used, plan)
