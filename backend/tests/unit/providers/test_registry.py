"""The provider registry: discovery through entry points and checks of provider classes."""

from __future__ import annotations

from importlib.metadata import EntryPoint
from typing import Any, ClassVar

import pytest

from app.providers.base import ActionDef, EventTypeDef, ProbeResult, ProviderStatus
from app.providers.demo.provider import DemoProvider
from app.providers.registry import (
    ENTRY_POINT_GROUPS,
    ProviderRegistry,
    ProviderTypeError,
    UnknownProviderTypeError,
)


def _good_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"label": {"type": "string", "default": "x"}},
        "additionalProperties": False,
    }


def _provider(**overrides: Any) -> type:
    """A minimal provider class; ``overrides`` replace class attributes."""
    attrs: dict[str, Any] = {
        "kind": "integration",
        "type_name": "sample",
        "config_schema": _good_schema(),
        "event_types": [
            EventTypeDef(
                "integration.sample.done",
                1,
                {"type": "object", "properties": {}, "additionalProperties": False},
            )
        ],
        "actions": [
            ActionDef("go", {"type": "object", "properties": {}, "additionalProperties": False})
        ],
    }
    attrs.update(overrides)

    class Sample:
        kind: ClassVar[str]

        async def start(self, ctx: Any) -> None: ...
        async def stop(self) -> None: ...
        async def reconfigure(self, ctx: Any) -> None: ...
        async def test_connection(self, config: Any, secrets: Any) -> ProbeResult:
            return ProbeResult(True, "ok", 0)

        async def run_action(self, name: str, params: Any) -> dict[str, Any]:
            return {}

        def status(self) -> ProviderStatus:
            raise NotImplementedError

    for key, value in attrs.items():
        setattr(Sample, key, value)
    return Sample


def test_entry_point_groups_cover_every_kind():
    assert ENTRY_POINT_GROUPS == {
        "account": "bambubridge.providers.account",
        "inventory": "bambubridge.providers.inventory",
        "integration": "bambubridge.providers.integration",
        "display": "bambubridge.providers.display",
    }


def test_registry_discovers_demo_via_entry_points():
    # The installed package metadata, not a direct import: the entry point is what ships.
    registry = ProviderRegistry.discover()
    assert registry.get("integration", "demo") is DemoProvider
    assert ("integration", "demo") in {(c.kind, c.type_name) for c in registry.all()}


def test_discover_uses_the_group_as_the_kind():
    ep = EntryPoint("sample", "tests.unit.providers.test_registry:SAMPLE", "x")
    registry = ProviderRegistry.discover(lambda group: [ep] if group.endswith("display") else [])
    # SAMPLE declares kind "integration" but is listed under "display": refused, skipped.
    with pytest.raises(UnknownProviderTypeError):
        registry.get("display", "sample")
    with pytest.raises(UnknownProviderTypeError):
        registry.get("integration", "sample")


def test_discover_skips_a_broken_entry_point(caplog: pytest.LogCaptureFixture):
    broken = EntryPoint("broken", "tests.unit.providers.does_not_exist:X", "x")
    good = EntryPoint("sample", "tests.unit.providers.test_registry:SAMPLE", "x")
    registry = ProviderRegistry.discover(
        lambda group: [broken, good] if group.endswith("integration") else []
    )
    assert registry.get("integration", "sample") is SAMPLE
    assert "broken" in caplog.text


def test_discover_skips_an_entry_point_whose_name_differs():
    ep = EntryPoint("other", "tests.unit.providers.test_registry:SAMPLE", "x")
    registry = ProviderRegistry.discover(
        lambda group: [ep] if group.endswith("integration") else []
    )
    assert registry.all() == []


def test_register_rejects_duplicates():
    registry = ProviderRegistry()
    registry.register(_provider())
    with pytest.raises(ProviderTypeError, match="already registered"):
        registry.register(_provider())


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"kind": "printer"}, "kind"),
        ({"type_name": "Bad-Name"}, "type_name"),
        ({"type_name": ""}, "type_name"),
        ({"config_schema": {"type": "array"}}, "config_schema"),
        (
            {
                "event_types": [
                    EventTypeDef("integration.other.done", 1, {"type": "object", "properties": {}})
                ]
            },
            "event type",
        ),
        ({"event_types": [EventTypeDef("integration.sample.done", 0, {})]}, "schema_version"),
        ({"actions": [ActionDef("Go!", {"type": "object", "properties": {}})]}, "action"),
        (
            {
                "actions": [
                    ActionDef("go", {"type": "object", "properties": {}}),
                    ActionDef("go", {"type": "object", "properties": {}}),
                ]
            },
            "action",
        ),
    ],
)
def test_register_rejects_invalid_classes(overrides: dict[str, Any], message: str):
    with pytest.raises(ProviderTypeError, match=message):
        ProviderRegistry().register(_provider(**overrides))


def test_get_unknown_type():
    with pytest.raises(UnknownProviderTypeError):
        ProviderRegistry().get("integration", "missing")


def test_all_is_sorted():
    registry = ProviderRegistry()
    registry.register(_provider(type_name="zeta", event_types=[], actions=[]))
    registry.register(_provider(type_name="alpha", event_types=[], actions=[]))
    assert [c.type_name for c in registry.all()] == ["alpha", "zeta"]


SAMPLE = _provider()
