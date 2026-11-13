"""What a provider is: the protocol every provider class implements, and its context.

A provider class is registered under a kind and a type name (see
:mod:`app.providers.registry`). The manager makes one object of it per running instance,
hands it a :class:`ProviderContext` in ``start`` and later calls ``stop``. The class
attributes describe it to the API and the web UI: ``config_schema`` (a JSON schema in the
subset of :mod:`app.providers.schema`; secret fields carry ``"x-secret": true``), the event
types it emits and the actions it offers.

Secrets reach a provider only through ``ProviderContext.secrets`` (and the ``secrets``
argument of ``test_connection``), never through ``config``. Provider code records what it
sends and receives with ``ProviderContext.record``, which masks every secret of the
instance before anything is stored.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from app.providers.manager import InstanceRecorder

ProviderKind = Literal["account", "inventory", "integration", "display"]
PROVIDER_KINDS: tuple[ProviderKind, ...] = ("account", "inventory", "integration", "display")

ProviderStatusState = Literal[
    "stopped", "starting", "connected", "disconnected", "error", "needs_secret"
]
STATUS_STATES: tuple[ProviderStatusState, ...] = (
    "stopped",
    "starting",
    "connected",
    "disconnected",
    "error",
    "needs_secret",
)


@dataclass(frozen=True)
class EventTypeDef:
    """An event type a provider emits: ``<kind>.<type_name>.<action>``."""

    name: str
    schema_version: int
    payload_schema: dict[str, Any]


@dataclass(frozen=True)
class ActionDef:
    """An action a provider offers; ``params_schema`` describes its parameters."""

    name: str
    params_schema: dict[str, Any]


@dataclass(frozen=True)
class ProbeResult:
    """The outcome of ``test_connection``. ``message`` is shown to the admin (masked)."""

    ok: bool
    message: str
    duration_ms: int


@dataclass(frozen=True)
class ProviderStatus:
    state: ProviderStatusState
    message: str | None
    since: datetime


Emit = Callable[..., Awaitable[UUID | None]]


@dataclass(frozen=True)
class ProviderContext:
    """What a running instance gets from the manager.

    ``emit(type=..., payload=..., schema_version=..., dedup_key=None, correlation_id=None)``
    writes an event of this instance (its own transaction, committed) and returns the event
    id, or ``None`` for a duplicate. Only the event types the class declares are accepted,
    and the payload is checked against their schema.

    ``record`` writes communication log entries for this instance; the instance id, the
    secret paths of the schema and every secret of the instance are already bound, so a
    provider cannot forget to have something masked.
    """

    instance_id: UUID
    config: dict[str, Any]
    secrets: dict[str, str] = field(repr=False)
    emit: Emit = field(repr=False)
    record: InstanceRecorder = field(repr=False)


@runtime_checkable
class Provider(Protocol):
    kind: ClassVar[ProviderKind]
    type_name: ClassVar[str]
    config_schema: ClassVar[dict[str, Any]]
    event_types: ClassVar[list[EventTypeDef]]
    actions: ClassVar[list[ActionDef]]

    async def start(self, ctx: ProviderContext) -> None:
        """Start working; return once running (the manager waits at most 10 s)."""

    async def stop(self) -> None:
        """Stop working and release everything (the manager waits at most 10 s)."""

    async def reconfigure(self, ctx: ProviderContext) -> None:
        """Take over a new configuration in place.

        The manager applies a change by ``stop`` and ``start`` on a new object; this is for
        providers that can change parts of their configuration without reconnecting.
        """

    async def test_connection(self, config: dict[str, Any], secrets: dict[str, str]) -> ProbeResult:
        """Try the given, possibly unsaved values; never keeps anything."""

    async def run_action(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Run a declared action with checked parameters; return a JSON object.

        The result must not echo caller input. The manager masks it with the instance's
        secrets, so an echoed parameter would tell a caller with scope ``operate`` whether a
        guess equals a stored secret (it comes back as ``***``).
        """

    def status(self) -> ProviderStatus:
        """The current state, without I/O."""
