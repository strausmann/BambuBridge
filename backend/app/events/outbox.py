"""Outbox queue: subscribers claim their pending deliveries, then complete or fail them.

Nothing here commits. A worker runs this cycle::

    batch = await claim(session, "rules", worker_id)
    await session.commit()            # the lease is stored: the batch is this worker's
    ...                               # process the batch, outside any transaction
    await complete(session, worker_id, done_ids)
    await fail(session, worker_id, failed_id, "reason")
    await session.commit()

**Lease.** :func:`claim` marks each delivery with the id of the worker and a lease of
``LEASE_SECONDS``. Until then no other claim returns it, also not after the claim was
committed. :func:`complete` and :func:`fail` end the lease; they change only deliveries the
calling worker still holds, so a late result of a worker that lost its delivery to another
one changes nothing (the return value tells). The worker id is any string that is unique to
the worker for as long as it runs, for example a UUID made at its start.

**Dead workers.** A lease that runs out without a result means the worker died or hung. The
next claim takes the delivery over and counts one attempt for it. After ``MAX_ATTEMPTS``
attempts (failures and lost leases together) the delivery is set to ``failed`` and no longer
handed out, so a delivery that kills its workers cannot stay first in line for ever. Commit
right after :func:`claim`: a claim that is rolled back, or whose worker dies inside
:func:`claim` or before the commit, leaves no lease and is not counted. Nothing was
processed under a stored lease then, so the delivery is simply free again.

**At least once.** A delivery can reach its handler more than once: a worker that dies
after the side effect and before its ``complete`` is committed leaves a lease that runs out,
and the next worker runs the handler again. Handlers must be idempotent (for example by
keying their effect on the event id).

**Batch size.** There is no lease renewal, on purpose: a worker either finishes its batch
inside ``LEASE_SECONDS`` or loses what is left of it. The rest of a batch that takes longer
is taken over by another worker of the same subscriber while the first one is still at
work, so those handlers run twice, and each take-over counts an attempt. Choose ``limit``
so that a whole batch is done well inside the lease; with slow handlers or a small
container (little CPU, little memory) take a small ``limit`` rather than the default.

**Short transactions.** Besides the row locks, an open claim transaction holds a read lock
on ``events``, and creating a monthly partition needs that table exclusively for a moment.
Partition upkeep gives up after a few seconds and tries again a minute later (see
:mod:`app.events.partitions`), so a transaction that stays open for long keeps new
partitions from being created. The lease is what makes the early commit possible.

Order: :func:`claim` returns deliveries by event time, then delivery id. A delivery that
failed comes back only after its wait, so it can be overtaken by later ones; and two workers
of one subscriber get disjoint batches whose relative order is up to them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import BigInteger, any_, bindparam, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.validation import check_subscriber, check_worker, is_delivery_id, make_storable
from app.models.event import Event
from app.models.event_delivery import EventDelivery
from app.repositories import events as events_repo
from app.security.masking import mask

MAX_ATTEMPTS = 10
MAX_ERROR_LENGTH = 2000
MAX_CLAIM_LIMIT = 1000
# How long a claimed delivery belongs to its worker without a result.
LEASE_SECONDS = 300
LEASE_EXPIRED_ERROR = "lease expired"


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


# One statement: pick the due deliveries in order (skipping rows another claim holds right
# now), and give them to the worker. A delivery that still carries a lease here is one whose
# lease ran out: that counts as an attempt, and the last allowed attempt ends it.
CLAIM_STATEMENT = text(
    """
    WITH due AS (
        SELECT id
        FROM event_deliveries
        WHERE subscriber = :subscriber
          AND status = 'pending'
          AND available_at <= clock_timestamp()
          AND (claimed_until IS NULL OR claimed_until < clock_timestamp())
        ORDER BY event_occurred_at, id
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE event_deliveries AS d
    SET attempts = d.attempts + CASE WHEN d.claimed_until IS NULL THEN 0 ELSE 1 END,
        last_error = CASE
            WHEN d.claimed_until IS NULL THEN d.last_error ELSE :lease_expired
        END,
        status = CASE
            WHEN d.claimed_until IS NOT NULL AND d.attempts + 1 >= :max_attempts THEN 'failed'
            ELSE 'pending'
        END,
        claimed_by = CASE
            WHEN d.claimed_until IS NOT NULL AND d.attempts + 1 >= :max_attempts THEN NULL
            ELSE CAST(:worker AS text)
        END,
        claimed_until = CASE
            WHEN d.claimed_until IS NOT NULL AND d.attempts + 1 >= :max_attempts THEN NULL
            ELSE clock_timestamp() + make_interval(secs => :lease)
        END
    FROM due
    WHERE d.id = due.id
    RETURNING d.id, d.subscriber, d.status, d.attempts, d.event_id, d.event_occurred_at
    """
)


async def claim(
    session: AsyncSession, subscriber: str, worker: str, limit: int = 100
) -> list[Delivery]:
    """Give up to ``limit`` (1 to 1000) due pending deliveries of ``subscriber`` to ``worker``.

    Returned deliveries carry a lease of ``LEASE_SECONDS`` for ``worker``; commit to keep
    it (see the module text). ``FOR UPDATE SKIP LOCKED``: deliveries another claim holds
    locked are left out instead of waited for, so concurrent workers never get the same
    delivery and never block each other.

    A delivery whose earlier lease ran out is returned with one more attempt on record
    (``last_error`` says ``lease expired``); if that was its last attempt it is set to
    ``failed`` instead and not returned, so the result can be shorter than the number of due
    deliveries. Raises ``ValueError`` for a subscriber name, worker id or limit outside the
    allowed values, before anything is sent to the database.
    """
    check_subscriber(subscriber)
    check_worker(worker)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_CLAIM_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {MAX_CLAIM_LIMIT}")
    result = await session.execute(
        CLAIM_STATEMENT,
        {
            "subscriber": subscriber,
            "worker": worker,
            "limit": limit,
            "max_attempts": MAX_ATTEMPTS,
            "lease": float(LEASE_SECONDS),
            "lease_expired": LEASE_EXPIRED_ERROR,
        },
    )
    rows = sorted(
        (row for row in result if row.status == "pending"),
        key=lambda row: (row.event_occurred_at, row.id),
    )
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


async def complete(session: AsyncSession, worker: str, ids: Sequence[int]) -> int:
    """Mark deliveries as done; returns how many were.

    Only pending deliveries that ``worker`` holds are changed. A smaller number than
    ``len(ids)`` means the rest was taken over by another worker after the lease ran out (or
    was completed or failed before). ``ids`` is a list or tuple of at most
    ``MAX_CLAIM_LIMIT`` delivery ids (integers as returned by :func:`claim`); anything else
    raises ``ValueError`` before a statement is sent.
    """
    check_worker(worker)
    if (
        not isinstance(ids, list | tuple)
        or len(ids) > MAX_CLAIM_LIMIT
        or not all(is_delivery_id(item) for item in ids)
    ):
        raise ValueError(f"ids must be a list of at most {MAX_CLAIM_LIMIT} delivery ids (integers)")
    if not ids:
        return 0
    result = await session.execute(
        update(EventDelivery)
        .where(
            # One array parameter: the statement is the same for 1 and for 1000 ids.
            EventDelivery.id == any_(bindparam("ids", list(ids), type_=ARRAY(BigInteger))),
            EventDelivery.status == "pending",
            EventDelivery.claimed_by == worker,
        )
        .values(status="done", claimed_by=None, claimed_until=None)
    )
    return int(cast("CursorResult[Any]", result).rowcount)


_FAIL = text(
    """
    UPDATE event_deliveries
    SET attempts = attempts + 1,
        last_error = :error,
        status = CASE WHEN attempts + 1 >= :max_attempts THEN 'failed' ELSE 'pending' END,
        available_at = CASE
            WHEN attempts + 1 >= :max_attempts THEN available_at
            ELSE clock_timestamp() + make_interval(secs => power(2, attempts + 1))
        END,
        claimed_by = NULL,
        claimed_until = NULL
    WHERE id = :id AND status = 'pending' AND claimed_by = :worker
    """
)


async def fail(session: AsyncSession, worker: str, id: int, error: str) -> bool:  # noqa: A002
    """Count a failed attempt of a delivery ``worker`` holds; ``False`` if it does not.

    The delivery becomes due again after ``2^attempts`` seconds (2 s after the first
    failure, 512 s after the ninth); the tenth attempt sets it to ``failed`` for good.
    ``error`` is stored in ``last_error``: NUL characters removed and surrogate code points
    replaced by U+FFFD (PostgreSQL text cannot hold them), secrets found by name masked
    (:func:`app.security.masking.mask`: ``password=...``, ``Authorization: ...``, ``Bearer``
    credentials and the like; ``read`` callers see the text in the event API), then cut to
    2000 characters. Masking is a safety net, not a licence: pass a short reason, never
    payload contents or secrets.
    """
    check_worker(worker)
    if not is_delivery_id(id):
        raise ValueError("id must be a delivery id (integer)")
    # Masked before it is cut, as in the communication log: ``read`` sees it in the event API.
    reason = mask(make_storable(error))[:MAX_ERROR_LENGTH]
    result = await session.execute(
        _FAIL, {"id": id, "worker": worker, "error": reason, "max_attempts": MAX_ATTEMPTS}
    )
    return bool(cast("CursorResult[Any]", result).rowcount)
