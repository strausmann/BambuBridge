"""Event rows: per-source lock, dedup lookup, insert, and loading events for deliveries.

Nothing here commits; the caller owns the transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, any_, bindparam, func, insert, select, text
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP, UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.event_delivery import EventDelivery

# First key of the two-key advisory lock form ("bbev"): the locks of the event core share
# no key space with the single-key locks used elsewhere. The second key is ``hashtext`` of
# the source for the per-source locks and a fixed number for anything else (see
# ``app.events.partitions``).
EVENTS_LOCK_NAMESPACE = 0x6262_6576


async def set_local_lock_timeout(session: AsyncSession, value: str) -> str:
    """``SET LOCAL lock_timeout`` (rest of the caller's transaction); returns the old value.

    Call it again with the returned value to put the caller's setting back.
    """
    # The subquery (kept apart by OFFSET 0) reads the old value before the new one is set.
    previous = await session.scalar(
        text(
            "SELECT p.previous FROM (SELECT current_setting('lock_timeout') AS previous OFFSET 0) "
            "AS p WHERE set_config('lock_timeout', :value, true) IS NOT NULL"
        ),
        {"value": value},
    )
    return str(previous)


async def lock_source(
    session: AsyncSession, source_instance_id: uuid.UUID | None, *, timeout_seconds: float
) -> None:
    """Serialise writers of one source until the caller's transaction ends.

    ``pg_advisory_xact_lock(<namespace>, hashtext(<source id as text>))``; events without a
    source share one lock. Waiters are served in the order they asked, and each waits at most
    ``timeout_seconds``: then the database error with SQLSTATE 55P03 is raised and the
    caller's transaction is aborted. The caller's own ``lock_timeout`` is back in place when
    the lock was taken.
    """
    previous = await set_local_lock_timeout(session, f"{int(timeout_seconds * 1000)}ms")
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, hashtext(:source))"),
        {
            "namespace": EVENTS_LOCK_NAMESPACE,
            "source": "" if source_instance_id is None else str(source_instance_id),
        },
    )
    await set_local_lock_timeout(session, previous)


def duplicate_query(
    *,
    source_instance_id: uuid.UUID | None,
    type: str,  # noqa: A002  # the column name
    dedup_key: str,
    window_seconds: int,
) -> Select[uuid.UUID]:
    """Lookup of an event of the source and type with this ``dedup_key`` in the last seconds.

    Served by the partial index ``ix_events_dedup`` (source, type, key, time; rows with a
    key only). The lower time bound uses ``statement_timestamp()``, not
    ``clock_timestamp()``: it is fixed for the statement, so PostgreSQL leaves out the
    partitions older than the window and can use the index for the range. A volatile clock
    would make every call read all partitions. The statement starts after
    :func:`lock_source` returned, so no earlier event of the source can be later than it.
    """
    same_source = (
        Event.source_instance_id.is_(None)
        if source_instance_id is None
        else Event.source_instance_id == source_instance_id
    )
    since = func.statement_timestamp() - func.make_interval(0, 0, 0, 0, 0, 0, window_seconds)
    return (
        select(Event.id)
        .where(
            same_source,
            Event.type == type,
            Event.dedup_key == dedup_key,
            Event.occurred_at > since,
        )
        .limit(1)
    )


async def duplicate_exists(
    session: AsyncSession,
    *,
    source_instance_id: uuid.UUID | None,
    type: str,  # noqa: A002  # the column name
    dedup_key: str,
    window_seconds: int,
) -> bool:
    """Whether the source wrote an event of this type and ``dedup_key`` in the last seconds."""
    found = await session.scalar(
        duplicate_query(
            source_instance_id=source_instance_id,
            type=type,
            dedup_key=dedup_key,
            window_seconds=window_seconds,
        )
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
    """Events by ``(id, occurred_at)``; keys without a row are missing from the result.

    Two array parameters, whatever the number of keys (a row-value ``IN`` list grows with it
    and fails beyond a few thousand pairs). The time array lets PostgreSQL leave out the
    partitions of other months; the pairs are matched here.
    """
    wanted = set(keys)
    if not wanted:
        return {}
    ids = bindparam("ids", list({key[0] for key in wanted}), type_=ARRAY(UUID(as_uuid=True)))
    times = bindparam(
        "times", list({key[1] for key in wanted}), type_=ARRAY(TIMESTAMP(timezone=True))
    )
    rows = await session.scalars(
        select(Event)
        .where(Event.id == any_(ids), Event.occurred_at == any_(times))
        .execution_options(populate_existing=True)
    )
    return {
        (event.id, event.occurred_at): event
        for event in rows
        if (event.id, event.occurred_at) in wanted
    }
