from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events import outbox
from app.events import service as service_module
from app.events.service import EventService, InvalidEventTypeError, register_subscriber
from app.models.event import Event
from app.models.event_delivery import EventDelivery
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

    claimed = await outbox.claim(db_session, "sse", limit=total)
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

    claimed = await outbox.claim(db_session, "sse")
    by_source = [d.event.payload["n"] for d in claimed if d.event.source_instance_id == SOURCE_A]
    assert by_source == [1, 3]
