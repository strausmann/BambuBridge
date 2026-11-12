"""The browser-test server (``tests/e2e_app.py``) is the real app plus one reset path."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from tests import e2e_app

PORT = 18765
ORIGIN = f"http://127.0.0.1:{PORT}"
KEYS = "/api/v1/admin/api-keys"
BOOTSTRAP = {"X-BambuBridge-Bootstrap": e2e_app.E2E_BOOTSTRAP_KEY}
BODY = {"name": "First admin token", "scope": "admin"}


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<!doctype html><title>shell</title>")
    return tmp_path


@pytest_asyncio.fixture
async def e2e(test_database_url: str, engine: AsyncEngine, dist: Path) -> AsyncIterator[FastAPI]:
    app = e2e_app.build_app(test_database_url, PORT, dist)
    try:
        yield app
    finally:
        await app.state.engine.dispose()


@pytest_asyncio.fixture
async def browser(e2e: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=e2e)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
        yield client


async def test_public_url_is_the_loopback_origin_the_browser_uses(e2e: FastAPI):
    assert str(e2e.state.settings.public_url).rstrip("/") == ORIGIN


async def test_sign_in_with_the_bootstrapped_token_needs_that_origin(browser: httpx.AsyncClient):
    created = await browser.post(KEYS, json=BODY, headers=BOOTSTRAP)
    assert created.status_code == 201, created.text
    token = created.json()["token"]

    wrong = await browser.post(
        "/api/v1/auth/session", json={"token": token}, headers={"Origin": "http://localhost:1"}
    )
    assert wrong.status_code == 403
    assert wrong.json()["error_code"] == "origin_mismatch"

    opened = await browser.post(
        "/api/v1/auth/session", json={"token": token}, headers={"Origin": ORIGIN}
    )
    assert opened.status_code == 201, opened.text
    assert opened.json()["scope"] == "admin"


async def test_reset_reopens_bootstrap_and_ends_sessions(browser: httpx.AsyncClient):
    first = await browser.post(KEYS, json=BODY, headers=BOOTSTRAP)
    assert first.status_code == 201
    closed = await browser.post(KEYS, json=BODY, headers=BOOTSTRAP)
    assert closed.status_code == 403
    assert closed.json()["error_code"] == "bootstrap_closed"
    opened = await browser.post(
        "/api/v1/auth/session", json={"token": first.json()["token"]}, headers={"Origin": ORIGIN}
    )
    assert opened.status_code == 201
    assert (await browser.get("/api/v1/auth/session")).status_code == 200

    reset = await browser.post(e2e_app.RESET_PATH)
    assert reset.status_code == 204

    assert (await browser.get("/api/v1/auth/session")).status_code == 401
    again = await browser.post(KEYS, json=BODY, headers=BOOTSTRAP)
    assert again.status_code == 201, again.text
    assert again.json()["token"] != first.json()["token"]


async def test_reset_forgets_rate_limit_history(browser: httpx.AsyncClient, e2e: FastAPI):
    limit = e2e.state.settings_store.get("auth.sign_in_limit_per_minute")
    for _ in range(limit):
        r = await browser.post(
            "/api/v1/auth/session", json={"token": "bb_wrong"}, headers={"Origin": ORIGIN}
        )
        assert r.status_code == 401
    blocked = await browser.post(
        "/api/v1/auth/session", json={"token": "bb_wrong"}, headers={"Origin": ORIGIN}
    )
    assert blocked.status_code == 429

    assert (await browser.post(e2e_app.RESET_PATH)).status_code == 204

    after = await browser.post(
        "/api/v1/auth/session", json={"token": "bb_wrong"}, headers={"Origin": ORIGIN}
    )
    assert after.status_code == 401


async def test_reset_path_is_not_swallowed_by_the_web_ui(browser: httpx.AsyncClient):
    # Other methods on the control path are refused, and the UI still answers its own paths.
    assert (await browser.get(e2e_app.RESET_PATH)).status_code == 405
    shell = await browser.get("/providers")
    assert shell.status_code == 200
    assert "shell" in shell.text


async def test_production_app_has_no_reset_path(app: FastAPI):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://bb.example.com") as client:
        assert (await client.post(e2e_app.RESET_PATH)).status_code == 404


def test_module_builds_the_app_only_on_first_use():
    with pytest.raises(AttributeError):
        _ = e2e_app.nothing_here  # type: ignore[attr-defined]
