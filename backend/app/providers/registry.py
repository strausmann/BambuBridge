"""Provider types: discovered through entry points, checked when they are registered.

Each kind has its own entry-point group, ``bambubridge.providers.<kind>``; the entry point's
name is the type name and its object the provider class::

    [project.entry-points."bambubridge.providers.integration"]
    demo = "app.providers.demo.provider:DemoProvider"

A class is checked before it is registered (its declared kind and type name, the schemas in
the subset of :mod:`app.providers.schema`, the event type names). A broken entry point or a
class that fails the check is logged and skipped: one bad plugin must not stop the bridge.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from importlib.metadata import EntryPoint, entry_points
from typing import Any

from app.events.service import EVENT_TYPE_PATTERN
from app.providers.base import PROVIDER_KINDS, Provider, ProviderKind
from app.providers.schema import SchemaDefinitionError, check_schema

ENTRY_POINT_GROUPS: dict[ProviderKind, str] = {
    kind: f"bambubridge.providers.{kind}" for kind in PROVIDER_KINDS
}
TYPE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$", re.ASCII)
ACTION_NAME_PATTERN = TYPE_NAME_PATTERN
_METHODS = ("start", "stop", "reconfigure", "test_connection", "run_action", "status")

_log = logging.getLogger(__name__)

ProviderClass = type[Provider]


class ProviderTypeError(ValueError):
    """A provider class does not describe itself correctly."""


class UnknownProviderTypeError(LookupError):
    """No provider type is registered under this kind and type name."""


def _check_class(cls: Any) -> None:
    kind = getattr(cls, "kind", None)
    if kind not in PROVIDER_KINDS:
        raise ProviderTypeError("kind must be one of " + ", ".join(PROVIDER_KINDS))
    type_name = getattr(cls, "type_name", None)
    if not isinstance(type_name, str) or not TYPE_NAME_PATTERN.fullmatch(type_name):
        raise ProviderTypeError("type_name must be lower case letters, digits and _")
    for method in _METHODS:
        if not callable(getattr(cls, method, None)):
            raise ProviderTypeError(f"the class has no method {method}")
    try:
        check_schema(getattr(cls, "config_schema", None))
    except SchemaDefinitionError as exc:
        raise ProviderTypeError(f"config_schema: {exc}") from None
    prefix = f"{kind}.{type_name}."
    names: set[str] = set()
    for event_type in getattr(cls, "event_types", None) or []:
        name = getattr(event_type, "name", None)
        if (
            not isinstance(name, str)
            or not name.startswith(prefix)
            or not EVENT_TYPE_PATTERN.fullmatch(name)
            or name in names
        ):
            raise ProviderTypeError(f"event type names must be unique and start with {prefix}")
        names.add(name)
        version = getattr(event_type, "schema_version", None)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ProviderTypeError(f"event type {name}: schema_version must be at least 1")
        try:
            check_schema(event_type.payload_schema)
        except SchemaDefinitionError as exc:
            raise ProviderTypeError(f"event type {name}: {exc}") from None
    actions: set[str] = set()
    for action in getattr(cls, "actions", None) or []:
        name = getattr(action, "name", None)
        if not isinstance(name, str) or not ACTION_NAME_PATTERN.fullmatch(name) or name in actions:
            raise ProviderTypeError("action names must be unique lower case identifiers")
        actions.add(name)
        try:
            check_schema(action.params_schema)
        except SchemaDefinitionError as exc:
            raise ProviderTypeError(f"action {name}: {exc}") from None


EntryPointSource = Callable[[str], Iterable[EntryPoint]]


def _installed(group: str) -> Iterable[EntryPoint]:
    return entry_points(group=group)


class ProviderRegistry:
    """The provider types of one application."""

    def __init__(self) -> None:
        self._types: dict[tuple[str, str], ProviderClass] = {}

    @classmethod
    def discover(cls, source: EntryPointSource = _installed) -> ProviderRegistry:
        """A registry of every provider class found in the entry-point groups."""
        registry = cls()
        for kind, group in ENTRY_POINT_GROUPS.items():
            for ep in source(group):
                try:
                    loaded = ep.load()
                    if getattr(loaded, "kind", None) != kind:
                        raise ProviderTypeError(f"listed under {group} but declares another kind")
                    if getattr(loaded, "type_name", None) != ep.name:
                        raise ProviderTypeError("entry point name differs from type_name")
                    registry.register(loaded)
                except Exception as exc:
                    # Type only: the message of a foreign plugin is not ours to trust.
                    _log.error(
                        "provider entry point %s in %s skipped (%s: %s)",
                        ep.name,
                        group,
                        type(exc).__name__,
                        exc if isinstance(exc, ProviderTypeError) else "",
                    )
        return registry

    def register(self, cls: Any) -> None:
        _check_class(cls)
        key = (cls.kind, cls.type_name)
        if key in self._types:
            raise ProviderTypeError(f"{key[0]}/{key[1]} is already registered")
        self._types[key] = cls

    def get(self, kind: str, type_name: str) -> ProviderClass:
        try:
            return self._types[(kind, type_name)]
        except KeyError:
            raise UnknownProviderTypeError("no such provider type") from None

    def find(self, kind: str, type_name: str) -> ProviderClass | None:
        return self._types.get((kind, type_name))

    def all(self) -> list[ProviderClass]:
        """Every registered class, sorted by kind and type name."""
        return [self._types[key] for key in sorted(self._types)]
