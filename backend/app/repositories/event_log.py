"""Reading events and the communication log: filtered keyset pages, single rows, replay.

Nothing here writes. Lists are ordered newest first by ``(occurred_at, id)`` and fetch one
row more than asked for, so the caller can tell whether there is a next page.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, case, exists, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.communication_entry import CommunicationEntry
from app.models.event import Event
from app.models.event_delivery import EventDelivery


def _deliveries_with(status: str | None = None, *, other_than: str | None = None) -> Any:
    """``EXISTS`` a delivery of the outer event (with ``status``, or not ``other_than``)."""
    conditions: list[ColumnElement[bool]] = [
        EventDelivery.event_id == Event.id,
        EventDelivery.event_occurred_at == Event.occurred_at,
    ]
    if status is not None:
        conditions.append(EventDelivery.status == status)
    if other_than is not None:
        conditions.append(EventDelivery.status != other_than)
    return exists().where(*conditions)


# The delivery state of an event over all its subscribers (see ``EventView``).
DELIVERY_STATUS = case(
    (_deliveries_with("failed"), literal("failed")),
    (_deliveries_with("pending"), literal("pending")),
    else_=literal("done"),
).label("delivery_status")


@dataclass(frozen=True)
class EventRow:
    event: Event
    delivery_status: str


def _before(
    occurred_at: Any, row_id: Any, cursor: tuple[datetime, uuid.UUID]
) -> ColumnElement[bool]:
    at, key = cursor
    # The plain time bound lets PostgreSQL leave out the partitions after the cursor.
    return and_(occurred_at <= at, tuple_(occurred_at, row_id) < tuple_(literal(at), literal(key)))


async def list_events(
    session: AsyncSession,
    *,
    start: datetime | None,
    end: datetime | None,
    source: uuid.UUID | None,
    type: str | None,  # noqa: A002  # the column name
    status: str | None,
    cursor: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[EventRow]:
    """Up to ``limit + 1`` events, newest first; ``start`` inclusive, ``end`` exclusive."""
    query = select(Event, DELIVERY_STATUS)
    if start is not None:
        query = query.where(Event.occurred_at >= start)
    if end is not None:
        query = query.where(Event.occurred_at < end)
    if source is not None:
        query = query.where(Event.source_instance_id == source)
    if type is not None:
        query = query.where(Event.type == type)
    if status == "failed":
        query = query.where(_deliveries_with("failed"))
    elif status == "pending":
        query = query.where(_deliveries_with("pending"), ~_deliveries_with("failed"))
    elif status == "done":
        query = query.where(~_deliveries_with(other_than="done"))
    if cursor is not None:
        query = query.where(_before(Event.occurred_at, Event.id, cursor))
    query = query.order_by(Event.occurred_at.desc(), Event.id.desc()).limit(limit + 1)
    rows = await session.execute(query)
    return [EventRow(event=row[0], delivery_status=row[1]) for row in rows]


async def get_event(session: AsyncSession, event_id: uuid.UUID) -> EventRow | None:
    row = (
        await session.execute(select(Event, DELIVERY_STATUS).where(Event.id == event_id).limit(1))
    ).first()
    return None if row is None else EventRow(event=row[0], delivery_status=row[1])


async def deliveries_of(session: AsyncSession, event: Event) -> Sequence[EventDelivery]:
    rows = await session.scalars(
        select(EventDelivery)
        .where(
            EventDelivery.event_id == event.id,
            EventDelivery.event_occurred_at == event.occurred_at,
        )
        .order_by(EventDelivery.subscriber, EventDelivery.id)
    )
    return rows.all()


async def events_after(
    session: AsyncSession, event_id: uuid.UUID, limit: int
) -> list[Event] | None:
    """Up to ``limit`` events after the event ``event_id``, oldest first.

    ``None`` when that event does not exist (unknown id, or removed by retention).
    """
    anchor = (
        await session.execute(select(Event.occurred_at).where(Event.id == event_id).limit(1))
    ).first()
    if anchor is None:
        return None
    at = anchor[0]
    rows = await session.scalars(
        select(Event)
        .where(
            Event.occurred_at >= at,
            tuple_(Event.occurred_at, Event.id) > tuple_(literal(at), literal(event_id)),
        )
        .order_by(Event.occurred_at, Event.id)
        .limit(limit)
    )
    return list(rows)


async def list_communication(
    session: AsyncSession,
    *,
    start: datetime | None,
    end: datetime | None,
    instance: uuid.UUID | None,
    status: str | None,
    cursor: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[CommunicationEntry]:
    """Up to ``limit + 1`` entries, newest first.

    ``status``: a status code (``"404"``), a class (``"4xx"``) or ``"none"`` (no answer).
    """
    query = select(CommunicationEntry)
    if start is not None:
        query = query.where(CommunicationEntry.occurred_at >= start)
    if end is not None:
        query = query.where(CommunicationEntry.occurred_at < end)
    if instance is not None:
        query = query.where(CommunicationEntry.instance_id == instance)
    if status == "none":
        query = query.where(CommunicationEntry.status.is_(None))
    elif status is not None and status.endswith("xx"):
        low = int(status[0]) * 100
        query = query.where(CommunicationEntry.status >= low, CommunicationEntry.status < low + 100)
    elif status is not None:
        query = query.where(CommunicationEntry.status == int(status))
    if cursor is not None:
        query = query.where(_before(CommunicationEntry.occurred_at, CommunicationEntry.id, cursor))
    query = query.order_by(
        CommunicationEntry.occurred_at.desc(), CommunicationEntry.id.desc()
    ).limit(limit + 1)
    return list(await session.scalars(query))


async def get_communication(
    session: AsyncSession, entry_id: uuid.UUID
) -> CommunicationEntry | None:
    return (
        await session.scalars(
            select(CommunicationEntry).where(CommunicationEntry.id == entry_id).limit(1)
        )
    ).first()
