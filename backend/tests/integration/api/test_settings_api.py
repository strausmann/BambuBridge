"""``/api/v1/settings``: listing without secrets, validated writes, the acting user."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import make_session_factory
from app.models.app_setting import AppSetting
from app.models.user import User
from tests.conftest import KEY_HEADER, SETTINGS_URL, TRUST_TOKEN, put_settings


def _problem(r: httpx.Response, status: int, error_code: str) -> None:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["error_code"] == error_code


async def test_get_settings_never_returns_secret_value(admin_client: httpx.AsyncClient):
    await put_settings(admin_client, {"sso.trust_token": TRUST_TOKEN})
    r = await admin_client.get(SETTINGS_URL)
    assert r.status_code == 200
    assert TRUST_TOKEN not in r.text  # raw response, not the parsed JSON
    listed = {s["key"]: s for s in r.json()}
    token = listed["sso.trust_token"]
    assert (token["value"], token["default"], token["set"], token["undecryptable"]) == (
        None,
        None,
        True,
        False,
    )


async def test_settings_list_describes_every_setting(admin_client: httpx.AsyncClient):
    listed = {s["key"]: s for s in (await admin_client.get(SETTINGS_URL)).json()}
    assert listed["sso.user_header"]["choices"] == ["Remote-User", "Remote-User-Id", "Remote-Email"]
    providers = listed["auth.identity_providers"]
    assert (providers["type"], providers["value"], providers["set"]) == (
        "choices",
        ["pangolin_header"],
        False,
    )
    assert "pangolin_header" in providers["choices"]
    assert listed["retention.events_days"]["value"] == 90


async def test_put_user_header_outside_choices_422(admin_client: httpx.AsyncClient):
    r = await admin_client.put(
        SETTINGS_URL, json={"values": {"sso.user_header": "X-Forwarded-User"}}
    )
    _problem(r, 422, "invalid_setting_value")
    assert "X-Forwarded-User" not in r.text
    listed = {s["key"]: s for s in (await admin_client.get(SETTINGS_URL)).json()}
    assert listed["sso.user_header"]["value"] == "Remote-User"


async def test_put_invalid_secret_never_echoes_it(admin_client: httpx.AsyncClient):
    bad = "short-secret"
    r = await admin_client.put(SETTINGS_URL, json={"values": {"sso.trust_token": bad}})
    _problem(r, 422, "invalid_setting_value")
    assert bad not in r.text


async def test_put_unknown_setting_422_without_echo(admin_client: httpx.AsyncClient):
    r = await admin_client.put(
        SETTINGS_URL, json={"values": {"evil.<script>": 1, "retention.events_days": 7}}
    )
    _problem(r, 422, "unknown_setting")
    assert "evil" not in r.text
    listed = {s["key"]: s for s in (await admin_client.get(SETTINGS_URL)).json()}
    assert listed["retention.events_days"]["value"] == 90  # all-or-nothing


async def test_put_body_shape_is_validated(admin_client: httpx.AsyncClient):
    _problem(
        await admin_client.put(SETTINGS_URL, json={"retention.events_days": 7}),
        422,
        "validation_failed",
    )
    _problem(await admin_client.put(SETTINGS_URL, json={"values": [1]}), 422, "validation_failed")


async def test_put_records_the_acting_user(admin_client: httpx.AsyncClient, engine: AsyncEngine):
    await put_settings(admin_client, {"retention.events_days": 7, "sso.trust_token": TRUST_TOKEN})
    async with make_session_factory(engine)() as session:
        admin = await session.scalar(select(User))
        assert admin is not None
        rows = (await session.scalars(select(AppSetting).order_by(AppSetting.key))).all()
        assert {(r.key, r.updated_by) for r in rows} == {
            ("retention.events_days", admin.id),
            ("sso.trust_token", admin.id),
        }


async def test_put_none_resets_to_default(admin_client: httpx.AsyncClient):
    await put_settings(admin_client, {"retention.events_days": 7})
    await put_settings(admin_client, {"retention.events_days": None})
    listed = {s["key"]: s for s in (await admin_client.get(SETTINGS_URL)).json()}
    assert (listed["retention.events_days"]["value"], listed["retention.events_days"]["set"]) == (
        90,
        False,
    )


async def test_settings_need_admin(client: httpx.AsyncClient, operate_token: str):
    _problem(await client.get(SETTINGS_URL), 401, "not_authenticated")
    headers = {KEY_HEADER: operate_token}
    _problem(await client.get(SETTINGS_URL, headers=headers), 403, "insufficient_scope")
    r = await client.put(SETTINGS_URL, json={"values": {}}, headers=headers)
    _problem(r, 403, "insufficient_scope")
