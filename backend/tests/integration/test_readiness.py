"""``GET /readiness``: database and settings listener, guarded by scope ``read``."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from fastapi import FastAPI

from app.api.routes import system
from app.config import Settings
from app.main import create_app
from tests.conftest import DEAD_DATABASE_URL, KEY_HEADER, settings_variant

# Syntactically a token; with the database down it cannot be checked anyway.
SOME_TOKEN = "bb_pat_" + "A" * 40


async def test_readiness_ok_with_running_listener(app: FastAPI, read_token: str):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/readiness", headers={KEY_HEADER: read_token})
    assert r.status_code == 200, r.text
    assert r.json() == {"database": "ok", "listener": "ok"}
    assert r.headers["cache-control"] == "no-store"


async def test_readiness_reports_listener_down(client: httpx.AsyncClient, read_token: str):
    # No lifespan in this client: the settings listener never started.
    r = await client.get("/readiness", headers={KEY_HEADER: read_token})
    assert r.status_code == 503
    assert r.json() == {"database": "ok", "listener": "unavailable"}


async def test_readiness_needs_credentials(client: httpx.AsyncClient):
    r = await client.get("/readiness")
    assert r.status_code == 401
    assert r.json()["error_code"] == "not_authenticated"


async def test_readiness_reports_database_down(settings: Settings):
    # Review focus 4: database unreachable -> readiness 503 with database "unavailable",
    # liveness stays 200.
    application = create_app(settings_variant(settings, database_url=DEAD_DATABASE_URL))
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/readiness", headers={KEY_HEADER: SOME_TOKEN})
            assert r.status_code == 503, r.text
            assert r.json() == {"database": "unavailable", "listener": "unavailable"}
            assert (await c.get("/healthz")).status_code == 200
            # Without credentials nothing is revealed.
            assert (await c.get("/readiness")).status_code == 401
    finally:
        await application.state.engine.dispose()


async def test_info_is_public_and_minimal(client: httpx.AsyncClient):
    r = await client.get("/api/v1/info")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"name", "version", "build", "bootstrap_open"}
    assert body["name"] == "BambuBridge"


async def test_info_reports_bootstrap_open_until_an_admin_token_exists(
    client: httpx.AsyncClient, admin_token: str
):
    # The key is configured by the fixture and the admin token already exists: closed.
    assert admin_token
    assert (await client.get("/api/v1/info")).json()["bootstrap_open"] is False


async def test_info_reports_bootstrap_open_on_a_fresh_install(client: httpx.AsyncClient):
    assert (await client.get("/api/v1/info")).json()["bootstrap_open"] is True


async def test_info_reports_bootstrap_closed_without_a_configured_key(settings: Settings):
    application = create_app(settings_variant(settings, bootstrap_admin_key=""))
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            assert (await c.get("/api/v1/info")).json()["bootstrap_open"] is False
    finally:
        await application.state.engine.dispose()


async def test_info_still_answers_when_the_database_is_down(settings: Settings):
    # A hint for the sign-in page only; the server enforces bootstrap itself. Unknown -> open.
    application = create_app(settings_variant(settings, database_url=DEAD_DATABASE_URL))
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/api/v1/info")
        assert r.status_code == 200
        assert r.json()["bootstrap_open"] is True
    finally:
        await application.state.engine.dispose()


async def test_readiness_is_bounded_when_the_database_stalls(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    # A TCP listener that accepts and never answers: the auth lookup on the readiness
    # path must give up after the readiness timeout and answer 503, not wait.
    monkeypatch.setattr(system, "DATABASE_CHECK_TIMEOUT_SECONDS", 0.5)
    stalled: list[asyncio.StreamWriter] = []

    async def accept(_r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        stalled.append(w)

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    url = f"postgresql+asyncpg://u:p@127.0.0.1:{port}/x"
    application = create_app(settings_variant(settings, database_url=url))
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            started = time.monotonic()
            r = await asyncio.wait_for(
                c.get("/readiness", headers={KEY_HEADER: SOME_TOKEN}), timeout=10
            )
            elapsed = time.monotonic() - started
        assert r.status_code == 503, r.text
        assert r.json() == {"database": "unavailable", "listener": "unavailable"}
        # One bound, not one per check: the auth timeout already answers for the database.
        assert elapsed < 1.5, elapsed
    finally:
        for w in stalled:
            w.close()
        server.close()
        await application.state.engine.dispose()
