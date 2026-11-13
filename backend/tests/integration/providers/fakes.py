"""Provider types for tests: hanging, failing and recording ones."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from typing import Any, ClassVar

from app.providers.base import (
    ActionDef,
    ProbeResult,
    ProviderContext,
    ProviderStatus,
    ProviderStatusState,
)

_OBJECT = {"type": "object", "properties": {}, "additionalProperties": False}


class _Base:
    kind: ClassVar[str] = "integration"
    type_name: ClassVar[str] = "fake"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "default": "x"},
            "host": {"type": "string", "default": "a.example", "x-binds-secrets": True},
            "password": {"type": "string", "x-secret": True},
        },
        "additionalProperties": False,
    }
    event_types: ClassVar[list[Any]] = []
    actions: ClassVar[list[ActionDef]] = [ActionDef("echo", _OBJECT)]

    def __init__(self) -> None:
        self._state: ProviderStatusState = "stopped"
        self._since = datetime.now(UTC)
        self.ctx: ProviderContext | None = None

    def _set(self, state: ProviderStatusState) -> None:
        self._state, self._since = state, datetime.now(UTC)

    async def start(self, ctx: ProviderContext) -> None:
        self.ctx = ctx
        self._set("connected")

    async def stop(self) -> None:
        self._set("stopped")

    async def reconfigure(self, ctx: ProviderContext) -> None:
        self.ctx = ctx

    async def test_connection(self, config: dict[str, Any], secrets: dict[str, str]) -> ProbeResult:
        return ProbeResult(True, "ok", 1)

    async def run_action(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self.ctx is not None
        return {"label": self.ctx.config["label"]}

    def status(self) -> ProviderStatus:
        return ProviderStatus(self._state, None, self._since)


async def _hang(release: asyncio.Event) -> None:
    """Wait for ``release`` and ignore cancellation: a provider that does not stop."""
    while not release.is_set():
        with contextlib.suppress(asyncio.CancelledError):
            await release.wait()


class HangingStopProvider(_Base):
    type_name: ClassVar[str] = "hang_stop"
    release: ClassVar[asyncio.Event]

    async def stop(self) -> None:
        await _hang(type(self).release)


class HangingStartProvider(_Base):
    type_name: ClassVar[str] = "hang_start"
    release: ClassVar[asyncio.Event]

    async def start(self, ctx: ProviderContext) -> None:
        await _hang(type(self).release)


class FailingStartProvider(_Base):
    type_name: ClassVar[str] = "fail_start"

    async def start(self, ctx: ProviderContext) -> None:
        raise RuntimeError("the secret is " + ctx.secrets.get("password", ""))


class RecordingProvider(_Base):
    """Remembers what ``test_connection`` and ``start`` received."""

    type_name: ClassVar[str] = "recording"
    probes: ClassVar[list[tuple[dict[str, Any], dict[str, str]]]] = []
    starts: ClassVar[list[ProviderContext]] = []

    async def start(self, ctx: ProviderContext) -> None:
        type(self).starts.append(ctx)
        await super().start(ctx)

    async def test_connection(self, config: dict[str, Any], secrets: dict[str, str]) -> ProbeResult:
        type(self).probes.append((dict(config), dict(secrets)))
        # A careless provider echoing the secret: the API masks the message.
        return ProbeResult(True, "connected with " + secrets.get("password", ""), 3)

    async def run_action(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self.ctx is not None
        return {"echo": self.ctx.secrets.get("password", "")}


FAKES: tuple[type[_Base], ...] = (
    HangingStopProvider,
    HangingStartProvider,
    FailingStartProvider,
    RecordingProvider,
)
