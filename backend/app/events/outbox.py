"""Outbox queue: subscribers claim their pending deliveries, then complete or fail them.

Nothing here commits. The rows returned by :func:`claim` stay locked until the caller's
transaction ends, so a worker claims, processes, calls :func:`complete` / :func:`fail` and
commits. If it rolls back or dies instead, the deliveries are simply pending again.

Order: :func:`claim` returns deliveries by event time, then delivery id. A delivery that
failed comes back only after its wait, so it can be overtaken by later ones; and two workers
of one subscriber get disjoint batches whose relative order is up to them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.event_delivery import EventDelivery
from app.repositories import events as events_repo

MAX_ATTEMPTS = 10
MAX_ERROR_LENGTH = 2000


@dataclass(frozen=True)
class Delivery:
    """A claimed delivery. ``event`` is ``None`` when the event no longer exists
    (its partition was dropped by retention)."""

    id: int
    subscriber: str
    attempts: int
    event_id: uuid.UUID
    event_occurred_at: datetime
    event: Event | None


async def claim(session: AsyncSession, subscriber: str, limit: int = 100) -> list[Delivery]:
    """Lock and return up to ``limit`` due pending deliveries of ``subscriber``.

    ``FOR UPDATE SKIP LOCKED``: deliveries another worker holds are left out instead of
    waited for, so concurrent workers never get the same delivery and never block each other.
    """
    rows = (
        await session.scalars(
            select(EventDelivery)
            .where(
                EventDelivery.subscriber == subscriber,
                EventDelivery.status == "pending",
                EventDelivery.available_at <= func.clock_timestamp(),
            )
            .order_by(EventDelivery.event_occurred_at, EventDelivery.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).all()
    events = await events_repo.load_events(
        session, ((row.event_id, row.event_occurred_at) for row in rows)
    )
    return [
        Delivery(
            id=row.id,
            subscriber=row.subscriber,
            attempts=row.attempts,
            event_id=row.event_id,
            event_occurred_at=row.event_occurred_at,
            event=events.get((row.event_id, row.event_occurred_at)),
        )
        for row in rows
    ]


async def complete(session: AsyncSession, ids: Sequence[int]) -> None:
    """Mark pending deliveries as done."""
    if not ids:
        return
    await session.execute(
        update(EventDelivery)
        .where(EventDelivery.id.in_(ids), EventDelivery.status == "pending")
        .values(status="done")
    )


_FAIL = text(
    """
    UPDATE event_deliveries
    SET attempts = attempts + 1,
        last_error = :error,
        status = CASE WHEN attempts + 1 >= :max_attempts THEN 'failed' ELSE 'pending' END,
        available_at = CASE
            WHEN attempts + 1 >= :max_attempts THEN available_at
            ELSE clock_timestamp() + make_interval(secs => power(2, attempts + 1))
        END
    WHERE id = :id AND status = 'pending'
    """
)


async def fail(session: AsyncSession, id: int, error: str) -> None:  # noqa: A002
    """Count a failed attempt of a pending delivery.

    It becomes due again after ``2^attempts`` seconds (2 s after the first failure, 512 s
    after the ninth); the tenth failure sets it to ``failed`` for good. ``error`` is stored
    in ``last_error`` (first 2000 characters): pass a short reason, never payload contents
    or secrets.
    """
    await session.execute(
        _FAIL, {"id": id, "error": error[:MAX_ERROR_LENGTH], "max_attempts": MAX_ATTEMPTS}
    )
