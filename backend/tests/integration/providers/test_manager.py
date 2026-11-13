"""ProviderManager: start, apply on change, timeouts, undecryptable secrets, live reload."""

from __future__ import annotations

import asyncio
import base64
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.session import make_session_factory
from app.main import create_app
from app.models.event import Event
from app.models.provider_instance import ProviderInstance
from app.providers import manager as manager_module
from app.providers.manager import ProviderManager
from tests.conftest import KEY_HEADER, settings_variant
from tests.integration.providers.conftest import (
    PROVIDERS_URL,
    create,
    eventually,
    state_of,
)

TOKEN = "demo-token-0123456789"


async def _labels(engine: AsyncEngine, instance_id: str, after: float = 0.0) -> list[str]:
    """Labels of the instance's demo events, oldest first (optionally only after a time)."""
    async with make_session_factory(engine)() as session:
        rows = (
            await session.execute(
                select(Event.payload, Event.occurred_at)
                .where(Event.source_instance_id == uuid.UUID(instance_id))
                .where(Event.type == "integration.demo.tick")
                .order_by(Event.occurred_at)
            )
        ).all()
    return [p["label"] for p, at in rows if at.timestamp() > after]


async def test_config_change_restarts_instance_without_app_restart(
    admin_client: httpx.AsyncClient, manager: ProviderManager, engine: AsyncEngine
):
    created = await create(
        admin_client,
        kind="integration",
        type_name="demo",
        name="demo one",
        config={"interval_seconds": 30, "label": "old", "token": TOKEN},
    )
    iid = created["id"]
    await eventually(lambda: state_of(admin_client, iid), lambda s: s["state"] == "connected", 5)
    action = f"{PROVIDERS_URL}/{iid}/actions/emit_now"
    assert (await admin_client.post(action, json={"params": {}})).status_code == 200
    assert (await _labels(engine, iid))[-1] == "old"

    r = await admin_client.patch(
        f"{PROVIDERS_URL}/{iid}", json={"config": {"interval_seconds": 1, "label": "new"}}
    )
    assert r.status_code == 200, r.text
    changed_at = time.time()

    # The label: what the running instance emits now. Without the restart it keeps "old".
    async def newest_after_emit() -> str | None:
        await admin_client.post(action, json={"params": {}})  # 409 while restarting
        labels = await _labels(engine, iid, after=changed_at)
        return labels[-1] if labels else None

    newest = await eventually(newest_after_emit, lambda label: label == "new", 3)
    assert newest == "new", "the running instance still emits the old label"

    # The interval: ticks of their own, one a second (with 30 s there would be none).
    quiet_from = time.time()
    await asyncio.sleep(2.6)
    ticks = await _labels(engine, iid, after=quiet_from)
    assert len(ticks) >= 2, ticks
    assert set(ticks) == {"new"}


async def test_reconfigure_times_out_hanging_stop(
    admin_client: httpx.AsyncClient, manager: ProviderManager
):
    assert manager_module.STEP_TIMEOUT_SECONDS == 10.0
    created = await create(
        admin_client, kind="integration", type_name="hang_stop", name="stuck", config={}
    )
    iid = created["id"]
    await eventually(lambda: state_of(admin_client, iid), lambda s: s["state"] == "connected", 5)

    r = await admin_client.patch(f"{PROVIDERS_URL}/{iid}", json={"config": {"label": "y"}})
    assert r.status_code == 200
    started = time.monotonic()
    slowest = 0.0
    state: dict[str, Any] = {}
    while time.monotonic() - started < 11.5:
        for path in (f"{PROVIDERS_URL}/{iid}", PROVIDERS_URL, "/api/v1/provider-types"):
            t0 = time.monotonic()
            resp = await admin_client.get(path)
            slowest = max(slowest, time.monotonic() - t0)
            assert resp.status_code == 200
        state = await state_of(admin_client, iid)
        if time.monotonic() - started < 9.0:
            assert state["state"] != "error", "gave up before the 10 s timeout"
        if state["state"] == "error":
            break
        await asyncio.sleep(0.2)
    assert slowest < 1.0, f"the API waited {slowest:.2f} s"
    assert (state["state"], state["message"]) == ("error", "timeout during stop")
    assert 9.0 <= time.monotonic() - started <= 11.5


async def test_start_timeout_reports_error(
    admin_client: httpx.AsyncClient, manager: ProviderManager
):
    manager.step_timeout = 0.5
    created = await create(
        admin_client, kind="integration", type_name="hang_start", name="slow", config={}
    )
    state = await eventually(
        lambda: state_of(admin_client, created["id"]), lambda s: s["state"] == "error", 5
    )
    assert state["message"] == "timeout during start"


async def test_start_failure_reports_the_error_class_only(
    admin_client: httpx.AsyncClient, manager: ProviderManager
):
    created = await create(
        admin_client,
        kind="integration",
        type_name="fail_start",
        name="broken",
        config={"password": "pw-never-shown-1234"},
    )
    r = await eventually(
        lambda: admin_client.get(f"{PROVIDERS_URL}/{created['id']}"),
        lambda resp: resp.json()["status"]["state"] == "error",
        5,
    )
    assert r.json()["status"]["message"] == "start failed (RuntimeError)"
    assert b"pw-never-shown-1234" not in r.content


async def test_instance_with_undecryptable_secret_reports_needs_secret(
    settings: Settings, app: FastAPI, admin_token: str, admin_client: httpx.AsyncClient
):
    created = await create(
        admin_client,
        kind="integration",
        type_name="demo",
        name="sealed elsewhere",
        enabled=True,
        config={"label": "x", "token": TOKEN},
    )
    # The same database, another BAMBUBRIDGE_SECRET_KEY: the stored token cannot be opened.
    other_key = base64.urlsafe_b64encode(b"another-secret-key-0123456789abc").decode()
    app_b = create_app(settings_variant(settings, secret_key=other_key))
    mgr_b: ProviderManager = app_b.state.provider_manager
    transport = httpx.ASGITransport(app=app_b)
    try:
        await mgr_b.start()
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers={KEY_HEADER: admin_token}
        ) as client_b:
            r = await eventually(
                lambda: client_b.get(f"{PROVIDERS_URL}/{created['id']}"),
                lambda resp: resp.json()["status"]["state"] == "needs_secret",
                5,
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"]["state"] == "needs_secret"
            assert "token" in body["status"]["message"]
            assert body["secrets"] == {"token": {"set": True}}
            listed = await client_b.get(PROVIDERS_URL)
            assert listed.status_code == 200

            # Entering the secret again under the new key brings the instance back.
            r = await client_b.patch(
                f"{PROVIDERS_URL}/{created['id']}", json={"config": {"token": TOKEN + "x"}}
            )
            assert r.status_code == 200, r.text
            await eventually(
                lambda: state_of(client_b, created["id"]),
                lambda s: s["state"] == "connected",
                5,
            )
    finally:
        await mgr_b.stop()
        await app_b.state.engine.dispose()


async def test_delete_stops_the_instance(admin_client: httpx.AsyncClient, manager: ProviderManager):
    created = await create(
        admin_client, kind="integration", type_name="recording", name="gone soon", config={}
    )
    iid = uuid.UUID(created["id"])
    await eventually(
        lambda: state_of(admin_client, created["id"]), lambda s: s["state"] == "connected", 5
    )
    assert (await admin_client.delete(f"{PROVIDERS_URL}/{iid}")).status_code == 204

    async def status() -> Any:
        return manager.status(iid)

    assert await eventually(status, lambda s: s is None, 5) is None


async def test_disabled_instance_is_stopped(
    admin_client: httpx.AsyncClient, manager: ProviderManager
):
    created = await create(
        admin_client, kind="integration", type_name="recording", name="off", config={}
    )
    await eventually(
        lambda: state_of(admin_client, created["id"]), lambda s: s["state"] == "connected", 5
    )
    await admin_client.patch(f"{PROVIDERS_URL}/{created['id']}", json={"enabled": False})
    state = await eventually(
        lambda: state_of(admin_client, created["id"]), lambda s: s["state"] == "stopped", 5
    )
    assert state["state"] == "stopped"


async def test_start_all_starts_stored_instances_and_persists_status(
    admin_client: httpx.AsyncClient, app: FastAPI, engine: AsyncEngine
):
    # Written while no manager runs: started by start_all, not by a notification.
    created = await create(
        admin_client, kind="integration", type_name="recording", name="stored", config={}
    )
    mgr: ProviderManager = app.state.provider_manager
    await mgr.start_all()
    try:
        assert mgr.status(uuid.UUID(created["id"])).state == "connected"  # type: ignore[union-attr]
        async with make_session_factory(engine)() as session:
            row = await session.get(ProviderInstance, uuid.UUID(created["id"]))
            assert row is not None
            assert (row.status, row.status_message) == ("connected", None)
    finally:
        await mgr.stop()


async def test_unregistered_type_reports_error(
    admin_client: httpx.AsyncClient, app: FastAPI, engine: AsyncEngine
):
    created = await create(
        admin_client, kind="integration", type_name="recording", name="orphan", config={}
    )
    async with make_session_factory(engine)() as session:
        await session.execute(
            update(ProviderInstance)
            .where(ProviderInstance.id == uuid.UUID(created["id"]))
            .values(type_name="removed")
        )
        await session.commit()
    mgr: ProviderManager = app.state.provider_manager
    await mgr.start_all()
    try:
        status = mgr.status(uuid.UUID(created["id"]))
        assert status is not None
        assert (status.state, status.message) == ("error", "provider type is not installed")
        r = await admin_client.get(f"{PROVIDERS_URL}/{created['id']}")
        assert r.status_code == 200
        assert r.json()["secrets"] == {}
    finally:
        await mgr.stop()


async def test_listener_reconnects_and_applies_missed_changes(
    admin_client: httpx.AsyncClient, manager: ProviderManager, engine: AsyncEngine
):
    created = await create(
        admin_client, kind="integration", type_name="recording", name="missed", config={}
    )
    iid = uuid.UUID(created["id"])
    await eventually(
        lambda: state_of(admin_client, created["id"]), lambda s: s["state"] == "connected", 5
    )
    pid = manager.listener.connection_pid
    assert pid is not None
    async with make_session_factory(engine)() as session:
        await session.execute(text("select pg_terminate_backend(:pid)"), {"pid": pid})
        # Changed without a notification: only the reload after reconnecting can see it.
        await session.execute(
            update(ProviderInstance)
            .where(ProviderInstance.id == iid)
            .values(enabled=False, updated_at=ProviderInstance.updated_at + text("interval '1s'"))
        )
        await session.commit()

    async def status() -> Any:
        return manager.status(iid)

    final = await eventually(status, lambda s: s is not None and s.state == "stopped", 8)
    assert final is not None and final.state == "stopped"
