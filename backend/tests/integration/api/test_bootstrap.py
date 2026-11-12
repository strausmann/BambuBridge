from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import func, select, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from app import main as main_module
from app.auth import dependencies as deps
from app.config import Settings
from app.db.session import make_session_factory
from app.main import create_app
from app.models.api_key import ApiKey
from app.models.user import User
from tests.conftest import (
    DEAD_DATABASE_URL,
    KEY_HEADER,
    TEST_BOOTSTRAP_KEY,
    issue_token,
    settings_variant,
)

BASE = "/api/v1/admin/api-keys"
BOOTSTRAP_HEADER = "X-BambuBridge-Bootstrap"
GOOD = {BOOTSTRAP_HEADER: TEST_BOOTSTRAP_KEY}
BODY = {"name": "first admin", "scope": "admin"}


def _problem(r: httpx.Response, status: int, error_code: str) -> None:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["error_code"] == error_code


async def _count(engine: AsyncEngine) -> int:
    async with make_session_factory(engine)() as session:
        return int(await session.scalar(select(func.count()).select_from(ApiKey)) or 0)


async def test_bootstrap_creates_one_admin_then_closes(
    client: httpx.AsyncClient, settings: Settings, engine: AsyncEngine
):
    r = await client.post(BASE, json=BODY, headers=GOOD)
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    assert r.json()["scope"] == "admin"
    # The new token works as admin.
    assert (await client.get(BASE, headers={KEY_HEADER: token})).status_code == 200

    second = await client.post(BASE, json=BODY, headers=GOOD)
    _problem(second, 403, "bootstrap_closed")
    assert await _count(engine) == 1


async def test_bootstrap_token_owned_by_single_admin_user(
    client: httpx.AsyncClient, engine: AsyncEngine
):
    r = await client.post(BASE, json=BODY, headers=GOOD)
    assert r.status_code == 201
    async with make_session_factory(engine)() as session:
        users = (await session.scalars(select(User))).all()
        key = await session.scalar(select(ApiKey))
    assert len(users) == 1
    assert (users[0].display_name, users[0].role, users[0].enabled) == ("admin", "admin", True)
    assert key is not None
    assert key.owner_user_id == users[0].id


async def test_bootstrap_rejected_with_wrong_key_constant_message(
    client: httpx.AsyncClient, engine: AsyncEngine
):
    bodies = []
    for wrong in ("x", TEST_BOOTSTRAP_KEY[:-1], TEST_BOOTSTRAP_KEY + "x", "y" * 64):
        r = await client.post(BASE, json=BODY, headers={BOOTSTRAP_HEADER: wrong})
        _problem(r, 401, "invalid_bootstrap_key")
        assert wrong not in r.text
        assert TEST_BOOTSTRAP_KEY not in r.text
        bodies.append(r.json())
    assert all(b == bodies[0] for b in bodies)
    assert await _count(engine) == 0


async def test_bootstrap_wrong_key_after_close_gives_same_message(
    client: httpx.AsyncClient, engine: AsyncEngine, admin_token: str
):
    # Closed or open: a wrong key never tells the caller which.
    r = await client.post(BASE, json=BODY, headers={BOOTSTRAP_HEADER: "nope"})
    _problem(r, 401, "invalid_bootstrap_key")


async def test_bootstrap_uses_constant_time_compare(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    import app.auth.dependencies as deps

    calls: list[tuple[bytes, bytes]] = []
    real = deps.hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(deps.hmac, "compare_digest", spy)
    await client.post(BASE, json=BODY, headers={BOOTSTRAP_HEADER: "wrong"})
    assert len(calls) == 1


async def test_bootstrap_only_for_unrestricted_admin_token(client: httpx.AsyncClient):
    _problem(
        await client.post(BASE, json={"name": "weak", "scope": "read"}, headers=GOOD),
        403,
        "bootstrap_admin_key_only",
    )
    soon = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    _problem(
        await client.post(BASE, json={**BODY, "expires_at": soon}, headers=GOOD),
        403,
        "bootstrap_admin_key_only",
    )


async def test_bootstrap_header_only_works_on_create(client: httpx.AsyncClient):
    _problem(await client.get(BASE, headers=GOOD), 401, "not_authenticated")


async def test_bootstrap_closed_while_an_admin_token_exists(
    client: httpx.AsyncClient, admin_token: str
):
    _problem(await client.post(BASE, json=BODY, headers=GOOD), 403, "bootstrap_closed")


@pytest.mark.parametrize("state", ["disabled", "expired", "read_scope"])
async def test_bootstrap_reopens_without_a_usable_admin_token(
    client: httpx.AsyncClient, engine: AsyncEngine, state: str
):
    # Reopen criterion: no enabled, unexpired token with scope admin.
    plaintext = await issue_token(engine, "read" if state == "read_scope" else "admin")
    values: dict[str, object] = {}
    if state == "disabled":
        values["enabled"] = False
    if state == "expired":
        values["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    if values:
        async with make_session_factory(engine)() as session:
            await session.execute(
                update(ApiKey).where(ApiKey.prefix == plaintext[:16]).values(**values)
            )
            await session.commit()
    r = await client.post(BASE, json=BODY, headers=GOOD)
    assert r.status_code == 201, r.text
    # The new token really works.
    assert (await client.get(BASE, headers={KEY_HEADER: r.json()["token"]})).status_code == 200


async def test_bootstrap_stays_closed_when_admin_token_owner_is_disabled(
    client: httpx.AsyncClient, engine: AsyncEngine, admin_token: str
):
    async with make_session_factory(engine)() as session:
        await session.execute(update(User).values(enabled=False))
        await session.commit()
    _problem(await client.post(BASE, json=BODY, headers=GOOD), 403, "bootstrap_closed")


async def test_bootstrap_refused_for_disabled_admin_user(
    client: httpx.AsyncClient, engine: AsyncEngine
):
    # The admin user exists but is disabled and has no admin token: no dead token is issued.
    async with make_session_factory(engine)() as session:
        session.add(User(display_name="admin", role="admin", enabled=False))
        await session.commit()
    _problem(await client.post(BASE, json=BODY, headers=GOOD), 403, "bootstrap_owner_disabled")
    assert await _count(engine) == 0


async def test_bootstrap_refused_when_admin_user_lost_its_role(
    client: httpx.AsyncClient, engine: AsyncEngine
):
    async with make_session_factory(engine)() as session:
        session.add(User(display_name="admin", role="read"))
        await session.commit()
    _problem(await client.post(BASE, json=BODY, headers=GOOD), 403, "bootstrap_owner_not_admin")
    assert await _count(engine) == 0
    async with make_session_factory(engine)() as session:
        names = (await session.scalars(select(User.display_name))).all()
    assert names == ["admin"]


async def test_token_header_wins_over_bootstrap_header(client: httpx.AsyncClient, read_token: str):
    r = await client.post(BASE, json=BODY, headers={**GOOD, KEY_HEADER: read_token})
    _problem(r, 403, "insufficient_scope")


async def test_concurrent_bootstrap_creates_exactly_one(
    client: httpx.AsyncClient, engine: AsyncEngine
):
    results = await asyncio.gather(*(client.post(BASE, json=BODY, headers=GOOD) for _ in range(4)))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 403, 403, 403]
    assert await _count(engine) == 1


@pytest_asyncio.fixture
async def client_without_bootstrap(
    settings: Settings, engine: AsyncEngine
) -> AsyncIterator[httpx.AsyncClient]:
    key = base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode()
    disabled = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=settings.database_url,
        secret_key=key,  # type: ignore[arg-type]
        public_url="https://bb.example.com",  # type: ignore[arg-type]
    )
    application = create_app(disabled)
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await application.state.engine.dispose()


async def test_bootstrap_disabled_without_configured_key(
    client_without_bootstrap: httpx.AsyncClient, engine: AsyncEngine
):
    for value in ("anything", TEST_BOOTSTRAP_KEY):
        r = await client_without_bootstrap.post(BASE, json=BODY, headers={BOOTSTRAP_HEADER: value})
        _problem(r, 401, "invalid_bootstrap_key")
    assert await _count(engine) == 0


async def test_create_without_any_header_401(client: httpx.AsyncClient):
    _problem(await client.post(BASE, json=BODY), 401, "not_authenticated")


def _client_at(app: FastAPI, ip: str) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, client=(ip, 40000))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_bootstrap_failures_are_limited_per_client(app: FastAPI, engine: AsyncEngine):
    # Audit H1: wrong bootstrap keys count against a per-client budget; over it the
    # address gets 429 without a key comparison, even for the right key. Other addresses
    # are not affected.
    budget = deps.FAILED_BOOTSTRAP_ATTEMPTS_PER_CLIENT_PER_MINUTE
    async with _client_at(app, "198.51.100.7") as guesser:
        for _ in range(budget):
            r = await guesser.post(BASE, json=BODY, headers={BOOTSTRAP_HEADER: "wrong"})
            _problem(r, 401, "invalid_bootstrap_key")
        r = await guesser.post(BASE, json=BODY, headers={BOOTSTRAP_HEADER: "wrong"})
        _problem(r, 429, "rate_limited")
        assert int(r.headers["Retry-After"]) >= 1
        r = await guesser.post(BASE, json=BODY, headers=GOOD)
        _problem(r, 429, "rate_limited")
    assert await _count(engine) == 0
    async with _client_at(app, "198.51.100.8") as operator:
        r = await operator.post(BASE, json=BODY, headers=GOOD)
        assert r.status_code == 201, r.text


async def test_correct_bootstrap_key_does_not_use_up_the_budget(app: FastAPI):
    budget = deps.FAILED_BOOTSTRAP_ATTEMPTS_PER_CLIENT_PER_MINUTE
    async with _client_at(app, "198.51.100.9") as c:
        for _ in range(budget - 1):
            r = await c.post(BASE, json=BODY, headers={BOOTSTRAP_HEADER: "wrong"})
            _problem(r, 401, "invalid_bootstrap_key")
        assert (await c.post(BASE, json=BODY, headers=GOOD)).status_code == 201
        # Closed now; the answer is the closed one, not a rate limit.
        _problem(await c.post(BASE, json=BODY, headers=GOOD), 403, "bootstrap_closed")


async def test_startup_warns_while_bootstrap_is_open(
    app: FastAPI, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        async with app.router.lifespan_context(app):
            pass
    assert "bootstrap is open" in caplog.text
    assert TEST_BOOTSTRAP_KEY not in caplog.text


async def test_startup_does_not_warn_once_bootstrap_is_closed(
    app: FastAPI, admin_token: str, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        async with app.router.lifespan_context(app):
            pass
    assert "bootstrap is open" not in caplog.text


async def test_startup_does_not_warn_without_a_bootstrap_key(
    settings: Settings, engine: AsyncEngine, caplog: pytest.LogCaptureFixture
):
    application = create_app(settings_variant(settings, bootstrap_admin_key=""))
    with caplog.at_level(logging.WARNING, logger="app.main"):
        async with application.router.lifespan_context(application):
            pass
    assert "bootstrap is open" not in caplog.text


async def test_startup_bootstrap_check_survives_a_dead_database(
    settings: Settings, caplog: pytest.LogCaptureFixture
):
    application = create_app(settings_variant(settings, database_url=DEAD_DATABASE_URL))
    with caplog.at_level(logging.WARNING, logger="app.main"):
        await main_module.warn_if_bootstrap_open(application)
    assert "bootstrap is open" not in caplog.text
    await application.state.engine.dispose()


async def test_startup_survives_a_database_error_in_the_bootstrap_check(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # For example a database that has not been migrated: the query itself fails.
    async def broken(*args: object, **kwargs: object) -> bool:
        raise ProgrammingError("SELECT 1", {}, Exception("relation does not exist"))

    monkeypatch.setattr(main_module.api_keys_repo, "usable_admin_token_exists", broken)
    with caplog.at_level(logging.WARNING, logger="app.main"):
        async with app.router.lifespan_context(app):
            pass
    assert "bootstrap is open" not in caplog.text
    assert "bootstrap state check skipped: database error" in caplog.text
    assert TEST_BOOTSTRAP_KEY not in caplog.text
