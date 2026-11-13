"""``integration/demo``: ticks on an interval, so the whole chain can be watched working.

Every ``interval_seconds`` it emits ``integration.demo.tick`` (payload ``{label, sequence}``,
``dedup_key`` = the sequence) and records a pseudo call ``GET demo://tick?token=<token>``
in the communication log. The pseudo peer echoes the token in its answer under a name no
masking rule knows, so the log shows masking by name (the query) and by value (the answer)
end to end. The action ``emit_now`` emits one tick at once (optionally with another label)
and returns only its ``sequence``.

It is shipped in the image; no instance is created by default.

The sequence keeps rising across restarts of an instance: it starts at the current time in
milliseconds and continues from the last value of the instance in this process. A restart
within the deduplication window therefore never repeats a dedup key (which would drop the
tick as a duplicate).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import quote

from app.events.communication import Message
from app.providers.base import (
    ActionDef,
    EventTypeDef,
    ProbeResult,
    ProviderContext,
    ProviderKind,
    ProviderStatus,
    ProviderStatusState,
)

EVENT_TYPE = "integration.demo.tick"

_log = logging.getLogger(__name__)


class DemoProvider:
    kind: ClassVar[ProviderKind] = "integration"
    type_name: ClassVar[str] = "demo"
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "title": "Demo",
        "properties": {
            "interval_seconds": {
                "type": "integer",
                "minimum": 1,
                "maximum": 3600,
                "default": 30,
                "title": "Interval (seconds)",
            },
            "label": {
                "type": "string",
                "minLength": 1,
                "maxLength": 100,
                "default": "demo",
                "title": "Label",
            },
            "token": {
                "type": "string",
                "x-secret": True,
                "minLength": 8,
                "maxLength": 512,
                "title": "Token",
            },
        },
        "required": ["token"],
        "additionalProperties": False,
    }
    event_types: ClassVar[list[EventTypeDef]] = [
        EventTypeDef(
            EVENT_TYPE,
            1,
            {
                "type": "object",
                "properties": {"label": {"type": "string"}, "sequence": {"type": "integer"}},
                "required": ["label", "sequence"],
                "additionalProperties": False,
            },
        )
    ]
    actions: ClassVar[list[ActionDef]] = [
        ActionDef(
            "emit_now",
            {
                "type": "object",
                "properties": {"label": {"type": "string", "minLength": 1, "maxLength": 100}},
                "additionalProperties": False,
            },
        )
    ]

    # The last sequence per instance in this process (see the module text).
    _last_sequence: ClassVar[dict[uuid.UUID, int]] = {}

    @classmethod
    def forget_instance(cls, instance_id: uuid.UUID) -> None:
        """The instance was deleted: drop its sequence (called by the manager)."""
        cls._last_sequence.pop(instance_id, None)

    def __init__(self) -> None:
        self._ctx: ProviderContext | None = None
        self._loop: asyncio.Task[None] | None = None
        self._status = ProviderStatus("stopped", None, datetime.now(UTC))

    def _set(self, state: ProviderStatusState, message: str | None = None) -> None:
        if (self._status.state, self._status.message) != (state, message):
            self._status = ProviderStatus(state, message, datetime.now(UTC))

    def status(self) -> ProviderStatus:
        return self._status

    async def start(self, ctx: ProviderContext) -> None:
        self._ctx = ctx
        self._loop = asyncio.create_task(self._run(), name=f"demo-{ctx.instance_id}")
        self._set("connected")

    async def stop(self) -> None:
        loop, self._loop = self._loop, None
        if loop is not None:
            loop.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop
        self._set("stopped")

    async def reconfigure(self, ctx: ProviderContext) -> None:
        await self.stop()
        await self.start(ctx)

    async def test_connection(
        self,
        config: dict[str, Any],  # noqa: ARG002  # nothing in it needs checking
        secrets: dict[str, str],
    ) -> ProbeResult:
        started = time.monotonic()
        ok = bool(secrets.get("token"))
        return ProbeResult(
            ok,
            "the token is set" if ok else "the token is empty",
            int((time.monotonic() - started) * 1000),
        )

    async def run_action(
        self,
        name: str,  # noqa: ARG002  # one action only; the manager checks the name
        params: dict[str, Any],
    ) -> dict[str, Any]:
        # The manager checks the name and the parameters against ``actions``. The result
        # never echoes the parameters (see ``Provider.run_action``).
        payload = await self._tick(params.get("label"))
        return {"sequence": payload["sequence"]}

    async def tick_once(self) -> dict[str, Any] | None:
        """One scheduled tick; a failure is reported in the status, not raised."""
        try:
            result = await self._tick(None)
        except Exception as exc:
            self._set("disconnected", f"tick failed ({type(exc).__name__})")
            return None
        self._set("connected")
        return result

    async def _run(self) -> None:
        while self._ctx is not None:
            await asyncio.sleep(int(self._ctx.config["interval_seconds"]))
            await self.tick_once()

    def _next_sequence(self, instance_id: uuid.UUID) -> int:
        last = type(self)._last_sequence.get(instance_id, 0)
        sequence = max(time.time_ns() // 1_000_000, last + 1)
        type(self)._last_sequence[instance_id] = sequence
        return sequence

    async def _tick(self, label: str | None) -> dict[str, Any]:
        ctx = self._ctx
        if ctx is None:
            raise RuntimeError("not started")
        sequence = self._next_sequence(ctx.instance_id)
        payload = {"label": label or str(ctx.config["label"]), "sequence": sequence}
        started = time.monotonic()
        await ctx.emit(type=EVENT_TYPE, payload=payload, schema_version=1, dedup_key=str(sequence))
        token = ctx.secrets.get("token", "")
        await ctx.record.record_isolated(
            method="GET",
            target=f"demo://tick?token={quote(token, safe='')}",
            status=200,
            duration_ms=int((time.monotonic() - started) * 1000),
            response=Message(
                headers={"content-type": "application/json"},
                body=json.dumps({**payload, "received": token}),
            ),
        )
        return payload
