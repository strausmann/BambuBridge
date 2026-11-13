"""ProviderManager edge cases: probes, actions and emitting outside the declared types."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import make_session_factory
from app.providers.base import ProbeResult, ProviderContext
from app.providers.demo.provider import DemoProvider
from app.providers.manager import (
    ActionFailedError,
    ActionTimeoutError,
    ProviderManager,
    ProviderNotRunningError,
    UnknownActionError,
)
from app.providers.schema import ValidationError
from app.repositories import provider_instances as repo
from tests.integration.providers import fakes


class _Odd(fakes.RecordingProvider):
    type_name: ClassVar[str] = "odd"
    mode: ClassVar[str] = "ok"

    async def test_connection(self, config: dict[str, Any], secrets: dict[str, str]) -> ProbeResult:
        if type(self).mode == "slow":
            await asyncio.sleep(5)
        if type(self).mode == "raise":
            raise RuntimeError(secrets.get("password", ""))
        if type(self).mode == "wrong":
            return "yes"  # type: ignore[return-value]
        return await super().test_connection(config, secrets)

    async def run_action(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        if type(self).mode == "slow":
            await asyncio.sleep(5)
        if type(self).mode == "raise":
            raise KeyError("x")
        if type(self).mode == "wrong":
            return ["no"]  # type: ignore[return-value]
        return await super().run_action(name, params)


@pytest.fixture
def mgr(app: FastAPI) -> ProviderManager:
    app.state.provider_registry.register(_Odd)
    manager: ProviderManager = app.state.provider_manager
    manager.step_timeout = 0.3
    return manager


async def _instance(engine: AsyncEngine, app: FastAPI, type_name: str = "odd") -> uuid.UUID:
    async with make_session_factory(engine)() as session:
        row = await repo.create(
            session,
            app.state.secret_box,
            kind="integration",
            type_name=type_name,
            name=f"edge {uuid.uuid4()}",
            enabled=True,
            config={},
            secrets={"password": "edge-password-123456"},
            user_id=None,
        )
        await session.commit()
    return row.id


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("slow", "the test did not finish in time"),
        ("raise", "test failed (RuntimeError)"),
        ("wrong", "test failed (str)"),
    ],
)
async def test_probe_failures_are_reported_without_values(
    mgr: ProviderManager, mode: str, message: str
):
    _Odd.mode = mode
    result = await mgr.probe(_Odd, {}, {"password": "edge-password-123456"})
    assert (result.ok, result.message) == (False, message)


@pytest.mark.parametrize(
    ("mode", "error"),
    [("slow", ActionTimeoutError), ("raise", ActionFailedError), ("wrong", ActionFailedError)],
)
async def test_action_failures(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI, mode: str, error: type[Exception]
):
    _Odd.mode = "ok"
    iid = await _instance(engine, app)
    await mgr.apply(iid)
    try:
        _Odd.mode = mode
        with pytest.raises(error):
            await mgr.run_action(iid, "echo", {})
        with pytest.raises(UnknownActionError):
            await mgr.run_action(iid, "nope", {})
        with pytest.raises(ValidationError):
            await mgr.run_action(iid, "echo", {"extra": 1})
    finally:
        _Odd.mode = "ok"
        await mgr.stop()
    with pytest.raises(ProviderNotRunningError):
        await mgr.run_action(iid, "echo", {})


async def test_emit_refuses_undeclared_types_and_bad_payloads(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    iid = await _instance(engine, app, "recording")
    await mgr.apply(iid)
    try:
        ctx: ProviderContext = fakes.RecordingProvider.starts[-1]
        with pytest.raises(ValueError, match="does not declare"):
            await ctx.emit(type="integration.recording.other", payload={}, schema_version=1)
        demo_emit = mgr._emitter(iid, DemoProvider)
        with pytest.raises(ValueError, match="does not declare"):
            await demo_emit(type="integration.demo.tick", payload={}, schema_version=2)
        with pytest.raises(ValueError, match="payload"):
            await demo_emit(type="integration.demo.tick", payload={"label": 1}, schema_version=1)
        event_id = await demo_emit(
            type="integration.demo.tick", payload={"label": "a", "sequence": 1}, schema_version=1
        )
        assert event_id is not None
    finally:
        await mgr.stop()


async def test_invalid_stored_config_reports_error(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    iid = await _instance(engine, app, "recording")
    async with make_session_factory(engine)() as session:
        row = await repo.get(session, iid, for_update=True)
        assert row is not None
        row.config = {"label": 7}
        await session.commit()
    await mgr.apply(iid)
    status = mgr.status(iid)
    assert status is not None
    assert (status.state, status.message) == ("error", "stored configuration is invalid (label)")


async def test_missing_required_secret_reports_needs_secret(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    async with make_session_factory(engine)() as session:
        row = await repo.create(
            session,
            app.state.secret_box,
            kind="integration",
            type_name="demo",
            name="no token",
            enabled=True,
            config={},
            secrets={},
            user_id=None,
        )
        await session.commit()
    await mgr.apply(row.id)
    status = mgr.status(row.id)
    assert status is not None
    assert (status.state, status.message) == ("needs_secret", "secret is missing: token")
