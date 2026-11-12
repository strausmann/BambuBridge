"""``GET /readiness``: database and settings listener, guarded by scope ``read``."""

from __future__ import annotations

import httpx
from fastapi import FastAPI

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
    assert set(body) == {"name", "version", "build"}
    assert body["name"] == "BambuBridge"
