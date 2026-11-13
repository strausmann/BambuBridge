"""``/api/v1/provider-types`` and ``/api/v1/providers``: scopes, validation, secrets."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import make_session_factory
from app.models.provider_instance import ProviderInstance
from app.models.user import User
from tests.conftest import KEY_HEADER
from tests.integration.providers import fakes
from tests.integration.providers.conftest import (  # noqa: F401  (fixtures)
    PROVIDERS_URL,
    admin_token,
    create,
    current_partitions,
    eventually,
    fake_types,
    manager,
    state_of,
)

TYPES_URL = "/api/v1/provider-types"
TOKEN = "demo-token-0123456789abc"
PASSWORD = "stored-password-987654"


def _problem(r: httpx.Response, status: int, error_code: str) -> dict[str, Any]:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    body: dict[str, Any] = r.json()
    assert body["error_code"] == error_code
    return body


async def _demo(client: httpx.AsyncClient, name: str = "demo") -> dict[str, Any]:
    return await create(
        client,
        kind="integration",
        type_name="demo",
        name=name,
        config={"interval_seconds": 60, "label": "l", "token": TOKEN},
    )


async def test_provider_types_describe_schema_events_and_actions(
    client: httpx.AsyncClient, read_token: str
):
    r = await client.get(TYPES_URL, headers={KEY_HEADER: read_token})
    assert r.status_code == 200
    demo = next(t for t in r.json() if (t["kind"], t["type_name"]) == ("integration", "demo"))
    props = demo["config_schema"]["properties"]
    assert props["interval_seconds"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 3600,
        "default": 30,
        "title": "Interval (seconds)",
    }
    assert props["token"]["x-secret"] is True
    assert demo["event_types"] == [
        {
            "name": "integration.demo.tick",
            "schema_version": 1,
            "payload_schema": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "sequence": {"type": "integer"}},
                "required": ["label", "sequence"],
                "additionalProperties": False,
            },
        }
    ]
    assert demo["actions"][0]["name"] == "emit_now"
    assert demo["actions"][0]["params_schema"]["properties"]["label"]["type"] == "string"


async def test_crud_roundtrip_records_the_acting_user(
    admin_client: httpx.AsyncClient, engine: AsyncEngine
):
    created = await _demo(admin_client)
    assert created["kind"] == "integration"
    assert created["enabled"] is True
    assert created["config"] == {"interval_seconds": 60, "label": "l"}
    assert created["secrets"] == {"token": {"set": True}}
    assert created["status"]["state"] == "stopped"
    iid = created["id"]

    listed = (await admin_client.get(PROVIDERS_URL)).json()
    assert [i["id"] for i in listed] == [iid]

    r = await admin_client.patch(
        f"{PROVIDERS_URL}/{iid}", json={"name": "renamed", "config": {"label": "m"}}
    )
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["config"]["label"]) == ("renamed", "m")
    assert r.json()["config"]["interval_seconds"] == 60  # merged, not replaced
    assert r.json()["secrets"] == {"token": {"set": True}}

    async with make_session_factory(engine)() as session:
        admin = await session.scalar(select(User))
        row = await session.get(ProviderInstance, uuid.UUID(iid))
        assert admin is not None and row is not None
        assert (row.created_by, row.updated_by) == (admin.id, admin.id)
        assert set(row.secrets) == {"token"}
        assert "token" not in row.config  # secrets never land in the plain config
        assert TOKEN not in str(row.secrets)

    assert (await admin_client.delete(f"{PROVIDERS_URL}/{iid}")).status_code == 204
    _problem(await admin_client.get(f"{PROVIDERS_URL}/{iid}"), 404, "provider_not_found")
    _problem(await admin_client.delete(f"{PROVIDERS_URL}/{iid}"), 404, "provider_not_found")


@pytest.mark.usefixtures("manager")
async def test_provider_api_never_returns_secret_values(admin_client: httpx.AsyncClient):
    secret = TOKEN.encode()
    r = await admin_client.post(
        PROVIDERS_URL,
        json={
            "kind": "integration",
            "type_name": "demo",
            "name": "secretive",
            "config": {"interval_seconds": 60, "label": "l", "token": TOKEN},
        },
    )
    assert r.status_code == 201
    responses = [r]
    iid = r.json()["id"]
    await eventually(lambda: state_of(admin_client, iid), lambda s: s["state"] == "connected", 5)
    responses.append(await admin_client.get(PROVIDERS_URL))
    responses.append(await admin_client.get(f"{PROVIDERS_URL}/{iid}"))
    responses.append(await admin_client.patch(f"{PROVIDERS_URL}/{iid}", json={"name": "x"}))
    responses.append(await admin_client.post(f"{PROVIDERS_URL}/{iid}/test", json={}))
    responses.append(await admin_client.get(TYPES_URL))
    responses.append(
        await admin_client.post(f"{PROVIDERS_URL}/{iid}/actions/emit_now", json={"params": {}})
    )
    for resp in responses:
        assert resp.status_code in (200, 201), resp.text
        assert secret not in resp.content  # raw bytes, not the parsed JSON


async def test_create_validates_type_name_and_config(admin_client: httpx.AsyncClient):
    body = {"kind": "integration", "type_name": "missing", "name": "x", "config": {}}
    _problem(await admin_client.post(PROVIDERS_URL, json=body), 404, "provider_type_not_found")
    body = {
        "kind": "integration",
        "type_name": "demo",
        "name": "x",
        "config": {"interval_seconds": 0, "token": "hidden-value-123"},
    }
    problem = _problem(
        await admin_client.post(PROVIDERS_URL, json=body), 422, "invalid_provider_config"
    )
    assert "interval_seconds" in problem["detail"]
    body["config"] = {"interval_seconds": "hidden-value-123", "token": TOKEN}
    r = await admin_client.post(PROVIDERS_URL, json=body)
    _problem(r, 422, "invalid_provider_config")
    assert b"hidden-value-123" not in r.content
    _problem(
        await admin_client.post(PROVIDERS_URL, json={**body, "name": " "}),
        422,
        "validation_failed",
    )
    await _demo(admin_client, "taken")
    _problem(await _post_demo(admin_client, "taken"), 409, "provider_name_taken")


async def _post_demo(client: httpx.AsyncClient, name: str) -> httpx.Response:
    return await client.post(
        PROVIDERS_URL,
        json={"kind": "integration", "type_name": "demo", "name": name, "config": {"token": TOKEN}},
    )


async def test_rename_to_a_taken_name_is_409(admin_client: httpx.AsyncClient):
    await _demo(admin_client, "a")
    b = await _demo(admin_client, "b")
    r = await admin_client.patch(f"{PROVIDERS_URL}/{b['id']}", json={"name": "a"})
    _problem(r, 409, "provider_name_taken")


async def test_patch_validates_config(admin_client: httpx.AsyncClient):
    created = await _demo(admin_client)
    r = await admin_client.patch(f"{PROVIDERS_URL}/{created['id']}", json={"config": {"label": 5}})
    _problem(r, 422, "invalid_provider_config")
    r = await admin_client.patch(f"{PROVIDERS_URL}/{created['id']}", json={"config": {"nope": 1}})
    _problem(r, 422, "invalid_provider_config")
    r = await admin_client.patch(f"{PROVIDERS_URL}/{uuid.uuid4()}", json={"name": "z"})
    _problem(r, 404, "provider_not_found")


async def test_test_endpoint_uses_unsaved_values_and_keeps_stored_secret(
    admin_client: httpx.AsyncClient, engine: AsyncEngine
):
    created = await create(
        admin_client,
        kind="integration",
        type_name="recording",
        name="probe",
        config={"label": "stored", "password": PASSWORD},
    )
    r = await admin_client.post(
        f"{PROVIDERS_URL}/{created['id']}/test",
        json={"config": {"label": "unsaved", "password": ""}},
    )
    assert r.status_code == 200, r.text
    config, secrets = fakes.RecordingProvider.probes[-1]
    assert config["label"] == "unsaved"
    assert secrets == {"password": PASSWORD}
    body = r.json()
    assert (body["ok"], body["duration_ms"]) == (True, 3)
    # The provider echoed the secret into its message; the API masks it.
    assert body["message"] == "connected with ***"
    assert PASSWORD.encode() not in r.content
    # Nothing was saved.
    async with make_session_factory(engine)() as session:
        row = await session.get(ProviderInstance, uuid.UUID(created["id"]))
        assert row is not None and row.config["label"] == "stored"

    # Without a body the stored values are tested.
    r = await admin_client.post(f"{PROVIDERS_URL}/{created['id']}/test")
    assert r.status_code == 200
    assert fakes.RecordingProvider.probes[-1] == (
        {"label": "stored", "host": "a.example"},
        {"password": PASSWORD},
    )


async def test_test_endpoint_refuses_stored_secret_for_another_host(
    admin_client: httpx.AsyncClient,
):
    created = await create(
        admin_client,
        kind="integration",
        type_name="recording",
        name="bound",
        config={"host": "a.example", "password": PASSWORD},
    )
    url = f"{PROVIDERS_URL}/{created['id']}/test"
    problem = _problem(
        await admin_client.post(url, json={"config": {"host": "evil.example"}}),
        422,
        "secret_required",
    )
    assert "password" in problem["detail"]
    assert fakes.RecordingProvider.probes == []
    _problem(
        await admin_client.patch(
            f"{PROVIDERS_URL}/{created['id']}", json={"config": {"host": "evil.example"}}
        ),
        422,
        "secret_required",
    )
    r = await admin_client.post(
        url, json={"config": {"host": "b.example", "password": "fresh-password-1234"}}
    )
    assert r.status_code == 200
    assert fakes.RecordingProvider.probes[-1][1] == {"password": "fresh-password-1234"}


async def test_type_test_endpoint_takes_unsaved_values(admin_client: httpx.AsyncClient):
    url = f"{TYPES_URL}/integration/demo/test"
    ok = await admin_client.post(url, json={"config": {"token": TOKEN}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["ok"] is True
    problem = _problem(
        await admin_client.post(url, json={"config": {"token": ""}}),
        422,
        "invalid_provider_config",
    )
    assert "token" in problem["detail"]
    _problem(
        await admin_client.post(url, json={"config": {"interval_seconds": -1}}),
        422,
        "invalid_provider_config",
    )
    _problem(
        await admin_client.post(f"{TYPES_URL}/integration/none/test", json={"config": {}}),
        404,
        "provider_type_not_found",
    )


@pytest.mark.usefixtures("manager")
async def test_action_requires_operate_scope(
    client: httpx.AsyncClient, admin_client: httpx.AsyncClient, read_token: str, operate_token: str
):
    created = await _demo(admin_client)
    await eventually(
        lambda: state_of(admin_client, created["id"]), lambda s: s["state"] == "connected", 5
    )
    url = f"{PROVIDERS_URL}/{created['id']}/actions/emit_now"
    _problem(
        await client.post(url, json={"params": {}}, headers={KEY_HEADER: read_token}),
        403,
        "insufficient_scope",
    )
    r = await client.post(
        url, json={"params": {"label": "op"}}, headers={KEY_HEADER: operate_token}
    )
    assert r.status_code == 200, r.text
    assert set(r.json()["result"]) == {"sequence"}
    assert b"op" not in r.content.replace(b"operate", b"")


@pytest.mark.usefixtures("manager")
async def test_action_errors(admin_client: httpx.AsyncClient):
    created = await _demo(admin_client)
    base = f"{PROVIDERS_URL}/{created['id']}/actions"
    await eventually(
        lambda: state_of(admin_client, created["id"]), lambda s: s["state"] == "connected", 5
    )
    _problem(await admin_client.post(f"{base}/nope", json={"params": {}}), 404, "unknown_action")
    _problem(
        await admin_client.post(f"{base}/emit_now", json={"params": {"label": 1}}),
        422,
        "invalid_action_params",
    )
    await admin_client.patch(f"{PROVIDERS_URL}/{created['id']}", json={"enabled": False})
    await eventually(
        lambda: state_of(admin_client, created["id"]), lambda s: s["state"] == "stopped", 5
    )
    _problem(
        await admin_client.post(f"{base}/emit_now", json={"params": {}}),
        409,
        "provider_not_running",
    )
    _problem(
        await admin_client.post(
            f"{PROVIDERS_URL}/{uuid.uuid4()}/actions/emit_now", json={"params": {}}
        ),
        404,
        "provider_not_found",
    )


@pytest.mark.usefixtures("manager")
async def test_action_result_is_masked(admin_client: httpx.AsyncClient):
    created = await create(
        admin_client,
        kind="integration",
        type_name="recording",
        name="echo",
        config={"password": PASSWORD},
    )
    await eventually(
        lambda: state_of(admin_client, created["id"]), lambda s: s["state"] == "connected", 5
    )
    r = await admin_client.post(
        f"{PROVIDERS_URL}/{created['id']}/actions/echo", json={"params": {}}
    )
    assert r.status_code == 200
    assert r.json()["result"] == {"echo": "***"}
    assert PASSWORD.encode() not in r.content


@pytest.mark.parametrize(
    ("method", "path", "need"),
    [
        ("get", TYPES_URL, "read"),
        ("get", PROVIDERS_URL, "read"),
        ("post", PROVIDERS_URL, "admin"),
        ("post", f"{TYPES_URL}/integration/demo/test", "admin"),
    ],
)
async def test_routes_need_their_scope(
    client: httpx.AsyncClient,
    read_token: str,
    operate_token: str,
    method: str,
    path: str,
    need: str,
):
    _problem(await client.request(method, path, json={}), 401, "not_authenticated")
    if need == "admin":
        r = await client.request(method, path, json={}, headers={KEY_HEADER: operate_token})
        _problem(r, 403, "insufficient_scope")
    else:
        r = await client.request(method, path, headers={KEY_HEADER: read_token})
        assert r.status_code == 200


async def test_instance_routes_need_admin_to_change(
    client: httpx.AsyncClient, admin_client: httpx.AsyncClient, read_token: str, operate_token: str
):
    created = await _demo(admin_client)
    url = f"{PROVIDERS_URL}/{created['id']}"
    assert (await client.get(url, headers={KEY_HEADER: read_token})).status_code == 200
    for method in ("patch", "delete"):
        r = await client.request(method, url, json={}, headers={KEY_HEADER: operate_token})
        _problem(r, 403, "insufficient_scope")
    r = await client.post(f"{url}/test", json={}, headers={KEY_HEADER: operate_token})
    _problem(r, 403, "insufficient_scope")


async def test_patch_with_empty_secret_keeps_it_and_null_clears_an_optional_one(
    admin_client: httpx.AsyncClient,
):
    created = await create(
        admin_client,
        kind="integration",
        type_name="recording",
        name="optional",
        config={"password": PASSWORD},
    )
    url = f"{PROVIDERS_URL}/{created['id']}"
    r = await admin_client.patch(url, json={"config": {"password": ""}})
    assert r.json()["secrets"] == {"password": {"set": True}}
    r = await admin_client.patch(url, json={"config": {"password": None}})
    assert r.json()["secrets"] == {"password": {"set": False}}


async def test_invalid_instance_id_is_422(admin_client: httpx.AsyncClient):
    _problem(await admin_client.get(f"{PROVIDERS_URL}/not-a-uuid"), 422, "validation_failed")


async def test_short_secret_is_refused(admin_client: httpx.AsyncClient):
    # Shorter than the masker's MIN_KNOWN_SECRET_LENGTH, it could not be masked by value.
    short = "seven77"
    body = {"kind": "integration", "type_name": "demo", "name": "s", "config": {"token": short}}
    problem = _problem(
        await admin_client.post(PROVIDERS_URL, json=body), 422, "invalid_provider_config"
    )
    assert "token" in problem["detail"] and short not in problem["detail"]
    r = await admin_client.post(
        f"{TYPES_URL}/integration/demo/test", json={"config": body["config"]}
    )
    _problem(r, 422, "invalid_provider_config")
    created = await _demo(admin_client)
    r = await admin_client.post(
        f"{PROVIDERS_URL}/{created['id']}/test", json={"config": body["config"]}
    )
    _problem(r, 422, "invalid_provider_config")


async def test_huge_integer_is_422_not_500(admin_client: httpx.AsyncClient):
    # 1 followed by 400 zeros, as JSON text (too large for a float).
    config = {"token": TOKEN, "interval_seconds": 10**400}
    content = json.dumps(
        {"kind": "integration", "type_name": "demo", "name": "big", "config": config}
    )
    r = await admin_client.post(
        PROVIDERS_URL, content=content, headers={"content-type": "application/json"}
    )
    assert r.status_code == 422, r.text


@pytest.mark.parametrize("padding", [" ", "​", "͏"])
async def test_padded_short_secret_is_refused_and_never_logged(
    admin_client: httpx.AsyncClient, engine: AsyncEngine, padding: str
):
    from sqlalchemy import func

    from app.models.communication_entry import CommunicationEntry

    core = "abc1234"  # 7 characters
    value = padding * 2 + core + padding * 2
    body = {"kind": "integration", "type_name": "demo", "name": "pad", "config": {"token": value}}
    r = await admin_client.post(PROVIDERS_URL, json=body)
    _problem(r, 422, "invalid_provider_config")
    assert core.encode() not in r.content
    r = await admin_client.post(
        f"{TYPES_URL}/integration/demo/test", json={"config": body["config"]}
    )
    _problem(r, 422, "invalid_provider_config")
    async with make_session_factory(engine)() as session:
        assert await session.scalar(select(func.count()).select_from(ProviderInstance)) == 0
        assert await session.scalar(select(func.count()).select_from(CommunicationEntry)) == 0
