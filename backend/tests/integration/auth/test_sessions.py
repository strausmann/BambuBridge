"""Browser sessions: token sign-in, cookies, CSRF and origin checks, expiry, sign-out."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth import sessions as ui_sessions
from app.config import Settings
from app.db.session import make_session_factory
from app.main import create_app
from app.models.api_key import ApiKey
from app.models.ui_session import UiSession
from app.models.user import User
from app.repositories import users as users_repo
from tests.conftest import (
    CSRF_HEADER,
    DEAD_DATABASE_URL,
    PUBLIC_URL,
    SESSION_URL,
    SETTINGS_URL,
    TRUST_TOKEN,
    csrf_from,
    issue_token,
    put_settings,
    settings_variant,
)

SSO = {"X-Pangolin-Token": TRUST_TOKEN, "Remote-User": "alice"}
API_KEYS_URL = "/api/v1/admin/api-keys"


def _problem(r: httpx.Response, status: int, error_code: str) -> None:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["error_code"] == error_code


async def _sign_in(browser: httpx.AsyncClient, token: str) -> httpx.Response:
    r = await browser.post(SESSION_URL, json={"token": token})
    assert r.status_code == 201, r.text
    return r


async def _rows(engine: AsyncEngine) -> list[UiSession]:
    async with make_session_factory(engine)() as session:
        return list((await session.scalars(select(UiSession).order_by(UiSession.created_at))).all())


# --- sign-in -------------------------------------------------------------------------------


async def test_token_sign_in_creates_session(
    browser: httpx.AsyncClient, admin_token: str, engine: AsyncEngine
):
    r = await _sign_in(browser, admin_token)
    body = r.json()
    assert body["kind"] == "session"
    assert body["scope"] == "admin"
    assert body["identity_provider"] is None
    assert body["identity_subject"] is None
    assert body["user"] == "admin"
    rows = await _rows(engine)
    assert len(rows) == 1
    assert rows[0].api_key_id is not None
    # Only the hash is stored; the cookie value appears nowhere in the row.
    cookie = browser.cookies.get("__Host-bb_session")
    assert cookie and rows[0].token_hash == ui_sessions.hash_token(cookie)
    assert cookie not in repr(rows[0].__dict__)
    assert admin_token not in r.text


async def test_sign_in_with_wrong_token_401(browser: httpx.AsyncClient, admin_token: str):
    forged = admin_token[:16] + "X" * (len(admin_token) - 16)
    r = await browser.post(SESSION_URL, json={"token": forged})
    _problem(r, 401, "invalid_token")
    assert forged not in r.text
    assert "set-cookie" not in r.headers
    _problem(await browser.post(SESSION_URL, json={"token": ""}), 422, "validation_failed")


async def test_sign_in_needs_public_origin_403(browser: httpx.AsyncClient, admin_token: str):
    for origin in ("https://evil.example", "null", "https://bb.example.com.evil.example"):
        r = await browser.post(SESSION_URL, json={"token": admin_token}, headers={"Origin": origin})
        _problem(r, 403, "origin_mismatch")
    del browser.headers["Origin"]
    _problem(await browser.post(SESSION_URL, json={"token": admin_token}), 403, "origin_mismatch")


async def test_sign_in_rate_limited_per_client(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    await put_settings(admin_client, {"auth.sign_in_limit_per_minute": 2})
    for _ in range(2):
        _problem(await browser.post(SESSION_URL), 401, "not_authenticated")
    r = await browser.post(SESSION_URL)
    _problem(r, 429, "rate_limited")
    assert int(r.headers["Retry-After"]) >= 1


async def test_sign_in_db_error_503(settings: Settings, admin_token: str):
    application = create_app(settings_variant(settings, database_url=DEAD_DATABASE_URL))
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url=PUBLIC_URL, headers={"Origin": PUBLIC_URL}
        ) as c:
            r = await c.post(SESSION_URL, json={"token": admin_token})
            _problem(r, 503, "database_unavailable")
            assert "set-cookie" not in r.headers
    finally:
        await application.state.engine.dispose()


# --- cookies -------------------------------------------------------------------------------


async def test_session_cookie_host_prefix_and_strict(browser: httpx.AsyncClient, admin_token: str):
    r = await _sign_in(browser, admin_token)
    cookies = {c.split("=", 1)[0]: c.lower() for c in r.headers.get_list("set-cookie")}
    assert set(cookies) == {"__Host-bb_session", "__Host-bb_csrf"}
    for name, raw in cookies.items():
        assert "samesite=strict" in raw
        assert "secure" in raw
        assert "path=/" in raw
        assert "max-age=43200" in raw
        assert "domain=" not in raw  # __Host- forbids a Domain attribute
        assert ("httponly" in raw) == (name == "__Host-bb_session")


async def test_plain_http_public_url_uses_unprefixed_cookies_and_warns(
    settings: Settings, admin_token: str, caplog: pytest.LogCaptureFixture
):
    application = create_app(settings_variant(settings, public_url="http://bb.example.com"))
    with caplog.at_level(logging.WARNING, logger="app.auth.sessions"):
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://bb.example.com",
                headers={"Origin": "http://bb.example.com"},
            ) as c:
                r = await c.post(SESSION_URL, json={"token": admin_token})
                assert r.status_code == 201, r.text
                names = {h.split("=", 1)[0] for h in r.headers.get_list("set-cookie")}
                assert names == {"bb_session", "bb_csrf"}
                assert all("secure" not in h.lower() for h in r.headers.get_list("set-cookie"))
                assert (await c.get(SESSION_URL)).status_code == 200
    assert "not https" in caplog.text


# --- CSRF and origin -------------------------------------------------------------------------


async def test_session_write_without_csrf_403(browser: httpx.AsyncClient, admin_token: str):
    await _sign_in(browser, admin_token)
    values = {"values": {"retention.events_days": 7}}
    _problem(await browser.put(SETTINGS_URL, json=values), 403, "csrf_failed")
    wrong = {CSRF_HEADER: "A" * 43}
    _problem(await browser.put(SETTINGS_URL, json=values, headers=wrong), 403, "csrf_failed")
    good = {CSRF_HEADER: csrf_from(browser)}
    r = await browser.put(
        SETTINGS_URL, json=values, headers={**good, "Origin": "https://evil.example"}
    )
    _problem(r, 403, "origin_mismatch")
    assert (await browser.put(SETTINGS_URL, json=values, headers=good)).status_code == 204
    # Reading needs no CSRF token.
    assert (await browser.get(SETTINGS_URL)).status_code == 200


async def test_csrf_error_never_echoes_tokens(browser: httpx.AsyncClient, admin_token: str):
    await _sign_in(browser, admin_token)
    presented = "B" * 43
    r = await browser.put(SETTINGS_URL, json={"values": {}}, headers={CSRF_HEADER: presented})
    _problem(r, 403, "csrf_failed")
    assert presented not in r.text
    assert csrf_from(browser) not in r.text
    assert browser.cookies.get("__Host-bb_session") not in r.text


async def test_token_requests_need_no_csrf(admin_client: httpx.AsyncClient):
    r = await admin_client.put(SETTINGS_URL, json={"values": {"retention.events_days": 7}})
    assert r.status_code == 204, r.text


async def test_session_can_create_api_token(browser: httpx.AsyncClient, admin_token: str):
    await _sign_in(browser, admin_token)
    body = {"name": "from the browser", "scope": "read"}
    _problem(await browser.post(API_KEYS_URL, json=body), 403, "csrf_failed")
    r = await browser.post(API_KEYS_URL, json=body, headers={CSRF_HEADER: csrf_from(browser)})
    assert r.status_code == 201, r.text


# --- scope and validity --------------------------------------------------------------------


async def test_session_scope_capped_by_token_scope(browser: httpx.AsyncClient, read_token: str):
    await _sign_in(browser, read_token)
    assert (await browser.get(SESSION_URL)).json()["scope"] == "read"
    _problem(await browser.get(SETTINGS_URL), 403, "insufficient_scope")


async def test_session_of_deleted_or_disabled_token_401(
    browser: httpx.AsyncClient, engine: AsyncEngine
):
    token = await issue_token(engine, "admin")
    await _sign_in(browser, token)
    async with make_session_factory(engine)() as session:
        await session.execute(update(ApiKey).values(enabled=False))
        await session.commit()
    _problem(await browser.get(SESSION_URL), 401, "invalid_session")
    async with make_session_factory(engine)() as session:
        await session.execute(update(ApiKey).values(enabled=True, expires_at=datetime.now(UTC)))
        await session.commit()
    _problem(await browser.get(SESSION_URL), 401, "invalid_session")


async def test_session_of_disabled_user_401(
    browser: httpx.AsyncClient, admin_token: str, engine: AsyncEngine
):
    await _sign_in(browser, admin_token)
    async with make_session_factory(engine)() as session:
        await session.execute(update(User).values(enabled=False))
        await session.commit()
    _problem(await browser.get(SESSION_URL), 401, "invalid_session")


async def test_session_expires_after_12_hours(
    browser: httpx.AsyncClient, admin_token: str, monkeypatch: pytest.MonkeyPatch
):
    await _sign_in(browser, admin_token)
    assert (await browser.get(SESSION_URL)).status_code == 200
    later = datetime.now(UTC) + timedelta(hours=12, seconds=1)
    monkeypatch.setattr(ui_sessions, "_now", lambda: later)
    _problem(await browser.get(SESSION_URL), 401, "invalid_session")


async def test_garbage_session_cookie_401(browser: httpx.AsyncClient):
    for value in ("x", "A" * 43):
        browser.cookies.set("__Host-bb_session", value, domain="bb.example.com")
        r = await browser.get(SESSION_URL)
        assert r.status_code == 401, r.text


async def test_max_active_sessions_revokes_oldest(
    browser: httpx.AsyncClient,
    admin_token: str,
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(ui_sessions, "MAX_ACTIVE_SESSIONS", 2)
    for _ in range(3):
        await _sign_in(browser, admin_token)
    rows = await _rows(engine)
    assert [r.revoked_at is not None for r in rows] == [True, False, False]


async def test_long_expired_sessions_are_purged(
    browser: httpx.AsyncClient, admin_token: str, engine: AsyncEngine
):
    await _sign_in(browser, admin_token)
    async with make_session_factory(engine)() as session:
        await session.execute(
            update(UiSession).values(expires_at=datetime.now(UTC) - timedelta(days=2))
        )
        await session.commit()
    await _sign_in(browser, admin_token)
    assert len(await _rows(engine)) == 1


# --- sign-out ------------------------------------------------------------------------------


async def test_sign_out_revokes_session_and_clears_cookies(
    browser: httpx.AsyncClient, admin_token: str, engine: AsyncEngine
):
    await _sign_in(browser, admin_token)
    csrf = csrf_from(browser)
    r = await browser.delete(SESSION_URL, headers={CSRF_HEADER: csrf})
    assert r.status_code == 204, r.text
    cleared = r.headers.get_list("set-cookie")
    assert {c.split("=", 1)[0] for c in cleared} == {"__Host-bb_session", "__Host-bb_csrf"}
    assert all("max-age=0" in c.lower() for c in cleared)
    [row] = await _rows(engine)
    assert row.revoked_at is not None
    _problem(await browser.get(SESSION_URL), 401, "not_authenticated")


async def test_sign_out_without_csrf_403(browser: httpx.AsyncClient, admin_token: str):
    await _sign_in(browser, admin_token)
    _problem(await browser.delete(SESSION_URL), 403, "csrf_failed")


async def test_sign_out_with_token_header_is_a_no_op(admin_client: httpx.AsyncClient):
    assert (await admin_client.delete(SESSION_URL)).status_code == 204
    me = await admin_client.get(SESSION_URL)
    assert me.json() == {
        "kind": "token",
        "scope": "admin",
        "user": "admin",
        "identity_provider": None,
        "identity_subject": None,
        "expires_at": None,
        "csrf_token": None,
    }


async def test_sign_out_db_error_503(
    browser: httpx.AsyncClient, admin_token: str, monkeypatch: pytest.MonkeyPatch
):
    await _sign_in(browser, admin_token)

    async def broken(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("UPDATE ui_sessions", {}, OSError("connection lost"))

    monkeypatch.setattr(ui_sessions, "revoke", broken)
    r = await browser.delete(SESSION_URL, headers={CSRF_HEADER: csrf_from(browser)})
    _problem(r, 503, "database_unavailable")


# --- /auth/continue ------------------------------------------------------------------------


async def test_auth_continue_rejects_absolute_next(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    r = await browser.get("/auth/continue", params={"next": "https://evil.example"}, headers=SSO)
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/"
    assert any(c.startswith("__Host-bb_session=") for c in r.headers.get_list("set-cookie"))


@pytest.mark.parametrize(
    "target", ["//evil.example", "/\\evil.example", "/%2F%2Fevil.example", "javascript:alert(1)"]
)
async def test_auth_continue_with_session_follows_only_relative_next(
    browser: httpx.AsyncClient, admin_token: str, target: str
):
    await _sign_in(browser, admin_token)
    r = await browser.get("/auth/continue", params={"next": target})
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    ok = await browser.get("/auth/continue", params={"next": "/printers?tab=2"})
    assert ok.headers["location"] == "/printers?tab=2"
    assert "set-cookie" not in ok.headers  # the existing session is kept


async def test_auth_continue_without_session_or_sso_401(browser: httpx.AsyncClient):
    _problem(await browser.get("/auth/continue?next=/x"), 401, "not_authenticated")


async def test_auth_continue_sends_a_browser_on_to_the_sign_in(browser: httpx.AsyncClient):
    r = await browser.get(
        "/auth/continue",
        params={"next": "/protocol?tab=2"},
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
    )
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    target = "/sign-in?redirect=%2Fprotocol%3Ftab%3D2"
    assert f'<meta http-equiv="refresh" content="0; url={target}">' in r.text
    assert f'<a href="{target}">' in r.text
    assert "<script" not in r.text
    assert "set-cookie" not in r.headers


async def test_auth_continue_401_varies_on_accept(browser: httpx.AsyncClient):
    """The answer depends on Accept (page or problem JSON): a cache must keep them apart."""
    page = await browser.get("/auth/continue?next=/x", headers={"Accept": "text/html"})
    problem = await browser.get("/auth/continue?next=/x", headers={"Accept": "application/json"})
    for r in (page, problem):
        assert r.status_code == 401
        assert "accept" in [v.strip().lower() for v in r.headers.get("vary", "").split(",")]


async def test_auth_continue_page_carries_no_markup_from_next(browser: httpx.AsyncClient):
    # safe_next lets quotes and angle brackets through in a path; the page must not.
    r = await browser.get(
        "/auth/continue", params={"next": '/x"><img/src=x>'}, headers={"Accept": "text/html"}
    )
    assert r.status_code == 401
    assert "<img" not in r.text
    assert "/sign-in?redirect=%2Fx%22%3E%3Cimg%2Fsrc%3Dx%3E" in r.text


async def test_auth_continue_page_goes_to_root_for_a_refused_next(browser: httpx.AsyncClient):
    r = await browser.get(
        "/auth/continue", params={"next": "//evil.example"}, headers={"Accept": "text/html"}
    )
    assert "/sign-in?redirect=%2F" in r.text
    assert "evil.example" not in r.text


def test_session_keys_hide_their_value_in_repr(app: FastAPI):
    assert repr(app.state.session_keys) == "SessionKeys(<hidden>)"


async def test_auth_continue_rate_limited_per_client(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    await put_settings(admin_client, {"auth.sign_in_limit_per_minute": 2})
    for _ in range(2):
        _problem(await browser.get("/auth/continue?next=/x"), 401, "not_authenticated")
    r = await browser.get("/auth/continue?next=/x")
    _problem(r, 429, "rate_limited")
    assert int(r.headers["Retry-After"]) >= 1
    assert "accept" in r.headers.get("vary", "").lower()


async def test_auth_continue_rate_limited_browser_gets_a_page(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    """A browser that runs into the limit gets a readable page, not problem JSON."""
    await put_settings(admin_client, {"auth.sign_in_limit_per_minute": 1})
    await browser.get("/auth/continue?next=/x", headers={"Accept": "text/html"})
    r = await browser.get(
        "/auth/continue", params={"next": "/protocol"}, headers={"Accept": "text/html"}
    )
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    assert "accept" in r.headers.get("vary", "").lower()
    retry = int(r.headers["Retry-After"])
    assert retry >= 1
    target = "/sign-in?redirect=%2Fprotocol"
    assert f'<meta http-equiv="refresh" content="{retry}; url={target}">' in r.text
    assert f'<a href="{target}">' in r.text
    assert "Too many sign-in attempts" in r.text
    assert "<script" not in r.text


async def test_auth_continue_limits_new_sso_sessions_not_existing_ones(
    app: FastAPI, admin_client: httpx.AsyncClient, engine: AsyncEngine
):
    # A client that drops the cookie and comes back with SSO headers opens a new session
    # each time; those sign-ins count against auth.sign_in_limit_per_minute.
    await put_settings(
        admin_client, {"sso.trust_token": TRUST_TOKEN, "auth.sign_in_limit_per_minute": 2}
    )
    transport = httpx.ASGITransport(app=app)
    for _ in range(2):
        async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as fresh:
            r = await fresh.get("/auth/continue?next=/x", headers=SSO)
            assert r.status_code == 303, r.text
    kept_cookies = fresh.cookies
    assert len(await _rows(engine)) == 2
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as fresh:
        r = await fresh.get("/auth/continue?next=/x", headers=SSO)
        _problem(r, 429, "rate_limited")
        assert int(r.headers["Retry-After"]) >= 1
        assert "set-cookie" not in r.headers
    assert len(await _rows(engine)) == 2  # no new session row
    # A browser that keeps its valid session is redirected without being limited.
    async with httpx.AsyncClient(
        transport=transport, base_url=PUBLIC_URL, cookies=kept_cookies
    ) as browser_with_session:
        for _ in range(4):
            r = await browser_with_session.get("/auth/continue?next=/x", headers=SSO)
            assert r.status_code == 303, r.text
            assert r.headers["location"] == "/x"
            assert "set-cookie" not in r.headers
    assert len(await _rows(engine)) == 2


@pytest.mark.parametrize(
    "preexisting", [ui_sessions.MAX_ACTIVE_SESSIONS - 1, ui_sessions.MAX_ACTIVE_SESSIONS]
)
async def test_parallel_sign_ins_never_exceed_the_session_cap(
    engine: AsyncEngine, preexisting: int
):
    # Each sign-in runs on its own connection; the barrier releases them together, so
    # without a per-user lock they all count the same active sessions before any inserts.
    parallel = 8
    factory = make_session_factory(engine)
    async with factory() as session:
        admin = await users_repo.get_or_create_admin(session)
        await session.commit()
    for _ in range(preexisting):
        async with factory() as session:
            await ui_sessions.create_session(session, user_id=admin.id, scope="admin")
    barrier = asyncio.Barrier(parallel)

    async def sign_in() -> None:
        async with factory() as session:
            await session.connection()  # own connection and transaction, opened up front
            await barrier.wait()
            await ui_sessions.create_session(session, user_id=admin.id, scope="admin")

    await asyncio.gather(*(sign_in() for _ in range(parallel)))
    rows = await _rows(engine)
    active = [r for r in rows if r.revoked_at is None]
    assert len(rows) == preexisting + parallel
    assert len(active) == ui_sessions.MAX_ACTIVE_SESSIONS


async def test_token_sign_ins_never_evict_sessions_of_another_credential(
    app: FastAPI,
    admin_client: httpx.AsyncClient,
    browser: httpx.AsyncClient,
    read_token: str,
    engine: AsyncEngine,
):
    # Audit F1: the cap is per credential. A read token signing in over and over only
    # rotates its own sessions; the operator's SSO session stays valid.
    await put_settings(
        admin_client, {"sso.trust_token": TRUST_TOKEN, "auth.sign_in_limit_per_minute": 600}
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=PUBLIC_URL) as operator:
        r = await operator.get("/auth/continue?next=/x", headers=SSO)
        assert r.status_code == 303, r.text
        for _ in range(ui_sessions.MAX_ACTIVE_SESSIONS + 5):
            await _sign_in(browser, read_token)
            browser.cookies.clear()
        r = await operator.get(SESSION_URL)
        assert r.status_code == 200, r.text
        assert r.json()["scope"] == "admin"
    rows = await _rows(engine)
    token_rows = [row for row in rows if row.api_key_id is not None]
    assert len(token_rows) == ui_sessions.MAX_ACTIVE_SESSIONS + 5
    # The read token's own sessions are still capped.
    assert sum(row.revoked_at is None for row in token_rows) == ui_sessions.MAX_ACTIVE_SESSIONS
    sso_rows = [row for row in rows if row.api_key_id is None]
    assert [row.revoked_at for row in sso_rows] == [None]


def test_session_keys_are_hkdf_sub_keys_of_the_secret_key(settings: Settings):
    from app.security.keys import decode_secret_key, derive_subkey

    master = decode_secret_key(settings.secret_key.get_secret_value(), name="K")
    keys = ui_sessions.session_keys(settings)
    assert keys.csrf == derive_subkey(master, "csrf")
    assert keys.binding == derive_subkey(master, "session-binding")
    assert len({keys.csrf, keys.binding, master, derive_subkey(master, "secret-box")}) == 4
