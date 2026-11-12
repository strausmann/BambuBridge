"""Event rows: per-source lock, dedup lookup, insert, and loading events for deliveries.

Nothing here commits; the caller owns the transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.event_delivery import EventDelivery

# First key of the two-key advisory lock form, so the per-source locks share no key space
# with the single-key locks used elsewhere ("bbev").
_SOURCE_LOCK_NAMESPACE = 0x6262_6576


async def lock_source(session: AsyncSession, source_instance_id: uuid.UUID | None) -> None:
    """Serialise writers of one source until the caller's transaction ends.

    ``pg_advisory_xact_lock(<namespace>, hashtext(<source id as text>))``; events without a
    source share one lock. Waiters are served in the order they asked.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:source))"),
        {
            "namespace": _SOURCE_LOCK_NAMESPACE,
            "source": "" if source_instance_id is None else str(source_instance_id),
        },
    )


async def duplicate_exists(
    session: AsyncSession,
    *,
    source_instance_id: uuid.UUID | None,
    dedup_key: str,
    window_seconds: int,
) -> bool:
    """Whether the source wrote an event with this ``dedup_key`` in the last seconds."""
    same_source = (
        Event.source_instance_id.is_(None)
        if source_instance_id is None
        else Event.source_instance_id == source_instance_id
    )
    since = func.clock_timestamp() - func.make_interval(0, 0, 0, 0, 0, 0, window_seconds)
    found = await session.scalar(
        select(Event.id)
        .where(same_source, Event.dedup_key == dedup_key, Event.occurred_at > since)
        .limit(1)
    )
    return found is not None


async def insert_event(
    session: AsyncSession,
    *,
    type: str,  # noqa: A002  # the column name
    source_instance_id: uuid.UUID | None,
    payload: dict[str, Any],
    schema_version: int,
    dedup_key: str | None,
    correlation_id: uuid.UUID | None,
) -> tuple[uuid.UUID, datetime]:
    """Insert the event; ``occurred_at`` is the database clock at this moment.

    The wall clock (not the transaction start time) is what keeps the events of one source
    in commit order: it is read while :func:`lock_source` is held.
    """
    row = (
        await session.execute(
            insert(Event)
            .values(
                occurred_at=func.clock_timestamp(),
                type=type,
                source_instance_id=source_instance_id,
                payload=payload,
                schema_version=schema_version,
                dedup_key=dedup_key,
                correlation_id=correlation_id,
            )
            .returning(Event.id, Event.occurred_at)
        )
    ).one()
    return row.id, row.occurred_at


async def insert_deliveries(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    event_occurred_at: datetime,
    subscribers: Sequence[str],
) -> None:
    """One pending delivery per subscriber, due at once."""
    if not subscribers:
        return
    await session.execute(
        insert(EventDelivery),
        [
            {
                "event_id": event_id,
                "event_occurred_at": event_occurred_at,
                "subscriber": subscriber,
                "available_at": event_occurred_at,
            }
            for subscriber in subscribers
        ],
    )


async def load_events(
    session: AsyncSession, keys: Iterable[tuple[uuid.UUID, datetime]]
) -> dict[tuple[uuid.UUID, datetime], Event]:
    """Events by ``(id, occurred_at)``; keys without a row are missing from the result."""
    wanted = list(set(keys))
    if not wanted:
        return {}
    rows = await session.scalars(
        select(Event)
        .where(tuple_(Event.id, Event.occurred_at).in_(wanted))
        .execution_options(populate_existing=True)
    )
    return {(event.id, event.occurred_at): event for event in rows}
