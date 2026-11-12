"""``HEAD`` is answered wherever ``GET`` is: same status and headers, no body."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app
from app.web.head import HeadAsGetMiddleware
from tests.conftest import KEY_HEADER

GET_ROUTES = ("/healthz", "/readiness", "/api/v1/info")


@pytest_asyncio.fixture(params=["api-only", "with-ui"])
async def head_app(
    request: pytest.FixtureRequest, settings: Settings, tmp_path: Path, engine: object
) -> AsyncIterator[FastAPI]:
    dist: Path | None = None
    if request.param == "with-ui":
        (tmp_path / "index.html").write_text("<!doctype html><title>shell</title>")
        dist = tmp_path
    application = create_app(settings, web_dist_dir=dist)
    try:
        async with application.router.lifespan_context(application):
            yield application
    finally:
        await application.state.engine.dispose()


async def test_head_on_get_routes_behaves_like_get_without_body(head_app: FastAPI, read_token: str):
    transport = httpx.ASGITransport(app=head_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        for path in GET_ROUTES:
            for headers in ({}, {KEY_HEADER: read_token}):
                got = await c.get(path, headers=headers)
                head = await c.head(path, headers=headers)
                assert head.status_code == got.status_code, (path, head.status_code)
                assert head.status_code != 405, path
                assert head.content == b"", path
                assert head.headers["content-type"] == got.headers["content-type"], path
                assert "content-security-policy" in head.headers, path


async def test_head_on_a_path_without_get_stays_405(head_app: FastAPI):
    transport = httpx.ASGITransport(app=head_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.head("/api/v1/admin/api-keys/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 405
    assert r.content == b""


async def test_head_is_listed_in_allow_next_to_get(head_app: FastAPI):
    transport = httpx.ASGITransport(app=head_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/v1/info")
    assert r.status_code == 405
    allowed = {m.strip() for m in r.headers["allow"].split(",")}
    assert {"GET", "HEAD"} <= allowed


async def test_the_middleware_drops_every_body_chunk_and_passes_other_methods():
    sent: list[dict[str, object]] = []
    seen_methods: list[str] = []

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        if scope["type"] != "http":
            seen_methods.append(scope["type"])
            return
        seen_methods.append(scope["method"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ab", "more_body": True})
        await send({"type": "http.response.body", "body": b"cd"})

    async def receive():  # type: ignore[no-untyped-def]
        return {"type": "http.request", "body": b""}

    async def send(message):  # type: ignore[no-untyped-def]
        sent.append(message)

    middleware = HeadAsGetMiddleware(app)
    await middleware({"type": "http", "method": "HEAD", "path": "/"}, receive, send)
    assert seen_methods == ["GET"]
    assert [m.get("body") for m in sent[1:]] == [b"", b""]
    assert sent[1]["more_body"] is True
    sent.clear()
    await middleware({"type": "http", "method": "POST", "path": "/"}, receive, send)
    assert seen_methods[-1] == "POST"
    assert [m.get("body") for m in sent[1:]] == [b"ab", b"cd"]
    await middleware({"type": "lifespan"}, receive, send)
    assert seen_methods[-1] == "lifespan"
