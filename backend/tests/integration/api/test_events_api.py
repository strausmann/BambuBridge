"""``/api/v1/events`` and ``/api/v1/communication``: filters, paging, scopes, masking."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.events import outbox
from app.events.communication import CommunicationRecorder, Message
from app.models.event_delivery import EventDelivery
from app.repositories import event_log
from app.repositories import events as events_repo
from tests.conftest import KEY_HEADER
from tests.integration.events.conftest import (  # noqa: F401  (fixtures)
    SOURCE_A,
    SOURCE_B,
    current_partitions,
    sessions,
)

EVENTS_URL = "/api/v1/events"
COMMUNICATION_URL = "/api/v1/communication"
TYPE_TICK = "integration.demo.tick"
TYPE_TOCK = "integration.demo.tock"
INSTANCE = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
OTHER_INSTANCE = uuid.UUID("00000000-0000-4000-8000-0000000000c2")
# Obviously fake value, readable text only.
SECRET = "fake-access-code-0001"


def _problem(r: httpx.Response, status: int, error_code: str | None = None) -> dict[str, Any]:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    if error_code is not None:
        assert body["error_code"] == error_code
    return body


async def _emit(
    app: FastAPI,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    *,
    type: str = TYPE_TICK,  # noqa: A002
    source: uuid.UUID | None = SOURCE_A,
    n: int = 0,
) -> uuid.UUID:
    async with sessions() as session:
        event_id = await app.state.event_service.emit(
            session, type=type, source_instance_id=source, payload={"n": n}, schema_version=1
        )
        await session.commit()
    assert event_id is not None
    return event_id


async def _occurred_at(client: httpx.AsyncClient, token: str, event_id: uuid.UUID) -> datetime:
    r = await client.get(f"{EVENTS_URL}/{event_id}", headers={KEY_HEADER: token})
    assert r.status_code == 200, r.text
    return datetime.fromisoformat(r.json()["occurred_at"])


def _ids(r: httpx.Response) -> list[str]:
    assert r.status_code == 200, r.text
    return [item["id"] for item in r.json()["items"]]


async def _set_delivery(
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    event_id: uuid.UUID,
    status: str,
    subscriber: str = "sse",
) -> None:
    async with sessions() as session:
        await session.execute(
            update(EventDelivery)
            .where(EventDelivery.event_id == event_id, EventDelivery.subscriber == subscriber)
            .values(status=status)
        )
        await session.commit()


async def _add_delivery(
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    client: httpx.AsyncClient,
    token: str,
    event_id: uuid.UUID,
    subscriber: str,
) -> None:
    occurred_at = await _occurred_at(client, token, event_id)
    async with sessions() as session:
        await events_repo.insert_deliveries(
            session, event_id=event_id, event_occurred_at=occurred_at, subscribers=[subscriber]
        )
        await session.commit()


# --- events -------------------------------------------------------------------------------


async def test_filter_by_type_source_and_range(
    app: FastAPI,
    client: httpx.AsyncClient,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    a_tick = await _emit(app, sessions, type=TYPE_TICK, source=SOURCE_A)
    b_tick = await _emit(app, sessions, type=TYPE_TICK, source=SOURCE_B)
    a_tock = await _emit(app, sessions, type=TYPE_TOCK, source=SOURCE_A)
    late = await _emit(app, sessions, type=TYPE_TICK, source=SOURCE_A)
    headers = {KEY_HEADER: read_token}

    assert _ids(await client.get(EVENTS_URL, headers=headers)) == [
        str(late),
        str(a_tock),
        str(b_tick),
        str(a_tick),
    ]
    by_type = await client.get(EVENTS_URL, params={"type": TYPE_TOCK}, headers=headers)
    assert _ids(by_type) == [str(a_tock)]
    by_source = await client.get(EVENTS_URL, params={"source": str(SOURCE_B)}, headers=headers)
    assert _ids(by_source) == [str(b_tick)]
    both = await client.get(
        EVENTS_URL, params={"type": TYPE_TICK, "source": str(SOURCE_A)}, headers=headers
    )
    assert _ids(both) == [str(late), str(a_tick)]

    # ``from`` inclusive, ``to`` exclusive; the bounds may come in any zone.
    start = await _occurred_at(client, read_token, b_tick)
    end = await _occurred_at(client, read_token, late)
    plus_two = start.astimezone(timezone(timedelta(hours=2)))
    in_range = await client.get(
        EVENTS_URL,
        params={"from": plus_two.isoformat(), "to": end.isoformat()},
        headers=headers,
    )
    assert _ids(in_range) == [str(a_tock), str(b_tick)]

    body = (await client.get(EVENTS_URL, params={"type": TYPE_TOCK}, headers=headers)).json()
    item = body["items"][0]
    assert item["source_instance_id"] == str(SOURCE_A)
    assert item["payload"] == {"n": 0}
    assert item["schema_version"] == 1
    assert item["delivery_status"] == "pending"
    assert datetime.fromisoformat(item["occurred_at"]).utcoffset() == timedelta(0)
    assert body["next_cursor"] is None


async def test_filter_by_delivery_status(
    app: FastAPI,
    client: httpx.AsyncClient,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    headers = {KEY_HEADER: read_token}
    done = await _emit(app, sessions, n=1)
    pending = await _emit(app, sessions, n=2)
    failed = await _emit(app, sessions, n=3)
    # Two subscribers: one done, one pending -> pending.
    mixed_pending = await _emit(app, sessions, n=4)
    # One failed, one pending -> failed wins.
    mixed_failed = await _emit(app, sessions, n=5)
    await _set_delivery(sessions, done, "done")
    await _set_delivery(sessions, failed, "failed")
    await _add_delivery(sessions, client, read_token, mixed_pending, "rules")
    await _set_delivery(sessions, mixed_pending, "done")
    await _add_delivery(sessions, client, read_token, mixed_failed, "rules")
    await _set_delivery(sessions, mixed_failed, "failed", subscriber="rules")

    def query(status: str) -> dict[str, str]:
        return {"status": status}

    assert _ids(await client.get(EVENTS_URL, params=query("done"), headers=headers)) == [str(done)]
    assert _ids(await client.get(EVENTS_URL, params=query("pending"), headers=headers)) == [
        str(mixed_pending),
        str(pending),
    ]
    assert _ids(await client.get(EVENTS_URL, params=query("failed"), headers=headers)) == [
        str(mixed_failed),
        str(failed),
    ]
    listed = (await client.get(EVENTS_URL, headers=headers)).json()["items"]
    assert {item["id"]: item["delivery_status"] for item in listed} == {
        str(done): "done",
        str(pending): "pending",
        str(failed): "failed",
        str(mixed_pending): "pending",
        str(mixed_failed): "failed",
    }
    detail = (await client.get(f"{EVENTS_URL}/{mixed_failed}", headers=headers)).json()
    assert detail["delivery_status"] == "failed"
    assert [(d["subscriber"], d["status"]) for d in detail["deliveries"]] == [
        ("rules", "failed"),
        ("sse", "pending"),
    ]
    r = await client.get(EVENTS_URL, params=query("lost"), headers=headers)
    _problem(r, 422)


async def test_cursor_pagination_stable_under_inserts(
    app: FastAPI,
    client: httpx.AsyncClient,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    headers = {KEY_HEADER: read_token}
    first = [await _emit(app, sessions, n=i) for i in range(5)]
    expected = [str(event_id) for event_id in reversed(first)]

    page1 = await client.get(EVENTS_URL, params={"limit": 2}, headers=headers)
    assert _ids(page1) == expected[:2]
    cursor = page1.json()["next_cursor"]
    assert cursor
    # New events while paging: they are newer than the cursor and never shift a later page.
    newer = [await _emit(app, sessions, n=10 + i) for i in range(3)]

    page2 = await client.get(EVENTS_URL, params={"limit": 2, "cursor": cursor}, headers=headers)
    assert _ids(page2) == expected[2:4]
    page3 = await client.get(
        EVENTS_URL, params={"limit": 2, "cursor": page2.json()["next_cursor"]}, headers=headers
    )
    assert _ids(page3) == expected[4:]
    assert page3.json()["next_cursor"] is None

    # Exactly ``limit`` rows left: no further page is announced.
    full = await client.get(EVENTS_URL, params={"limit": 8}, headers=headers)
    assert _ids(full) == [str(e) for e in reversed(newer)] + expected
    assert full.json()["next_cursor"] is None


async def test_naive_datetime_rejected_422(client: httpx.AsyncClient, read_token: str):
    headers = {KEY_HEADER: read_token}
    for name in ("from", "to"):
        r = await client.get(EVENTS_URL, params={name: "2026-11-13T10:00:00"}, headers=headers)
        _problem(r, 422)
    r = await client.get(COMMUNICATION_URL, params={"from": "2026-11-13T10:00:00"}, headers=headers)
    assert r.status_code in (403, 422)  # a read token is stopped by the scope first
    ok = await client.get(EVENTS_URL, params={"from": "2026-11-13T10:00:00+01:00"}, headers=headers)
    assert ok.status_code == 200, ok.text


async def test_range_from_not_before_to_422(client: httpx.AsyncClient, read_token: str):
    when = "2026-11-13T10:00:00+00:00"
    r = await client.get(
        EVENTS_URL, params={"from": when, "to": when}, headers={KEY_HEADER: read_token}
    )
    _problem(r, 422, "invalid_range")


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!",
        base64.urlsafe_b64encode(b"no separator").decode(),
        base64.urlsafe_b64encode(b"2026-11-13T10:00:00|not-a-uuid").decode(),
        # A time without a zone is not one of ours either.
        base64.urlsafe_b64encode(f"2026-11-13T10:00:00|{uuid.uuid4()}".encode()).decode(),
        base64.urlsafe_b64encode(b"\xff\xfe|x").decode(),
        "A" * 201,
    ],
)
async def test_bad_cursor_rejected_422(client: httpx.AsyncClient, read_token: str, cursor: str):
    r = await client.get(EVENTS_URL, params={"cursor": cursor}, headers={KEY_HEADER: read_token})
    body = _problem(r, 422)
    assert body["error_code"] in ("invalid_cursor", "validation_failed")
    assert cursor not in r.text  # the input is never echoed


@pytest.mark.parametrize("limit", ["0", "201", "-1", "x"])
async def test_limit_out_of_range_422(client: httpx.AsyncClient, read_token: str, limit: str):
    r = await client.get(EVENTS_URL, params={"limit": limit}, headers={KEY_HEADER: read_token})
    _problem(r, 422)


async def test_limit_bounds_accepted(client: httpx.AsyncClient, read_token: str):
    for limit in ("1", "200"):
        r = await client.get(EVENTS_URL, params={"limit": limit}, headers={KEY_HEADER: read_token})
        assert r.status_code == 200, r.text


async def test_unknown_event_404(client: httpx.AsyncClient, read_token: str):
    r = await client.get(f"{EVENTS_URL}/{uuid.uuid4()}", headers={KEY_HEADER: read_token})
    _problem(r, 404, "event_not_found")


async def test_events_need_credentials(client: httpx.AsyncClient):
    _problem(await client.get(EVENTS_URL), 401, "not_authenticated")
    _problem(await client.get(f"{EVENTS_URL}/{uuid.uuid4()}"), 401, "not_authenticated")


# --- communication log --------------------------------------------------------------------


async def _record(
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
    *,
    instance: uuid.UUID = INSTANCE,
    status: int | None = 200,
    target: str = "https://printer.example.com/status",
) -> None:
    async with sessions() as session:
        await CommunicationRecorder().record(
            session,
            instance_id=instance,
            method="GET",
            target=target,
            status=status,
            duration_ms=12,
            request=Message(headers={"Authorization": f"Bearer {SECRET}"}, body=SECRET),
            response=Message(body=f'{{"code": "{SECRET}"}}'),
            known_secrets=[SECRET],
        )
        await session.commit()


async def test_communication_requires_admin(
    client: httpx.AsyncClient,
    engine: AsyncEngine,
    read_token: str,
    operate_token: str,
    admin_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    await _record(sessions)
    _problem(await client.get(COMMUNICATION_URL), 401, "not_authenticated")
    for token in (read_token, operate_token):
        r = await client.get(COMMUNICATION_URL, headers={KEY_HEADER: token})
        _problem(r, 403, "insufficient_scope")
        r = await client.get(f"{COMMUNICATION_URL}/{uuid.uuid4()}", headers={KEY_HEADER: token})
        _problem(r, 403, "insufficient_scope")
    r = await client.get(COMMUNICATION_URL, headers={KEY_HEADER: admin_token})
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 1


async def test_communication_returns_the_stored_masked_entry(
    admin_client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    await _record(sessions, target=f"https://printer.example.com/v1?access_token={SECRET}")
    listed = await admin_client.get(COMMUNICATION_URL)
    assert listed.status_code == 200, listed.text
    assert SECRET not in listed.text
    item = listed.json()["items"][0]
    assert "request_body" not in item  # the list carries no bodies or headers
    assert item["instance_id"] == str(INSTANCE)
    assert item["status"] == 200
    detail = await admin_client.get(f"{COMMUNICATION_URL}/{item['id']}")
    assert detail.status_code == 200, detail.text
    assert SECRET not in detail.text
    body = detail.json()
    assert "***" in body["request_body"]
    assert "***" in body["target"]
    assert body["request_headers"]
    assert datetime.fromisoformat(body["occurred_at"]).utcoffset() == timedelta(0)


async def test_communication_filters_and_paging(
    admin_client: httpx.AsyncClient,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    await _record(sessions, status=200)
    await _record(sessions, status=404)
    await _record(sessions, status=503, instance=OTHER_INSTANCE)
    await _record(sessions, status=None)

    async def statuses(**params: str) -> list[int | None]:
        r = await admin_client.get(COMMUNICATION_URL, params=params)
        assert r.status_code == 200, r.text
        return [item["status"] for item in r.json()["items"]]

    assert await statuses() == [None, 503, 404, 200]
    assert await statuses(status="404") == [404]
    assert await statuses(status="4xx") == [404]
    assert await statuses(status="5xx") == [503]
    assert await statuses(status="none") == [None]
    assert await statuses(instance=str(OTHER_INSTANCE)) == [503]
    for bad in ("600", "6xx", "40", "abc"):
        r = await admin_client.get(COMMUNICATION_URL, params={"status": bad})
        _problem(r, 422)

    page1 = await admin_client.get(COMMUNICATION_URL, params={"limit": 3})
    assert [i["status"] for i in page1.json()["items"]] == [None, 503, 404]
    page2 = await admin_client.get(
        COMMUNICATION_URL, params={"limit": 3, "cursor": page1.json()["next_cursor"]}
    )
    assert [i["status"] for i in page2.json()["items"]] == [200]
    assert page2.json()["next_cursor"] is None

    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert await statuses(**{"from": future}) == []
    _problem(await admin_client.get(COMMUNICATION_URL, params={"cursor": "%%"}), 422)


async def test_unknown_communication_entry_404(admin_client: httpx.AsyncClient):
    r = await admin_client.get(f"{COMMUNICATION_URL}/{uuid.uuid4()}")
    _problem(r, 404, "communication_entry_not_found")


async def test_failed_replay_frees_the_stream_slot(
    app: FastAPI, client: httpx.AsyncClient, read_token: str, monkeypatch: pytest.MonkeyPatch
):
    # The replay runs before the response starts; when it fails, the slot must not leak.
    async def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("replay failed")

    monkeypatch.setattr(event_log, "events_after", broken)
    r = await client.get(
        f"{EVENTS_URL}/stream",
        headers={KEY_HEADER: read_token, "Last-Event-ID": str(uuid.uuid4())},
    )
    _problem(r, 500, "internal_error")
    assert app.state.sse_hub.connection_count == 0


async def test_delivery_error_is_masked_for_readers(
    client: httpx.AsyncClient,
    app: FastAPI,
    read_token: str,
    sessions: async_sessionmaker[AsyncSession],  # noqa: F811
):
    # A handler that puts a credential into its failure reason: read scope must not see it.
    event_id = await _emit(app, sessions)
    async with sessions() as session:
        (delivery,) = await outbox.claim(session, "sse", "worker-1")
        await session.commit()
        assert await outbox.fail(
            session, "worker-1", delivery.id, f"upstream refused: password={SECRET} token: {SECRET}"
        )
        await session.commit()
    r = await client.get(f"{EVENTS_URL}/{event_id}", headers={KEY_HEADER: read_token})
    assert r.status_code == 200, r.text
    assert SECRET not in r.text
    (stored,) = r.json()["deliveries"]
    assert stored["last_error"].startswith("upstream refused: password=***")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("from", "0001-01-01T00:00:00+01:00"),
        ("to", "9999-12-31T23:59:59-01:00"),
    ],
)
async def test_time_beyond_the_utc_range_is_422(
    client: httpx.AsyncClient, admin_token: str, name: str, value: str
):
    # In UTC these fall before year 1 or after year 9999: Python cannot represent them.
    for url in (EVENTS_URL, COMMUNICATION_URL):
        r = await client.get(url, params={name: value}, headers={KEY_HEADER: admin_token})
        _problem(r, 422, "invalid_range")


async def test_cursor_beyond_the_utc_range_is_422(client: httpx.AsyncClient, read_token: str):
    cursor = base64.urlsafe_b64encode(f"0001-01-01T00:00:00+01:00|{uuid.uuid4()}".encode())
    r = await client.get(
        EVENTS_URL, params={"cursor": cursor.decode()}, headers={KEY_HEADER: read_token}
    )
    _problem(r, 422, "invalid_cursor")
