from __future__ import annotations

from typing import ClassVar

import pytest
from fastapi import Request

from app.auth.identity import registry
from app.auth.identity.base import Identity
from app.security.secret_box import secret_box_from_key
from app.settings_store.store import SettingsStore


class _Provider:
    kind: ClassVar[str] = "unit_test_provider"

    async def identify(self, request: Request, store: SettingsStore) -> Identity | None:
        return None

    def session_binding(self, store: SettingsStore) -> str | None:
        return None


@pytest.fixture
def store() -> SettingsStore:
    return SettingsStore(secret_box_from_key(b"A" * 32))


def test_builtin_provider_is_registered_and_active_by_default(store: SettingsStore):
    assert "pangolin_header" in registry.kinds()
    assert [p.kind for p in registry.active(store)] == ["pangolin_header"]
    assert registry.is_active(store, "pangolin_header")


def test_kind_can_be_registered_once():
    provider = registry.register(_Provider())
    try:
        assert registry.get("unit_test_provider") is provider
        with pytest.raises(ValueError):
            registry.register(_Provider())
    finally:
        registry.unregister("unit_test_provider")
    assert registry.get("unit_test_provider") is None
    assert "unit_test_provider" not in registry.kinds()


def test_identity_repr_hides_the_subject():
    identity = Identity(subject="alice@example.com", provider="x", scopes=frozenset({"read"}))
    assert "alice" not in repr(identity)
