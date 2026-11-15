"""``GET /api/v1/events/stream``: live delivery, resume, heartbeat, limits, credentials.

``httpx.ASGITransport`` collects a whole response before it returns it, so a stream that
never ends cannot be read through it. These tests run the app in a real uvicorn server on a
loopback port (without the lifespan; the fixture starts the SSE pump itself).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.routes import events as events_routes
from app.events import sse
from app.models.api_key import ApiKey
from app.models.event import Event
from app.models.event_delivery import EventDelivery
from app.schemas.events import StreamEvent
from tests.conftest import KEY_HEADER, issue_token
from tests.integration.events.conftest import (  # noqa: F401  (fixtures)
    SOURCE_A,
    current_partitions,
    sessions,
)

STREAM_URL = "/api/v1/events/stream"
# Generous: a loaded CI runner can be slow; the 2 s promise is checked by measurement.
STEP_TIMEOUT = 15.0


@pytest_asyncio.fixture
async def server(app: FastAPI) -> AsyncIterator[str]:
    """The app on a free loopback port, with the SSE pump running; yields the base URL."""
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        lifespan="off",
        log_level="warning",
        timeout_graceful_shutdown=2,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(STEP_TIMEOUT):
        while not server.started:
            await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    await app.state.sse_hub.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await app.state.sse_hub.stop()
        server.should_exit = True
        await asyncio.wait_for(task, STEP_TIMEOUT)


class Stream:
    """Reads SSE messages (and comment lines) from an open response."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self._lines = response.aiter_lines()

    async def next_block(self) -> list[str]:
        """The lines of the next message or comment, up to the blank line."""
        lines: list[str] = []
        async with asyncio.timeout(STEP_TIMEOUT):
            async for line in self._lines:
                if line == "":
                    if lines:
                        return lines
                    continue
                lines.append(line)
        raise EOFError("stream ended")

    async def until_end(self) -> list[list[str]]:
        """Every block up to the end of the stream; ``TimeoutError`` if it does not end.

        One deadline for the whole read: heartbeats keep a stream that never ends busy, so a
        per-block timeout would never fire.
        """
        blocks: list[list[str]] = []
        async with asyncio.timeout(STEP_TIMEOUT):
            while True:
                try:
                    blocks.append(await self.next_block())
                except EOFError:
                    return blocks

    async def next_event(self) -> dict[str, Any]:
        """The next event message, skipping comments; its ``id`` line must match the data."""
        while True:
            block = await self.next_block()
            if block[0].startswith(":"):
                continue
            fields = dict(line.split(": ", 1) for line in block)
            data: dict[str, Any] = json.loads(fields["data"])
            assert fields["id"] == data["id"]
            return data


@contextlib.asynccontextmanager
async def open_stream(
    base_url: str, token: str, headers: dict[str, str] | None = None
) -> AsyncIterator[Stream]:
    async with (
        httpx.AsyncClient(base_url=base_url, timeout=STEP_TIMEOUT) as client,
        client.stream(
            "GET", STREAM_URL, headers={KEY_HEADER: token, **(headers or {})}
        ) as response,
    ):
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith("text/event-stream")
        stream = Stream(response)
        assert await stream.next_block() == [": connected"]
        yield stream


async def _emit(
    app: FastAPI,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    n: int = 0,
) -> uuid.UUID:
    async with sessions() as session:
        event_id = await app.state.event_service.emit(
            session,
            type="integration.demo.tick",
            source_instance_id=SOURCE_A,
            payload={"n": n},
            schema_version=1,
        )
        await session.commit()
    assert event_id is not None
    return event_id


async def _sse_status(
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    event_id: uuid.UUID,
) -> str:
    async with sessions() as session:
        status = await session.scalar(
            select(EventDelivery.status).where(
                EventDelivery.event_id == event_id, EventDelivery.subscriber == "sse"
            )
        )
    return str(status)


async def _occurred_at(
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    event_id: uuid.UUID,
) -> datetime:
    async with sessions() as session:
        when = await session.scalar(select(Event.occurred_at).where(Event.id == event_id))
    assert when is not None
    return when


async def _until(predicate: Any) -> None:
    async with asyncio.timeout(STEP_TIMEOUT):
        while not await predicate():
            await asyncio.sleep(0.05)


async def test_stream_delivers_new_event_within_2s(
    app: FastAPI,
    server: str,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    async with open_stream(server, read_token) as stream:
        started = time.monotonic()
        event_id = await _emit(app, sessions, n=7)
        event = await stream.next_event()
        elapsed = time.monotonic() - started
    assert event["id"] == str(event_id)
    assert event["type"] == "integration.demo.tick"
    assert event["payload"] == {"n": 7}
    assert event["source_instance_id"] == str(SOURCE_A)
    assert elapsed < 2.0, f"took {elapsed:.2f} s"

    async def completed() -> bool:
        return await _sse_status(sessions, event_id) == "done"

    await _until(completed)


async def test_stream_resumes_after_last_event_id(
    app: FastAPI,
    server: str,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    first, second, third = [await _emit(app, sessions, n=i) for i in range(3)]

    async def all_completed() -> bool:
        return all([await _sse_status(sessions, e) == "done" for e in (first, second, third)])

    # The pump has handed them out (to nobody) before the client comes back.
    await _until(all_completed)
    async with open_stream(server, read_token, {"Last-Event-ID": str(first)}) as stream:
        assert (await stream.next_event())["id"] == str(second)
        assert (await stream.next_event())["id"] == str(third)
        # A replayed event that the pump hands out again (written while the stream opened,
        # or a delivery whose completion was lost) is not sent twice.
        async with sessions() as session:
            again = await session.get(Event, (third, await _occurred_at(sessions, third)))
            assert again is not None
            app.state.sse_hub.broadcast([sse.stream_event(again)])
        live = await _emit(app, sessions, n=9)
        assert (await stream.next_event())["id"] == str(live)


async def test_stream_unknown_last_event_id_signals_reset(
    app: FastAPI,
    server: str,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    earlier = await _emit(app, sessions, n=1)

    async def completed() -> bool:
        return await _sse_status(sessions, earlier) == "done"

    await _until(completed)  # handed out before the client comes, so it is not live
    # An id that never existed (or was removed by retention), and one that is not an id.
    for value in (str(uuid.uuid4()), "not-an-id"):
        async with open_stream(server, read_token, {"Last-Event-ID": value}) as stream:
            # The client cannot resume: it is told to load the list again, then it is live.
            assert await stream.next_block() == ["event: reset", "data: {}"]
            live = await _emit(app, sessions, n=2)
            assert (await stream.next_event())["id"] == str(live)


async def test_stream_known_last_event_id_sends_no_reset(
    app: FastAPI,
    server: str,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    anchor = await _emit(app, sessions, n=1)

    async def completed() -> bool:
        return await _sse_status(sessions, anchor) == "done"

    await _until(completed)
    async with open_stream(server, read_token, {"Last-Event-ID": str(anchor)}) as stream:
        live = await _emit(app, sessions, n=2)
        block = await stream.next_block()
        assert block[0] == f"id: {live}", block


async def test_stream_replay_beyond_limit_continues_on_reconnect(
    app: FastAPI,
    server: str,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(events_routes, "REPLAY_LIMIT", 2)
    anchor = await _emit(app, sessions, n=0)
    later = [await _emit(app, sessions, n=i) for i in range(1, 6)]

    async def all_completed() -> bool:
        return all([await _sse_status(sessions, e) == "done" for e in (anchor, *later)])

    await _until(all_completed)
    last = anchor
    for expected in (later[0:2], later[2:4]):
        async with open_stream(server, read_token, {"Last-Event-ID": str(last)}) as stream:
            got = [(await stream.next_event())["id"] for _ in expected]
            assert got == [str(e) for e in expected]
            # More are waiting: the stream ends instead of going live, and the browser
            # reconnects with the last id it got.
            assert await stream.until_end() == [[f": {events_routes.END_REPLAY_CONTINUES}"]]
        last = expected[-1]
    # The rest fits into one batch: sent, then live.
    async with open_stream(server, read_token, {"Last-Event-ID": str(last)}) as stream:
        assert (await stream.next_event())["id"] == str(later[4])
        live = await _emit(app, sessions, n=9)
        assert (await stream.next_event())["id"] == str(live)


async def test_stream_sends_heartbeat(
    server: str, read_token: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sse, "HEARTBEAT_SECONDS", 0.2)
    async with open_stream(server, read_token) as stream:
        assert await stream.next_block() == [": heartbeat"]
        assert await stream.next_block() == [": heartbeat"]


async def test_stream_limit_answers_429_and_frees_the_slot(
    app: FastAPI, server: str, read_token: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sse, "MAX_CONNECTIONS", 2)
    hub: sse.SseHub = app.state.sse_hub
    async with httpx.AsyncClient(base_url=server, timeout=STEP_TIMEOUT) as client:
        async with open_stream(server, read_token), open_stream(server, read_token):
            assert hub.connection_count == 2
            r = await client.get(STREAM_URL, headers={KEY_HEADER: read_token})
            assert r.status_code == 429, r.text
            assert r.json()["error_code"] == "too_many_streams"
            assert r.headers["retry-after"] == "5"

        async def freed() -> bool:
            return hub.connection_count == 0

        await _until(freed)
        async with open_stream(server, read_token):
            assert hub.connection_count == 1


async def test_stream_holds_no_database_connection(app: FastAPI, server: str, read_token: str):
    # Three open streams; the pump borrows a connection now and then, nothing else may.
    pool = app.state.engine.pool
    async with (
        open_stream(server, read_token),
        open_stream(server, read_token),
        open_stream(server, read_token),
    ):
        samples = []
        for _ in range(20):
            samples.append(pool.checkedout())
            await asyncio.sleep(0.02)
    assert max(samples) <= 1, samples


async def test_stream_needs_read_scope(server: str):
    async with httpx.AsyncClient(base_url=server, timeout=STEP_TIMEOUT) as client:
        r = await client.get(STREAM_URL)
        assert r.status_code == 401
        assert r.json()["error_code"] == "not_authenticated"
        r = await client.get(STREAM_URL, headers={KEY_HEADER: "bb_pat_" + "x" * 40})
        assert r.status_code == 401


async def test_stream_ends_when_the_token_is_disabled(
    engine: AsyncEngine,
    server: str,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(sse, "HEARTBEAT_SECONDS", 0.1)
    monkeypatch.setattr(sse, "REAUTH_SECONDS", 0.2)
    async with open_stream(server, read_token) as stream:
        assert await stream.next_block() == [": heartbeat"]
        async with sessions() as session:
            await session.execute(update(ApiKey).values(enabled=False))
            await session.commit()
        blocks = await stream.until_end()
    # Ended by the re-check (and for that reason), not by a timeout or another layer.
    assert blocks[-1] == [f": {events_routes.END_UNAUTHORIZED}"], blocks[-3:]


async def test_stream_keeps_running_while_the_token_is_valid(
    server: str, read_token: str, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sse, "HEARTBEAT_SECONDS", 0.1)
    monkeypatch.setattr(sse, "REAUTH_SECONDS", 0.2)
    async with open_stream(server, read_token) as stream:
        started = time.monotonic()
        # Several re-checks pass: the stream stays open and keeps sending heartbeats.
        while time.monotonic() - started < 1.0:
            assert await stream.next_block() == [": heartbeat"]


async def test_slow_connection_is_ended(
    app: FastAPI,
    server: str,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
):
    hub: sse.SseHub = app.state.sse_hub
    async with open_stream(server, read_token) as stream:
        monkeypatch.setattr(sse, "QUEUE_SIZE", 2)
        # More events than the buffer holds, handed over before the connection reads them.
        hub.broadcast(
            StreamEvent(
                id=uuid.uuid4(),
                occurred_at=datetime.now(UTC),
                type="integration.demo.tick",
                source_instance_id=None,
                schema_version=1,
                correlation_id=None,
                payload={},
            )
            for _ in range(3)
        )
        assert hub.connection_count == 0
        blocks = await stream.until_end()
    assert blocks == [[f": {events_routes.END_TOO_SLOW}"]]


async def test_pump_completes_deliveries_without_connections(
    app: FastAPI,
    server: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    event_id = await _emit(app, sessions)

    async def completed() -> bool:
        return await _sse_status(sessions, event_id) == "done"

    await _until(completed)


async def test_pump_keeps_running_after_a_database_error(
    app: FastAPI,
    server: str,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    monkeypatch.setattr(sse, "ERROR_BACKOFF_SECONDS", 0.05)
    real_claim = sse.outbox.claim
    failures = 0

    async def flaky_claim(*args: Any, **kwargs: Any) -> Any:
        nonlocal failures
        if failures < 2:
            failures += 1
            raise OSError("connection refused")
        return await real_claim(*args, **kwargs)

    monkeypatch.setattr(sse.outbox, "claim", flaky_claim)
    async with open_stream(server, read_token) as stream:
        event_id = await _emit(app, sessions, n=3)
        assert (await stream.next_event())["id"] == str(event_id)
    assert failures == 2
    assert "sse pump failed (OSError); retrying" in caplog.text


async def test_stream_limit_per_principal(
    app: FastAPI,
    engine: AsyncEngine,
    server: str,
    read_token: str,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(sse, "MAX_CONNECTIONS_PER_PRINCIPAL", 1)
    other_token = await issue_token(engine, "read", name="second reader")
    hub: sse.SseHub = app.state.sse_hub
    async with httpx.AsyncClient(base_url=server, timeout=STEP_TIMEOUT) as client:
        async with open_stream(server, read_token):
            r = await client.get(STREAM_URL, headers={KEY_HEADER: read_token})
            assert r.status_code == 429, r.text
            assert r.json()["error_code"] == "too_many_streams"
            assert r.headers["retry-after"] == "5"
            # Another token is another principal: its own budget.
            async with open_stream(server, other_token):
                assert hub.connection_count == 2

        async def freed() -> bool:
            return hub.connection_count == 0

        await _until(freed)
        # The slot of the first token is back.
        async with open_stream(server, read_token):
            assert hub.connection_count == 1


def test_hub_counts_a_principal_once_per_close(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sse, "MAX_CONNECTIONS_PER_PRINCIPAL", 2)
    hub = sse.SseHub(None)  # type: ignore[arg-type]  # no database needed here
    principal = ("key", uuid.uuid4())
    first = hub.open(principal)
    second = hub.open(principal)
    with pytest.raises(sse.ConnectionLimitError):
        hub.open(principal)
    # Closed twice (generator end and background task) while ``second`` is still open: the
    # caller has one free slot, not two.
    hub.close(first)
    hub.close(first)
    third = hub.open(principal)
    with pytest.raises(sse.ConnectionLimitError):
        hub.open(principal)
    hub.close(second)
    hub.close(third)
    assert hub.connection_count == 0


async def test_head_stream_does_not_hold_a_slot(app: FastAPI, server: str, read_token: str):
    hub: sse.SseHub = app.state.sse_hub
    async with httpx.AsyncClient(base_url=server, timeout=5.0) as client:
        r = await client.head(STREAM_URL, headers={KEY_HEADER: read_token})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.content == b""
        assert hub.connection_count == 0
        # HEAD still needs credentials, like GET.
        assert (await client.head(STREAM_URL)).status_code == 401
