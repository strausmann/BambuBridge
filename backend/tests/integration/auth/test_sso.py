"""Sign-in through identity providers: trusted Pangolin headers and the provider registry."""

from __future__ import annotations

from typing import ClassVar

import httpx
import pytest
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.identity import registry
from app.auth.identity.base import Identity
from app.auth.identity.pangolin_header import PangolinHeaderProvider
from app.db.session import make_session_factory
from app.models.ui_session import UiSession
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.settings_store.store import SettingsStore
from tests.conftest import SESSION_URL, SETTINGS_URL, TRUST_TOKEN, put_settings

SSO = {"X-Pangolin-Token": TRUST_TOKEN, "Remote-User": "alice"}


def _problem(r: httpx.Response, status: int, error_code: str) -> None:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["error_code"] == error_code


async def _count(engine: AsyncEngine, model: type) -> int:
    async with make_session_factory(engine)() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def test_sso_header_ignored_without_trust_token(browser: httpx.AsyncClient):
    # Acceptance 3: a client can always send Remote-User; without a stored trust token it is
    # never believed, even together with a trust header.
    _problem(
        await browser.post(SESSION_URL, headers={"Remote-User": "alice"}), 401, "not_authenticated"
    )
    _problem(await browser.post(SESSION_URL, headers=SSO), 401, "not_authenticated")
    assert "set-cookie" not in (await browser.post(SESSION_URL, headers=SSO)).headers


async def test_sso_header_ignored_with_wrong_trust_token(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    wrong = {"X-Pangolin-Token": "wrong-trust-token-" + "y" * 24, "Remote-User": "alice"}
    r = await browser.post(SESSION_URL, headers=wrong)
    _problem(r, 401, "not_authenticated")
    assert "set-cookie" not in r.headers
    # A prefix of the right token (different length) and the user header alone fail too.
    short = {"X-Pangolin-Token": TRUST_TOKEN[:-1], "Remote-User": "alice"}
    _problem(await browser.post(SESSION_URL, headers=short), 401, "not_authenticated")
    _problem(
        await browser.post(SESSION_URL, headers={"Remote-User": "alice"}), 401, "not_authenticated"
    )


async def test_sso_header_creates_session_with_matching_token(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    r = await browser.post(SESSION_URL, headers=SSO)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "session"
    assert body["scope"] == "admin"
    assert body["identity_provider"] == "pangolin_header"
    assert body["user"] == "alice"
    assert body["csrf_token"] == browser.cookies.get("__Host-bb_csrf")
    # The cookie alone now authenticates (no SSO headers on this request).
    me = await browser.get(SESSION_URL)
    assert me.status_code == 200, me.text
    assert me.json()["kind"] == "session"


async def test_repeated_sso_headers_are_refused(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    headers = [("X-Pangolin-Token", TRUST_TOKEN), ("Remote-User", "alice"), ("Remote-User", "eve")]
    _problem(await browser.post(SESSION_URL, headers=headers), 401, "not_authenticated")
    blank = {"X-Pangolin-Token": TRUST_TOKEN, "Remote-User": "   "}
    _problem(await browser.post(SESSION_URL, headers=blank), 401, "not_authenticated")
    too_long = {"X-Pangolin-Token": TRUST_TOKEN, "Remote-User": "a" * 257}
    _problem(await browser.post(SESSION_URL, headers=too_long), 401, "not_authenticated")


async def test_sso_header_names_follow_settings_without_restart(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    await put_settings(
        admin_client, {"sso.user_header": "Remote-Email", "sso.trust_header": "X-Other-Trust"}
    )
    _problem(await browser.post(SESSION_URL, headers=SSO), 401, "not_authenticated")
    renamed = {"X-Other-Trust": TRUST_TOKEN, "Remote-Email": "alice@example.com"}
    r = await browser.post(SESSION_URL, headers=renamed)
    assert r.status_code == 201, r.text
    assert r.json()["user"] == "alice@example.com"


async def test_disabled_identity_provider_is_not_asked(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    await put_settings(admin_client, {"auth.identity_providers": []})
    _problem(await browser.post(SESSION_URL, headers=SSO), 401, "not_authenticated")
    _problem(await browser.get("/auth/continue", headers=SSO), 401, "not_authenticated")
    await put_settings(admin_client, {"auth.identity_providers": ["pangolin_header"]})
    assert (await browser.post(SESSION_URL, headers=SSO)).status_code == 201


async def test_unknown_identity_provider_kind_422(admin_client: httpx.AsyncClient):
    r = await admin_client.put(SETTINGS_URL, json={"values": {"auth.identity_providers": ["oidc"]}})
    _problem(r, 422, "invalid_setting_value")
    assert "oidc" not in r.text
    for bad in (["pangolin_header", "pangolin_header"], "pangolin_header", [1]):
        r = await admin_client.put(SETTINGS_URL, json={"values": {"auth.identity_providers": bad}})
        _problem(r, 422, "invalid_setting_value")
    listed = {s["key"]: s for s in (await admin_client.get(SETTINGS_URL)).json()}
    assert listed["auth.identity_providers"]["value"] == ["pangolin_header"]


class _HeaderProvider:
    """Test provider: trusts ``X-Test-Subject`` (only ever registered inside a test)."""

    kind: ClassVar[str] = "test_header"

    async def identify(self, request: Request, store: SettingsStore) -> Identity | None:
        subject = request.headers.get("X-Test-Subject")
        if not subject:
            return None
        return Identity(subject=subject, provider=self.kind, scopes=frozenset({"operate"}))

    def session_binding(self, store: SettingsStore) -> str | None:
        return "static-test-binding"


@pytest.fixture
def test_provider():
    provider = registry.register(_HeaderProvider())
    try:
        yield provider
    finally:
        registry.unregister(provider.kind)


async def test_routes_use_registry_not_provider(
    monkeypatch: pytest.MonkeyPatch,
    test_provider: _HeaderProvider,
    browser: httpx.AsyncClient,
    admin_client: httpx.AsyncClient,
    engine: AsyncEngine,
):
    asked: list[str] = []

    async def spy(self: PangolinHeaderProvider, request: Request, store: SettingsStore) -> None:
        asked.append("pangolin_header")

    monkeypatch.setattr(PangolinHeaderProvider, "identify", spy)
    await put_settings(admin_client, {"auth.identity_providers": ["test_header"]})
    r = await browser.get("/auth/continue?next=/printers", headers={"X-Test-Subject": "bob"})
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/printers"
    assert asked == []  # the inactive built-in provider was not asked
    async with make_session_factory(engine)() as session:
        row = await session.scalar(select(UiSession))
        assert row is not None
        assert (row.identity_provider, row.identity_subject) == ("test_header", "bob")
        assert row.scope == "operate"  # capped by what the identity grants
        link = await session.scalar(select(UserIdentity))
        assert link is not None
        assert (link.provider, link.subject, link.user_id) == ("test_header", "bob", row.user_id)
    me = await browser.get("/api/v1/auth/session")
    assert me.json()["identity_provider"] == "test_header"


async def test_sso_identity_linked_once_to_admin_user(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient, engine: AsyncEngine
):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    for _ in range(2):
        assert (await browser.post(SESSION_URL, headers=SSO)).status_code == 201
    async with make_session_factory(engine)() as session:
        links = (await session.scalars(select(UserIdentity))).all()
        assert [(i.provider, i.subject) for i in links] == [("pangolin_header", "alice")]
        users = {u.id: u.display_name for u in (await session.scalars(select(User))).all()}
        assert list(users.values()) == ["admin"]
        sessions = (await session.scalars(select(UiSession))).all()
        assert len(sessions) == 2
        assert {s.user_id for s in sessions} == {links[0].user_id}


async def test_sso_session_ends_when_trust_token_rotated_or_provider_disabled(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient
):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    assert (await browser.post(SESSION_URL, headers=SSO)).status_code == 201
    assert (await browser.get(SESSION_URL)).status_code == 200
    await put_settings(admin_client, {"auth.identity_providers": []})
    _problem(await browser.get(SESSION_URL), 401, "invalid_session")
    await put_settings(admin_client, {"auth.identity_providers": ["pangolin_header"]})
    assert (await browser.get(SESSION_URL)).status_code == 200
    await put_settings(admin_client, {"sso.trust_token": "rotated-trust-token-" + "z" * 20})
    _problem(await browser.get(SESSION_URL), 401, "invalid_session")
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    assert (await browser.get(SESSION_URL)).status_code == 200
    await put_settings(admin_client, {"sso.trust_token": None})
    _problem(await browser.get(SESSION_URL), 401, "invalid_session")


async def test_sso_sign_in_for_disabled_admin_401(
    browser: httpx.AsyncClient, admin_client: httpx.AsyncClient, engine: AsyncEngine
):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    async with make_session_factory(engine)() as session:
        admin = await session.scalar(select(User))
        assert admin is not None
        admin.enabled = False
        await session.commit()
    _problem(await browser.post(SESSION_URL, headers=SSO), 401, "user_disabled")
    assert await _count(engine, UiSession) == 0
