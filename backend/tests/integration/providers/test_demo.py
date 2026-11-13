"""The demo provider: ticks, the emit_now action, the probe and the masked pseudo call."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import make_session_factory
from app.events.communication import CommunicationRecorder
from app.models.communication_entry import CommunicationEntry
from app.models.event import Event
from app.providers.base import ProviderContext
from app.providers.demo.provider import DemoProvider
from app.providers.manager import InstanceRecorder
from app.security.masking import secret_paths_from_schema
from tests.integration.providers.conftest import PROVIDERS_URL, create, eventually

TOKEN = "demo-token-abcdef123456"


async def _entries(engine: AsyncEngine, instance_id: uuid.UUID) -> list[CommunicationEntry]:
    async with make_session_factory(engine)() as session:
        return list(
            (
                await session.scalars(
                    select(CommunicationEntry).where(CommunicationEntry.instance_id == instance_id)
                )
            ).all()
        )


async def test_demo_token_masked_in_communication_log(
    admin_client: httpx.AsyncClient, manager: Any, engine: AsyncEngine
):
    created = await create(
        admin_client,
        kind="integration",
        type_name="demo",
        name="masking",
        config={"interval_seconds": 1, "label": "m", "token": TOKEN},
    )
    iid = uuid.UUID(created["id"])
    entries = await eventually(lambda: _entries(engine, iid), bool, 5)
    assert entries, "no pseudo call was recorded"
    entry = entries[0]
    assert (entry.method, entry.direction, entry.status) == ("GET", "outbound", 200)
    assert entry.target.startswith("demo://tick?")
    assert "***" in entry.target
    stored = json.dumps(
        [
            entry.target,
            entry.request_headers,
            entry.request_body,
            entry.response_headers,
            entry.response_body,
            entry.error,
        ]
    )
    assert TOKEN not in stored
    # The peer echoes the token in a field no name rule knows: only masking by value hides it.
    assert entry.response_body is not None
    assert json.loads(entry.response_body)["received"] == "***"


def _context(
    engine: AsyncEngine, events: list[dict[str, Any]], config: dict[str, Any]
) -> ProviderContext:
    instance_id = uuid.uuid4()
    sessions = make_session_factory(engine)

    async def emit(**kwargs: Any) -> uuid.UUID | None:
        events.append(kwargs)
        return uuid.uuid4()

    recorder = InstanceRecorder(
        CommunicationRecorder(),
        sessions,
        instance_id=instance_id,
        secret_paths=secret_paths_from_schema(DemoProvider.config_schema),
        known_secrets=(TOKEN,),
    )
    return ProviderContext(
        instance_id=instance_id,
        config=config,
        secrets={"token": TOKEN},
        emit=emit,
        record=recorder,
    )


async def test_emit_now_uses_the_given_label_and_a_rising_sequence(engine: AsyncEngine):
    events: list[dict[str, Any]] = []
    demo = DemoProvider()
    await demo.start(_context(engine, events, {"interval_seconds": 3600, "label": "cfg"}))
    try:
        assert demo.status().state == "connected"
        first = await demo.run_action("emit_now", {})
        second = await demo.run_action("emit_now", {"label": "given"})
    finally:
        await demo.stop()
    assert demo.status().state == "stopped"
    assert [e["payload"]["label"] for e in events] == ["cfg", "given"]
    assert events[0]["type"] == "integration.demo.tick"
    assert events[0]["schema_version"] == 1
    assert events[0]["dedup_key"] == str(events[0]["payload"]["sequence"])
    assert events[1]["payload"]["sequence"] > events[0]["payload"]["sequence"]
    # The result never echoes caller input (it would be a guess oracle against masking).
    assert first == {"sequence": events[0]["payload"]["sequence"]}
    assert second == {"sequence": events[1]["payload"]["sequence"]}


async def test_sequence_keeps_rising_across_a_restart(engine: AsyncEngine):
    # A restart within the deduplication window must not repeat a dedup key.
    events: list[dict[str, Any]] = []
    ctx = _context(engine, events, {"interval_seconds": 3600, "label": "a"})
    for _ in range(2):
        demo = DemoProvider()
        await demo.start(ctx)
        await demo.run_action("emit_now", {})
        await demo.stop()
    keys = [e["dedup_key"] for e in events]
    assert len(set(keys)) == 2
    assert int(keys[1]) > int(keys[0])


async def test_reconfigure_changes_label_in_place(engine: AsyncEngine):
    events: list[dict[str, Any]] = []
    demo = DemoProvider()
    ctx = _context(engine, events, {"interval_seconds": 3600, "label": "a"})
    await demo.start(ctx)
    try:
        ctx2 = ProviderContext(
            instance_id=ctx.instance_id,
            config={"interval_seconds": 3600, "label": "b"},
            secrets=ctx.secrets,
            emit=ctx.emit,
            record=ctx.record,
        )
        await demo.reconfigure(ctx2)
        await demo.run_action("emit_now", {})
    finally:
        await demo.stop()
    assert events[-1]["payload"]["label"] == "b"


async def test_tick_failure_marks_disconnected_and_recovers(engine: AsyncEngine):
    calls = 0

    async def flaky_emit(**kwargs: Any) -> uuid.UUID | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("database away")
        return uuid.uuid4()

    ctx = _context(engine, [], {"interval_seconds": 3600, "label": "a"})
    ctx = ProviderContext(
        instance_id=ctx.instance_id,
        config=ctx.config,
        secrets=ctx.secrets,
        emit=flaky_emit,
        record=ctx.record,
    )
    demo = DemoProvider()
    await demo.start(ctx)
    try:
        await demo.tick_once()
        assert (demo.status().state, demo.status().message) == (
            "disconnected",
            "tick failed (OSError)",
        )
        await demo.tick_once()
        assert demo.status().state == "connected"
    finally:
        await demo.stop()


async def test_test_connection_needs_a_token():
    demo = DemoProvider()
    ok = await demo.test_connection({"interval_seconds": 30, "label": "x"}, {"token": TOKEN})
    empty = await demo.test_connection({"interval_seconds": 30, "label": "x"}, {})
    assert ok.ok and not empty.ok
    assert TOKEN not in ok.message


async def test_demo_events_reach_the_events_table(
    admin_client: httpx.AsyncClient, manager: Any, engine: AsyncEngine
):
    created = await create(
        admin_client,
        kind="integration",
        type_name="demo",
        name="events",
        config={"interval_seconds": 1, "label": "e", "token": TOKEN},
    )
    iid = uuid.UUID(created["id"])

    async def events() -> list[Event]:
        async with make_session_factory(engine)() as session:
            return list(
                (await session.scalars(select(Event).where(Event.source_instance_id == iid))).all()
            )

    found = await eventually(events, bool, 5)
    assert found[0].type == "integration.demo.tick"
    assert found[0].payload["label"] == "e"
    assert found[0].dedup_key == str(found[0].payload["sequence"])
    assert found[0].occurred_at <= datetime.now(UTC)


async def test_no_demo_instance_exists_by_default(admin_client: httpx.AsyncClient):
    assert (await admin_client.get(PROVIDERS_URL)).json() == []
