"""The live event stream: subscriber ``sse`` and the open server-sent event connections.

:class:`SseHub` runs one pump per server process. It claims the pending deliveries of the
subscriber ``sse`` from the outbox (:func:`app.events.outbox.claim`), commits the lease,
hands every event to all open connections of this process and completes the deliveries. It
runs whether or not a connection is open, so the ``sse`` deliveries never pile up.

**Live only, at least once.** A connection gets the events claimed while it is open. An
event whose ``complete`` was lost (a crash right after it was sent) is handed out again when
its lease runs out, so a client can see an event twice; the SSE ``id`` is the event id, and
clients drop an id they have seen. A client that was away resumes with ``Last-Event-ID``:
the route replays what came after that event from the ``events`` table (see
``app.api.routes.events``).

**One process.** The deliveries are claimed by one pump; with several server processes each
event reaches the connections of the process that claimed it only. BambuBridge runs one
process.

**Slow clients.** Each connection buffers up to ``QUEUE_SIZE`` events. A connection that
falls that far behind is ended; the client reconnects and resumes with ``Last-Event-ID``.

The numbers below are read at the time of use, so tests can shrink them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections import Counter, deque
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events import outbox
from app.models.event import Event
from app.schemas.events import StreamEvent

SUBSCRIBER = "sse"
# A comment line is sent after this many seconds without a message, so proxies and the
# browser keep the connection.
HEARTBEAT_SECONDS = 15.0
# Open stream connections per process; one more is answered with 429.
MAX_CONNECTIONS = 100
# Open stream connections per caller (token or browser session), so that one caller cannot
# take all of ``MAX_CONNECTIONS``; one more is answered with 429 too.
MAX_CONNECTIONS_PER_PRINCIPAL = 10
# How long the pump waits when the outbox had nothing for it.
POLL_INTERVAL_SECONDS = 0.25
# How long the pump waits after a database error before it tries again.
ERROR_BACKOFF_SECONDS = 5.0
# Deliveries per claim; far inside the lease (sending is in memory).
CLAIM_LIMIT = 100
# Events a connection may have waiting before it is ended as too slow.
QUEUE_SIZE = 1000
# How often a stream checks its caller's credentials again.
REAUTH_SECONDS = 60.0

_log = logging.getLogger(__name__)


# Who holds a stream: ``("key", <token id>)`` or ``("session", <browser session id>)``.
Principal = tuple[str, uuid.UUID]


class ConnectionLimitError(RuntimeError):
    """``MAX_CONNECTIONS`` streams, or ``MAX_CONNECTIONS_PER_PRINCIPAL`` of one caller, are
    open already."""


def stream_event(event: Event) -> StreamEvent:
    return StreamEvent(
        id=event.id,
        occurred_at=event.occurred_at,
        type=event.type,
        source_instance_id=event.source_instance_id,
        schema_version=event.schema_version,
        correlation_id=event.correlation_id,
        payload=event.payload,
    )


def format_event(event: StreamEvent) -> str:
    """One SSE message: ``id`` is the event id, ``data`` the event as one line of JSON."""
    return f"id: {event.id}\ndata: {event.model_dump_json()}\n\n"


class Subscription:
    """The events waiting for one open connection."""

    def __init__(self, principal: Principal) -> None:
        self.principal = principal
        self._pending: deque[StreamEvent] = deque()
        self._ready = asyncio.Event()
        self.overflowed = False

    def push(self, event: StreamEvent) -> None:
        if self.overflowed:
            return
        if len(self._pending) >= QUEUE_SIZE:
            self.overflowed = True
            self._pending.clear()
        else:
            self._pending.append(event)
        self._ready.set()

    async def wait(self, timeout: float) -> bool:
        """Wait until something arrived; ``False`` after ``timeout`` seconds without."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout)
        except TimeoutError:
            return False
        return True

    def drain(self) -> list[StreamEvent]:
        self._ready.clear()
        events = list(self._pending)
        self._pending.clear()
        return events


class SseHub:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory
        self._subscriptions: set[Subscription] = set()
        self._per_principal: Counter[Principal] = Counter()
        self._task: asyncio.Task[None] | None = None
        # The lease owner of this process's claims.
        self._worker = f"sse-{uuid.uuid4()}"

    @property
    def connection_count(self) -> int:
        return len(self._subscriptions)

    def open(self, principal: Principal) -> Subscription:
        """Register a connection of ``principal``; ``ConnectionLimitError`` beyond
        ``MAX_CONNECTIONS`` in all or ``MAX_CONNECTIONS_PER_PRINCIPAL`` for this caller."""
        if len(self._subscriptions) >= MAX_CONNECTIONS:
            raise ConnectionLimitError
        if self._per_principal[principal] >= MAX_CONNECTIONS_PER_PRINCIPAL:
            raise ConnectionLimitError
        subscription = Subscription(principal)
        self._subscriptions.add(subscription)
        self._per_principal[principal] += 1
        return subscription

    def close(self, subscription: Subscription) -> None:
        """Unregister a connection; closing twice changes nothing."""
        if subscription not in self._subscriptions:
            return
        self._subscriptions.remove(subscription)
        self._per_principal[subscription.principal] -= 1
        if self._per_principal[subscription.principal] <= 0:
            del self._per_principal[subscription.principal]

    def broadcast(self, events: Iterable[StreamEvent]) -> None:
        for event in events:
            for subscription in list(self._subscriptions):
                subscription.push(event)
                if subscription.overflowed:
                    self.close(subscription)

    async def pump_once(self) -> int:
        """Claim, send and complete one batch; returns how many deliveries it took."""
        async with self._sessions() as session:
            batch = await outbox.claim(session, SUBSCRIBER, self._worker, limit=CLAIM_LIMIT)
            await session.commit()
        if not batch:
            return 0
        # An event removed by retention has nothing to send; its delivery is completed too.
        self.broadcast(stream_event(d.event) for d in batch if d.event is not None)
        async with self._sessions() as session:
            await outbox.complete(session, self._worker, [d.id for d in batch])
            await session.commit()
        return len(batch)

    async def _run(self) -> None:
        while True:
            try:
                taken = await self.pump_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the pump must keep running
                # The class only: a driver message can quote row values.
                _log.warning("sse pump failed (%s); retrying", type(exc).__name__)
                await asyncio.sleep(ERROR_BACKOFF_SECONDS)
                continue
            if taken == 0:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="sse-pump")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
