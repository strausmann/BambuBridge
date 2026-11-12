"""Request body size limit: oversize bodies are refused with 413 before any handler runs."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from starlette.responses import PlainTextResponse
from starlette.types import Receive, Scope, Send

from app.auth import csrf
from app.config import Settings
from app.main import create_app
from app.web import body_limit
from app.web.body_limit import MAX_REQUEST_BODY_BYTES

SESSION_URL = "/api/v1/auth/session"


@pytest.fixture
def handler_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records every call of the sign-in handler's first statement (the Origin check)."""
    calls: list[str] = []
    original = csrf.check_origin

    def spy(*args: object, **kwargs: object) -> None:
        calls.append("check_origin")
        original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(csrf, "check_origin", spy)
    return calls


def _assert_413(r: httpx.Response) -> None:
    assert r.status_code == 413, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["error_code"] == "payload_too_large"


async def test_oversize_content_length_is_413_before_the_handler(
    client: httpx.AsyncClient, handler_calls: list[str]
):
    body = b'{"token":"' + b"A" * MAX_REQUEST_BODY_BYTES + b'"}'
    r = await client.post(SESSION_URL, content=body, headers={"Content-Type": "application/json"})
    _assert_413(r)
    assert handler_calls == []
    # Security headers still apply to the refusal.
    assert "content-security-policy" in r.headers


async def test_oversize_streamed_body_is_413_before_the_handler(
    client: httpx.AsyncClient, handler_calls: list[str]
):
    sent = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal sent
        for _ in range(64):
            sent += 1
            yield b"A" * 4096

    r = await client.post(
        SESSION_URL, content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert "content-length" not in r.request.headers
    _assert_413(r)
    assert handler_calls == []


async def test_body_at_the_limit_reaches_the_handler(
    client: httpx.AsyncClient, handler_calls: list[str]
):
    filler = MAX_REQUEST_BODY_BYTES - len(b'{"token":""}')
    body = b'{"token":"' + b"A" * filler + b'"}'
    assert len(body) == MAX_REQUEST_BODY_BYTES
    r = await client.post(SESSION_URL, content=body, headers={"Content-Type": "application/json"})
    # Not 413: the body is parsed and validated (too long a token) by the normal path.
    assert r.status_code == 422, r.text


async def test_normal_requests_are_unaffected(client: httpx.AsyncClient):
    r = await client.post(SESSION_URL, json={"token": "bb_pat_" + "A" * 40})
    assert r.status_code == 403  # no Origin: refused by the handler, not by the limit
    assert (await client.get("/api/v1/info")).status_code == 200


def test_the_limit_is_64_kib():
    assert body_limit.MAX_REQUEST_BODY_BYTES == 64 * 1024


async def test_body_read_outside_a_route_is_413_too():
    # An ASGI app that reads the body itself (no FastAPI body parsing to catch the error).
    seen: list[bytes] = []

    async def reader(scope: Scope, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            seen.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        await PlainTextResponse("read")(scope, receive, send)

    limited = body_limit.BodySizeLimitMiddleware(reader, max_bytes=8)
    transport = httpx.ASGITransport(app=limited)

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(4):
            yield b"12345"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        _assert_413(await c.post("/", content=chunks()))
        assert sum(map(len, seen)) <= 8  # the crossing chunk was never handed on
        ok = await c.post("/", content=b"1234")
        assert ok.status_code == 200
        assert ok.text == "read"


async def _oversize_chunks() -> AsyncIterator[bytes]:
    for _ in range(20):
        yield b"A" * 4096


@pytest.mark.parametrize("path", ["/", "/robots.txt", "/healthz"])
async def test_oversize_streamed_body_to_a_route_that_ignores_bodies_is_413(
    settings: Settings,
    tmp_path: Path,
    engine: object,
    caplog: pytest.LogCaptureFixture,
    path: str,
):
    # Static files and /healthz never read the body; the limit must hold all the same, as a
    # clean 413 and not as a cut-off 200 with a logged traceback.
    (tmp_path / "index.html").write_text("<!doctype html><title>shell</title>")
    (tmp_path / "robots.txt").write_text("User-agent: *")
    application = create_app(settings, web_dist_dir=tmp_path)
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    try:
        with caplog.at_level(logging.ERROR):
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                r = await c.request("GET", path, content=_oversize_chunks())
    finally:
        await application.state.engine.dispose()
    _assert_413(r)
    assert "content-security-policy" in r.headers
    assert [rec for rec in caplog.records if rec.levelno >= logging.ERROR] == []


async def test_a_client_gone_while_the_body_is_read_never_reaches_the_app():
    calls: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append("app")

    messages = [
        {"type": "http.request", "body": b"12", "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> dict[str, object]:
        return messages.pop(0)

    async def send(message: object) -> None:
        calls.append("send")

    limited = body_limit.BodySizeLimitMiddleware(app, max_bytes=8)
    await limited({"type": "http", "method": "POST", "headers": []}, receive, send)  # type: ignore[arg-type]
    assert calls == []
