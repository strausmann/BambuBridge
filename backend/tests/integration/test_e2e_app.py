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
BODY = {"name": "First admin token", "scope": "admin"}
RESET = {e2e_app.RESET_HEADER: e2e_app.RESET_HEADER_VALUE}


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


@pytest.fixture
def bootstrap_headers(e2e: FastAPI) -> dict[str, str]:
    return {"X-BambuBridge-Bootstrap": e2e.state.e2e_bootstrap_key}


async def test_public_url_is_the_loopback_origin_the_browser_uses(e2e: FastAPI):
    assert str(e2e.state.settings.public_url).rstrip("/") == ORIGIN


async def test_sign_in_with_the_bootstrapped_token_needs_that_origin(
    browser: httpx.AsyncClient, bootstrap_headers: dict[str, str]
):
    created = await browser.post(KEYS, json=BODY, headers=bootstrap_headers)
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


async def test_reset_reopens_bootstrap_and_ends_sessions(
    browser: httpx.AsyncClient, bootstrap_headers: dict[str, str]
):
    first = await browser.post(KEYS, json=BODY, headers=bootstrap_headers)
    assert first.status_code == 201
    closed = await browser.post(KEYS, json=BODY, headers=bootstrap_headers)
    assert closed.status_code == 403
    assert closed.json()["error_code"] == "bootstrap_closed"
    opened = await browser.post(
        "/api/v1/auth/session", json={"token": first.json()["token"]}, headers={"Origin": ORIGIN}
    )
    assert opened.status_code == 201
    assert (await browser.get("/api/v1/auth/session")).status_code == 200

    reset = await browser.post(e2e_app.RESET_PATH, headers=RESET)
    assert reset.status_code == 204

    assert (await browser.get("/api/v1/auth/session")).status_code == 401
    again = await browser.post(KEYS, json=BODY, headers=bootstrap_headers)
    assert again.status_code == 201, again.text
    assert again.json()["token"] != first.json()["token"]


async def test_reset_returns_the_settings_in_memory_to_their_defaults(
    browser: httpx.AsyncClient, e2e: FastAPI, bootstrap_headers: dict[str, str]
):
    token = (await browser.post(KEYS, json=BODY, headers=bootstrap_headers)).json()["token"]
    changed = await browser.put(
        "/api/v1/settings",
        json={"values": {"retention.events_days": 14}},
        headers={"X-BambuBridge-Key": token},
    )
    assert changed.status_code == 204, changed.text
    store = e2e.state.settings_store
    assert store.get("retention.events_days") == 14

    assert (await browser.post(e2e_app.RESET_PATH, headers=RESET)).status_code == 204

    # The table is empty, so the next test must not meet the previous test's value.
    assert store.get("retention.events_days") == 90


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

    assert (await browser.post(e2e_app.RESET_PATH, headers=RESET)).status_code == 204

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
        assert (await client.post(e2e_app.RESET_PATH, headers=RESET)).status_code == 404


def test_module_builds_the_app_only_on_first_use():
    with pytest.raises(AttributeError):
        _ = e2e_app.nothing_here  # type: ignore[attr-defined]


async def test_reset_needs_its_header_and_leaves_everything_in_place_without_it(
    browser: httpx.AsyncClient, bootstrap_headers: dict[str, str]
):
    assert (await browser.post(KEYS, json=BODY, headers=bootstrap_headers)).status_code == 201

    for headers in ({}, {e2e_app.RESET_HEADER: "yes"}, {"X-Requested-With": "reset"}):
        assert (await browser.post(e2e_app.RESET_PATH, headers=headers)).status_code == 403

    # Nothing was emptied: bootstrap is still closed.
    closed = await browser.post(KEYS, json=BODY, headers=bootstrap_headers)
    assert closed.status_code == 403
    assert closed.json()["error_code"] == "bootstrap_closed"


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        f"evil.example:{PORT}",
        "127.0.0.1",
        "127.0.0.1:1",
        f"127.0.0.1.evil.example:{PORT}",
        "",
    ],
)
async def test_another_host_name_is_refused_on_every_path(
    browser: httpx.AsyncClient, bootstrap_headers: dict[str, str], host: str
):
    named = {"Host": host}
    assert (await browser.post(e2e_app.RESET_PATH, headers={**RESET, **named})).status_code == 421
    assert (
        await browser.post(KEYS, json=BODY, headers={**bootstrap_headers, **named})
    ).status_code == 421
    assert (await browser.get("/providers", headers=named)).status_code == 421
    # The refused attempts changed nothing: bootstrap is still open.
    assert (await browser.post(KEYS, json=BODY, headers=bootstrap_headers)).status_code == 201


async def test_localhost_with_the_test_port_is_answered(browser: httpx.AsyncClient):
    assert (
        await browser.get("/providers", headers={"Host": f"localhost:{PORT}"})
    ).status_code == 200
    assert (
        await browser.get("/providers", headers={"Host": f"LOCALHOST:{PORT}"})
    ).status_code == 200


async def test_a_request_that_arrived_on_another_interface_is_refused(e2e: FastAPI):
    # The transport reports the address the "connection" was accepted on from the URL.
    transport = httpx.ASGITransport(app=e2e)
    async with httpx.AsyncClient(
        transport=transport, base_url=f"http://192.0.2.10:{PORT}"
    ) as client:
        response = await client.get("/providers", headers={"Host": f"127.0.0.1:{PORT}"})
    assert response.status_code == 421


async def test_bootstrap_key_is_random_per_app_and_can_be_given(test_database_url: str, dist: Path):
    first = e2e_app.build_app(test_database_url, PORT, dist)
    second = e2e_app.build_app(test_database_url, PORT, dist)
    given = e2e_app.build_app(
        test_database_url, PORT, dist, "given-by-the-test-runner-for-this-one-run"
    )
    try:
        assert first.state.e2e_bootstrap_key != second.state.e2e_bootstrap_key
        assert len(first.state.e2e_bootstrap_key) >= 32
        assert given.state.e2e_bootstrap_key == "given-by-the-test-runner-for-this-one-run"
        assert not hasattr(e2e_app, "E2E_bootstrap_headers_KEY")
    finally:
        for built in (first, second, given):
            await built.state.engine.dispose()


async def test_the_former_fixed_key_opens_nothing(browser: httpx.AsyncClient):
    old = {"X-BambuBridge-Bootstrap": "e2e-bootstrap-key-for-browser-tests-only"}
    assert (await browser.post(KEYS, json=BODY, headers=old)).status_code == 401


@pytest.mark.parametrize(
    "argv",
    [
        ["uvicorn", "tests.e2e_app:app"],
        ["uvicorn", "tests.e2e_app:app", "--host", "127.0.0.1", "--port", "8765"],
        ["uvicorn", "--host=localhost", "tests.e2e_app:app"],
        ["uvicorn", "--host", "::1", "tests.e2e_app:app"],
    ],
)
def test_a_loopback_bind_is_accepted(argv: list[str]):
    e2e_app.refuse_non_loopback_bind(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["uvicorn", "tests.e2e_app:app", "--host", "0.0.0.0"],  # noqa: S104 - the refused value
        ["uvicorn", "--host=::", "tests.e2e_app:app"],
        ["uvicorn", "--host", "192.0.2.10", "tests.e2e_app:app"],
        ["uvicorn", "--host", "127.0.0.1", "--host", "0.0.0.0", "tests.e2e_app:app"],  # noqa: S104
        ["uvicorn", "--host", "bb.example.com", "tests.e2e_app:app"],
    ],
)
def test_any_other_bind_stops_the_server_before_it_starts(argv: list[str]):
    with pytest.raises(RuntimeError, match="loopback"):
        e2e_app.refuse_non_loopback_bind(argv)


# --- the second build (update test) ------------------------------------------------------

NEXT = {e2e_app.RESET_HEADER: e2e_app.NEXT_BUILD_HEADER_VALUE}


@pytest_asyncio.fixture
async def two_builds(
    test_database_url: str, engine: AsyncEngine, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    first = tmp_path / "first"
    (first / "assets").mkdir(parents=True)
    (first / "index.html").write_text("first shell")
    (first / "sw.js").write_text("// worker 1")
    (first / "assets" / "a-1.js").write_text("// a1")
    second = tmp_path / "next"
    (second / "assets").mkdir(parents=True)
    (second / "index.html").write_text("next shell")
    (second / "sw.js").write_text("// worker 2")
    (second / "assets" / "a-2.js").write_text("// a2")
    app = e2e_app.build_app(test_database_url, PORT, first, next_dist_dir=second)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            yield client
    finally:
        await app.state.engine.dispose()
    # The originals are never written to.
    assert (first / "index.html").read_text() == "first shell"
    assert not (first / "assets" / "a-2.js").exists()


async def test_next_build_switches_files_and_version(two_builds: httpx.AsyncClient):
    version = (await two_builds.get("/api/v1/info")).headers["x-bambubridge-version"]
    assert (await two_builds.get("/")).text == "first shell"

    assert (await two_builds.post(e2e_app.NEXT_BUILD_PATH, headers=NEXT)).status_code == 204
    assert (await two_builds.get("/")).text == "next shell"
    assert (await two_builds.get("/sw.js")).text == "// worker 2"
    # The old hashed file stays, as on a server between two releases.
    assert (await two_builds.get("/assets/a-1.js")).status_code == 200
    assert (await two_builds.get("/assets/a-2.js")).status_code == 200
    info = await two_builds.get("/api/v1/info")
    switched = info.headers["x-bambubridge-version"]
    assert switched == f"{e2e_app.VERSION}+{e2e_app.DEFAULT_NEXT_BUILD_ID}"
    assert switched != version
    # The body says the same as the header (the device page shows it as the server's build).
    assert info.json()["build"] == e2e_app.DEFAULT_NEXT_BUILD_ID
    assert int(info.headers["content-length"]) == len(info.content)
    # Only API answers carry the header, as without the switch.
    assert "x-bambubridge-version" not in (await two_builds.get("/")).headers

    assert (await two_builds.post(e2e_app.RESET_PATH, headers=RESET)).status_code == 204
    assert (await two_builds.get("/")).text == "first shell"
    assert (await two_builds.get("/assets/a-2.js")).status_code == 404
    back_info = await two_builds.get("/api/v1/info")
    assert back_info.headers["x-bambubridge-version"] == version
    assert back_info.json()["build"] != e2e_app.DEFAULT_NEXT_BUILD_ID


async def test_next_build_needs_its_header(two_builds: httpx.AsyncClient):
    assert (await two_builds.post(e2e_app.NEXT_BUILD_PATH)).status_code == 403
    assert (await two_builds.post(e2e_app.NEXT_BUILD_PATH, headers=RESET)).status_code == 403
    assert (await two_builds.get("/")).text == "first shell"


async def test_next_build_without_a_second_build_is_404(browser: httpx.AsyncClient):
    assert (await browser.post(e2e_app.NEXT_BUILD_PATH, headers=NEXT)).status_code == 404
