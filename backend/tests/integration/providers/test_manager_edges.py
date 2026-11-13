"""ProviderManager edge cases: probes, actions and emitting outside the declared types."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import make_session_factory
from app.providers.base import EventTypeDef, ProbeResult, ProviderContext
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


SECRET = "edge-password-123456"


class _BadProbe(fakes.RecordingProvider):
    type_name: ClassVar[str] = "bad_probe"
    result: ClassVar[Any] = None

    async def test_connection(self, config: dict[str, Any], secrets: dict[str, str]) -> ProbeResult:
        return type(self).result  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    "result",
    [
        ProbeResult("yes", "m", 1),  # type: ignore[arg-type]
        ProbeResult(True, 5, 1),  # type: ignore[arg-type]
        ProbeResult(True, "m", "1"),  # type: ignore[arg-type]
        ProbeResult(True, "m", -1),
        ProbeResult(True, "m", True),  # type: ignore[arg-type]
    ],
)
async def test_probe_with_malformed_fields_is_an_error_result(
    mgr: ProviderManager, result: ProbeResult
):
    _BadProbe.result = result
    probe = await mgr.probe(_BadProbe, {}, {"password": SECRET})
    assert (probe.ok, probe.message) == (False, "test failed (invalid result)")


async def test_probe_message_is_masked_whole_then_capped(mgr: ProviderManager):
    from app.events.communication import MAX_MASK_INPUT
    from app.providers.manager import MAX_STATUS_MESSAGE_LENGTH

    _BadProbe.result = ProbeResult(True, SECRET + "z" * 1000, 2)
    probe = await mgr.probe(_BadProbe, {}, {"password": SECRET})
    assert probe.message.startswith("***")
    assert len(probe.message) <= MAX_STATUS_MESSAGE_LENGTH
    huge = SECRET + "z" * MAX_MASK_INPUT
    _BadProbe.result = ProbeResult(True, huge, 2)
    probe = await mgr.probe(_BadProbe, {}, {"password": SECRET})
    assert probe.message == f"<omitted: {len(huge)} bytes>"


async def test_masked_status_is_computed_once_per_status(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI, monkeypatch: pytest.MonkeyPatch
):
    from app.providers import manager as manager_module

    iid = await _instance(engine, app, "recording")
    await mgr.apply(iid)
    calls = 0
    real = manager_module.masker_for

    def counting(*args: Any) -> Any:
        nonlocal calls
        calls += 1
        return real(*args)

    monkeypatch.setattr(manager_module, "masker_for", counting)
    running = mgr._running[iid].provider
    running._state, running._message = "connected", f"using {SECRET}"  # type: ignore[attr-defined]
    try:
        first = [mgr.status(iid) for _ in range(5)]
        assert calls == 1
        assert first[0] is not None and first[0].message == "using ***"
        running._message = "changed"  # type: ignore[attr-defined]
        assert mgr.status(iid).message == "changed"  # type: ignore[union-attr]
        assert calls == 2
    finally:
        await mgr.stop()


class _Payloads(fakes.RecordingProvider):
    """Declares an event whose field names the masker's name rules would hide."""

    type_name: ClassVar[str] = "payloads"
    event_types: ClassVar[list[Any]] = [
        EventTypeDef(
            "integration.payloads.seen",
            1,
            {
                "type": "object",
                "properties": {
                    "session": {"type": "string"},
                    "keyframe": {"type": "integer"},
                    "print_ticket": {"type": "string"},
                },
                "additionalProperties": False,
            },
        )
    ]


async def _payloads_instance(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
) -> tuple[uuid.UUID, ProviderContext]:
    app.state.provider_registry.register(_Payloads)
    iid = await _instance(engine, app, "payloads")
    await mgr.apply(iid)
    return iid, fakes.RecordingProvider.starts[-1]


async def _stored_payloads(engine: AsyncEngine, iid: uuid.UUID) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.models.event import Event

    async with make_session_factory(engine)() as session:
        return list(
            await session.scalars(select(Event.payload).where(Event.source_instance_id == iid))
        )


async def test_event_payload_fields_with_secret_like_names_are_stored_unchanged(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    iid, ctx = await _payloads_instance(mgr, engine, app)
    payload = {"session": "s-1", "keyframe": 42, "print_ticket": "t-7"}
    try:
        assert await ctx.emit(type="integration.payloads.seen", payload=payload, schema_version=1)
    finally:
        await mgr.stop()
    assert await _stored_payloads(engine, iid) == [payload]


@pytest.mark.parametrize(
    ("payload", "dedup_key"),
    [
        ({"session": f"has {SECRET} in it"}, None),
        ({"print_ticket": SECRET.replace("-", "%2D")}, None),  # encoded
        ({"session": "fine"}, f"key-{SECRET}"),
        # Not a known secret, but credentials by their form (a provider bug): the value
        # masking still applies to payload values.
        ({"session": "Bearer abcdefgh123"}, None),
        ({"print_ticket": "token=xyz12345"}, None),
        ({"session": "https://user:pw-1234@printer.example/x"}, None),
        ({"session": "fine"}, "token=xyz12345"),
    ],
)
async def test_event_carrying_a_secret_is_rejected_and_not_stored(
    mgr: ProviderManager,
    engine: AsyncEngine,
    app: FastAPI,
    caplog: pytest.LogCaptureFixture,
    payload: dict[str, Any],
    dedup_key: str | None,
):
    from app.providers.manager import EventRejectedError

    iid, ctx = await _payloads_instance(mgr, engine, app)
    try:
        with pytest.raises(EventRejectedError):
            await ctx.emit(
                type="integration.payloads.seen",
                payload=payload,
                schema_version=1,
                dedup_key=dedup_key,
            )
        status = mgr.status(iid)
        assert status is not None
        field = "dedup_key" if dedup_key is not None else next(iter(payload))
        hint = f"event rejected: field '{field}' looks like a credential or contains a secret"
        assert status.message == hint
        assert f"field '{field}'" in caplog.text
    finally:
        await mgr.stop()
    assert await _stored_payloads(engine, iid) == []
    # Nothing of the value, neither in the status nor in the log.
    offending = dedup_key if dedup_key is not None else str(next(iter(payload.values())))
    for part in {offending[i : i + 5] for i in range(len(offending) - 4)}:
        assert part not in caplog.text, part
        assert part not in hint, part


async def test_event_payload_is_still_checked_against_its_schema(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    _iid, ctx = await _payloads_instance(mgr, engine, app)
    try:
        with pytest.raises(ValueError, match="payload"):
            await ctx.emit(
                type="integration.payloads.seen", payload={"keyframe": "x"}, schema_version=1
            )
    finally:
        await mgr.stop()


async def test_delete_forgets_per_instance_state(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    async with make_session_factory(engine)() as session:
        row = await repo.create(
            session,
            app.state.secret_box,
            kind="integration",
            type_name="demo",
            name="forgotten",
            enabled=True,
            config={"interval_seconds": 3600},
            secrets={"token": "forget-token-123456"},
            user_id=None,
        )
        await session.commit()
    await mgr.apply(row.id)
    await mgr.run_action(row.id, "emit_now", {})
    assert row.id in DemoProvider._last_sequence
    async with make_session_factory(engine)() as session:
        assert await repo.delete(session, row.id)
        await session.commit()
    await mgr.apply(row.id)
    assert mgr.status(row.id) is None
    assert row.id not in mgr._locks
    assert row.id not in mgr._applied
    assert row.id not in DemoProvider._last_sequence


class _LateStart(fakes.RecordingProvider):
    """Catches the cancellation of a timed-out start and finishes starting a bit later."""

    type_name: ClassVar[str] = "late_start"
    order: ClassVar[list[str]] = []

    async def start(self, ctx: ProviderContext) -> None:
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            await asyncio.sleep(0.2)
            type(self).order.append("started")

    async def stop(self) -> None:
        type(self).order.append("stopped")


async def test_cleanup_after_start_timeout_waits_for_the_start_to_end(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    app.state.provider_registry.register(_LateStart)
    _LateStart.order = []
    iid = await _instance(engine, app, "late_start")
    await mgr.apply(iid)
    assert mgr.status(iid).message == "timeout during start"  # type: ignore[union-attr]
    for _ in range(40):
        if len(_LateStart.order) == 2:
            break
        await asyncio.sleep(0.05)
    # stop() must not run while start() is still finishing.
    assert _LateStart.order == ["started", "stopped"]


class _SlowLateStart(fakes.RecordingProvider):
    """Finishes its start ``delay`` seconds after the cancellation; logs per object."""

    type_name: ClassVar[str] = "slow_late"
    log: ClassVar[list[tuple[int, str]]] = []
    delays: ClassVar[list[float]] = []

    async def start(self, ctx: ProviderContext) -> None:
        delay = type(self).delays.pop(0)
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            await asyncio.sleep(delay)
            type(self).log.append((id(self), "started"))

    async def stop(self) -> None:
        type(self).log.append((id(self), "stopped"))


async def test_concurrent_start_timeouts_each_stop_their_own_provider_once(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    app.state.provider_registry.register(_SlowLateStart)
    _SlowLateStart.log = []
    # The first to time out finishes its start last.
    _SlowLateStart.delays = [0.8, 0.1]
    first = await _instance(engine, app, "slow_late")
    second = await _instance(engine, app, "slow_late")
    await asyncio.gather(mgr.apply(first), mgr.apply(second))
    for _ in range(60):
        if len(_SlowLateStart.log) == 4:
            break
        await asyncio.sleep(0.05)
    per_object: dict[int, list[str]] = {}
    for obj, what in _SlowLateStart.log:
        per_object.setdefault(obj, []).append(what)
    assert len(per_object) == 2
    for events in per_object.values():
        # Stopped exactly once, and only after its own start ended.
        assert events == ["started", "stopped"], _SlowLateStart.log


class _WeirdMessage:
    """A status message whose comparison raises (provider code is not trusted)."""

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("no comparing")

    __hash__ = object.__hash__


async def test_a_status_that_cannot_be_compared_gives_a_stable_error(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    iid = await _instance(engine, app, "recording")
    await mgr.apply(iid)
    try:
        running = mgr._running[iid].provider
        running._message = _WeirdMessage()  # type: ignore[attr-defined]
        for _ in range(3):  # from the second call on, the cache is compared
            status = mgr.status(iid)
            assert status is not None
            assert (status.state, status.message) == ("error", "status failed (RuntimeError)")
    finally:
        await mgr.stop()


async def test_delete_during_a_stop_timeout_still_forgets_the_instance(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    iid = await _instance(engine, app, "hang_stop")
    await mgr.apply(iid)
    async with make_session_factory(engine)() as session:
        assert await repo.delete(session, iid)
        await session.commit()
    await mgr.apply(iid)  # the stop times out after step_timeout
    assert mgr.status(iid) is None
    assert iid not in mgr._locks
    assert iid not in mgr._applied
    assert iid not in mgr._status_cache


async def test_the_status_cache_key_holds_the_masking_inputs(mgr: ProviderManager):
    """No stop or start in between: only the key keeps an old mask from being reused."""
    from datetime import UTC, datetime

    from app.providers.base import ProviderStatus
    from app.providers.manager import _Running

    reported = ProviderStatus("connected", f"using {SECRET}", datetime.now(UTC))
    provider = fakes.RecordingProvider()
    before = _Running(provider, ("another-secret-0000",), frozenset())
    after = _Running(provider, (SECRET,), frozenset())
    iid = uuid.uuid4()
    assert mgr._clean(iid, before, reported).message == f"using {SECRET}"
    assert mgr._clean(iid, after, reported).message == "using ***"


async def test_a_start_interrupted_by_shutdown_is_stopped_before_stop_returns(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    """The listener cancels a running apply on shutdown; the start it waited for must not
    be left running without ever seeing stop()."""
    app.state.provider_registry.register(_LateStart)
    _LateStart.order = []
    mgr.step_timeout = 2.0
    iid = await _instance(engine, app, "late_start")
    job = asyncio.create_task(mgr.apply(iid))
    await asyncio.sleep(0.3)  # inside start()
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    await mgr.stop()
    # By the time stop() returns, the interrupted start has ended and been stopped.
    assert _LateStart.order == ["started", "stopped"]


async def test_a_rejected_tick_names_the_field_and_nothing_of_its_value(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI, caplog: pytest.LogCaptureFixture
):
    """A harmless label that looks like a credential: fail closed, but say where."""
    label = "Garage key: shelf 3"
    async with make_session_factory(engine)() as session:
        row = await repo.create(
            session,
            app.state.secret_box,
            kind="integration",
            type_name="demo",
            name="garage",
            enabled=True,
            config={"interval_seconds": 3600, "label": label},
            secrets={"token": "garage-token-123456"},
            user_id=None,
        )
        await session.commit()
    await mgr.apply(row.id)
    try:
        with pytest.raises(ActionFailedError):
            await mgr.run_action(row.id, "emit_now", {})
        status = mgr.status(row.id)
        assert status is not None
        assert status.message == (
            "event rejected: field 'label' looks like a credential or contains a secret"
        )
        for word in ("Garage", "shelf", "key: "):
            assert word not in status.message
            assert word not in caplog.text
    finally:
        await mgr.stop()


class _FastStart(fakes.RecordingProvider):
    """Finishes its start and, in the same step, cancels the apply that waits for it."""

    type_name: ClassVar[str] = "fast_start"
    caller: ClassVar[asyncio.Task[Any] | None] = None
    stopped: ClassVar[int] = 0

    async def start(self, ctx: ProviderContext) -> None:
        caller = type(self).caller
        if caller is not None:
            caller.cancel()

    async def stop(self) -> None:
        type(self).stopped += 1


async def test_a_start_that_finished_as_its_caller_was_cancelled_is_stopped(
    mgr: ProviderManager, engine: AsyncEngine, app: FastAPI
):
    app.state.provider_registry.register(_FastStart)
    _FastStart.stopped = 0
    iid = await _instance(engine, app, "fast_start")
    job = asyncio.create_task(mgr.apply(iid))
    _FastStart.caller = job
    with pytest.raises(asyncio.CancelledError):
        await job
    _FastStart.caller = None
    await mgr.stop()
    # It started, it is not in the running set: it must have been stopped all the same.
    assert iid not in mgr._running
    assert _FastStart.stopped == 1
