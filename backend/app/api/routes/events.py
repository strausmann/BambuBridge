"""Events: ``GET /api/v1/events``, ``/api/v1/events/{event_id}`` and the live stream.

All three need ``read``. Times in the query are ISO 8601 **with** a zone (a time without one
is refused with 422) and compared in UTC; ``from`` is inclusive, ``to`` exclusive. Lists are
newest first, paged with ``cursor`` (see :mod:`app.api.pagination`). ``delivery_status``
covers every subscriber, the live stream (``sse``) included: an event is ``pending`` until
the stream pump has handed it out too.

``GET /api/v1/events/stream`` is a server-sent event stream (``text/event-stream``): one
message per event (``id`` = event id, ``data`` = the event as JSON), a comment line after
``sse.HEARTBEAT_SECONDS`` without a message.

- **Resume.** With ``Last-Event-ID`` it first sends the events after that one, oldest
  first. More than ``REPLAY_LIMIT`` waiting: it sends that many and ends the stream with the
  comment ``END_REPLAY_CONTINUES``; the browser reconnects with the last id it got and gets
  the next batch. An id that is not an event (unknown, malformed, or removed by retention)
  cannot be resumed from: the stream sends one ``event: reset`` message (``data: {}``) and
  goes live, and the client loads the list again with ``GET /api/v1/events``.
- **At least once.** An event can arrive twice (see :mod:`app.events.sse`); clients drop an
  ``id`` they have seen.
- **Gaps.** Lists and replay follow ``(occurred_at, id)``. An event whose transaction
  commits after a later one was read (a long transaction of another source) carries the
  earlier time and is missed by a page or replay that has passed that time; the live stream
  still sends it.
- **Credentials.** The stream holds no database connection while it runs: credentials are
  checked in short sessions of their own, at the start and every ``sse.REAUTH_SECONDS``. A
  check runs when a message or a heartbeat is due, so a revoked token or session ends its
  streams within about ``sse.REAUTH_SECONDS + sse.HEARTBEAT_SECONDS``.
- **Ends.** Before the server ends a stream it sends a comment naming the reason
  (``END_UNAUTHORIZED``, ``END_TOO_SLOW``, ``END_REPLAY_CONTINUES``).
- **Limits.** At most ``sse.MAX_CONNECTIONS`` streams per process and
  ``sse.MAX_CONNECTIONS_PER_PRINCIPAL`` per token or browser session; beyond that 429. A
  ``HEAD`` request gets the headers only and takes no slot.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.background import BackgroundTask

from app.api.errors import ApiError
from app.api.pagination import (
    DEFAULT_LIMIT,
    CursorQuery,
    FromQuery,
    LimitQuery,
    ToQuery,
    check_range,
    decode_cursor,
    encode_cursor,
)
from app.auth.dependencies import AuthContext, reauthenticate, require_scope
from app.db.session import connected, get_session
from app.events import sse
from app.events.service import MAX_EVENT_TYPE_LENGTH
from app.repositories import event_log
from app.schemas.events import DeliveryView, EventDetail, EventPage, EventView, StreamEvent
from app.schemas.problem import ProblemDetail
from app.web.head import HEAD_SCOPE_KEY

router = APIRouter(prefix="/api/v1", tags=["events"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_scope("read"))]
StreamReadDep = Annotated[AuthContext, Depends(require_scope("read", own_session=True))]

# Events replayed after ``Last-Event-ID`` before the stream goes live.
REPLAY_LIMIT = 1000
# The comment a stream sends before the server ends it, naming the reason.
END_UNAUTHORIZED = "end: credentials no longer valid"
END_TOO_SLOW = "end: client too slow"
END_REPLAY_CONTINUES = "end: replay continues"
# The message telling a client that its Last-Event-ID cannot be resumed from.
RESET_MESSAGE = "event: reset\ndata: {}\n\n"

_BASE: dict[int | str, dict[str, Any]] = {
    code: {"model": ProblemDetail} for code in (401, 403, 429, 503)
}
_LIST_PROBLEMS = {**_BASE, 422: {"model": ProblemDetail}}


def _event_view(row: event_log.EventRow) -> EventView:
    return EventView(
        **sse.stream_event(row.event).model_dump(),
        delivery_status=row.delivery_status,  # type: ignore[arg-type]
    )


def _principal(auth: AuthContext) -> sse.Principal:
    """Whose stream budget a connection counts against: its browser session or its token."""
    if auth.kind == "session" and auth.session_id is not None:
        return ("session", auth.session_id)
    if auth.key_id is not None:
        return ("key", auth.key_id)
    raise ApiError(403, "insufficient_scope", "Insufficient scope")  # pragma: no cover


def _not_found() -> ApiError:
    return ApiError(404, "event_not_found", "Event not found")


@router.get(
    "/events",
    summary="List events",
    response_model=EventPage,
    responses=_LIST_PROBLEMS,
)
async def list_events(
    session: SessionDep,
    _auth: ReadDep,
    start: FromQuery = None,
    end: ToQuery = None,
    source: Annotated[uuid.UUID | None, Query(description="Source provider instance")] = None,
    type: Annotated[  # noqa: A002  # the query parameter
        str | None, Query(max_length=MAX_EVENT_TYPE_LENGTH, description="Exact event type")
    ] = None,
    status: Annotated[
        Literal["pending", "done", "failed"] | None,
        Query(description="Delivery state over all subscribers (see EventView)"),
    ] = None,
    cursor: CursorQuery = None,
    limit: LimitQuery = DEFAULT_LIMIT,
) -> EventPage:
    start_utc, end_utc = check_range(start, end)
    key = decode_cursor(cursor) if cursor is not None else None
    rows = await event_log.list_events(
        session,
        start=start_utc,
        end=end_utc,
        source=source,
        type=type,
        status=status,
        cursor=key,
        limit=limit,
    )
    page = rows[:limit]
    next_cursor = (
        encode_cursor(page[-1].event.occurred_at, page[-1].event.id) if len(rows) > limit else None
    )
    return EventPage(items=[_event_view(row) for row in page], next_cursor=next_cursor)


@dataclass(frozen=True)
class Replay:
    events: list[StreamEvent]
    # The id could not be resumed from: send ``event: reset`` first.
    reset: bool = False
    # More than ``REPLAY_LIMIT`` were waiting: end after the batch.
    more: bool = False


async def _replay(factory: async_sessionmaker[AsyncSession], last_event_id: str | None) -> Replay:
    if not last_event_id:
        return Replay(events=[])
    try:
        anchor = uuid.UUID(last_event_id.strip())
    except ValueError:
        return Replay(events=[], reset=True)  # not one of our ids
    limit = REPLAY_LIMIT
    async with factory() as session:
        await connected(session)
        events = await event_log.events_after(session, anchor, limit + 1)
    if events is None:
        return Replay(events=[], reset=True)  # unknown, or removed by retention
    return Replay(
        events=[sse.stream_event(event) for event in events[:limit]], more=len(events) > limit
    )


async def _messages(
    request: Request,
    hub: sse.SseHub,
    subscription: sse.Subscription,
    replay: Replay,
) -> AsyncIterator[str]:
    try:
        yield ": connected\n\n"
        if replay.reset:
            yield RESET_MESSAGE
        sent: set[uuid.UUID] = set()
        for event in replay.events:
            sent.add(event.id)
            yield sse.format_event(event)
        if replay.more:
            # The browser reconnects with the last id it got and gets the next batch.
            yield f": {END_REPLAY_CONTINUES}\n\n"
            return
        checked = time.monotonic()
        while True:
            arrived = await subscription.wait(sse.HEARTBEAT_SECONDS)
            if subscription.overflowed:
                # Too far behind: the client resumes with Last-Event-ID.
                yield f": {END_TOO_SLOW}\n\n"
                return
            if time.monotonic() - checked >= sse.REAUTH_SECONDS:
                try:
                    await reauthenticate(request, "read")
                except ApiError:
                    yield f": {END_UNAUTHORIZED}\n\n"
                    return
                checked = time.monotonic()
            if not arrived:
                yield ": heartbeat\n\n"
                continue
            for event in subscription.drain():
                # Replayed and live can overlap for events written while the stream opened.
                if event.id in sent:
                    continue
                yield sse.format_event(event)
    finally:
        hub.close(subscription)


@router.get(
    "/events/stream",
    summary="Stream events (server-sent events)",
    response_class=StreamingResponse,
    responses={
        **_BASE,
        200: {
            "description": "A ``text/event-stream`` of events",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        },
    },
)
async def stream_events(
    request: Request,
    auth: StreamReadDep,
    last_event_id: Annotated[
        str | None,
        Header(
            alias="Last-Event-ID",
            max_length=200,
            description="Resume after this event id (sent by the browser on reconnect)",
        ),
    ] = None,
) -> Response:
    headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    if request.scope.get(HEAD_SCOPE_KEY):
        # The headers of the stream, without a stream: a HEAD client must not hold a slot.
        return Response(media_type="text/event-stream", headers=headers)
    hub: sse.SseHub = request.app.state.sse_hub
    try:
        subscription = hub.open(_principal(auth))
    except sse.ConnectionLimitError:
        raise ApiError(
            429,
            "too_many_streams",
            "Too many open streams",
            detail="Try again later.",
            headers={"Retry-After": "5"},
        ) from None
    try:
        replay = await _replay(request.app.state.session_factory, last_event_id)
    except BaseException:
        hub.close(subscription)
        raise
    return StreamingResponse(
        _messages(request, hub, subscription, replay),
        media_type="text/event-stream",
        headers=headers,
        # Also when the body never started (the client left at once): free the slot.
        background=BackgroundTask(hub.close, subscription),
    )


@router.get(
    "/events/{event_id}",
    summary="Get an event with its deliveries",
    response_model=EventDetail,
    responses={**_BASE, 404: {"model": ProblemDetail}},
)
async def get_event(event_id: uuid.UUID, session: SessionDep, _auth: ReadDep) -> EventDetail:
    row = await event_log.get_event(session, event_id)
    if row is None:
        raise _not_found()
    deliveries = await event_log.deliveries_of(session, row.event)
    return EventDetail(
        **_event_view(row).model_dump(),
        deliveries=[
            DeliveryView(
                subscriber=d.subscriber,
                status=d.status,  # type: ignore[arg-type]
                attempts=d.attempts,
                last_error=d.last_error,
            )
            for d in deliveries
        ],
    )
