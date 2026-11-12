"""Registry of identity providers and the active selection.

Every provider registers once, under its ``kind``. Which providers are asked is the
runtime setting ``auth.identity_providers`` (a list of registered kinds, default
``["pangolin_header"]``): it is read on every call, so a change through the settings API
applies to the next request without a restart. Providers are asked in the order of that
list; ``[]`` switches header sign-in off. Routes only ever call :func:`active`, never a
provider directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.auth.identity.base import IdentityProvider
from app.settings_store.registry import set_choices_source

if TYPE_CHECKING:
    from app.settings_store.store import SettingsStore

SETTING_KEY = "auth.identity_providers"

_PROVIDERS: dict[str, IdentityProvider] = {}


def register(provider: IdentityProvider) -> IdentityProvider:
    """Register ``provider`` under its ``kind``; a kind can be registered only once."""
    kind = provider.kind
    if not kind or kind in _PROVIDERS:
        raise ValueError("identity provider kind must be unique and non-empty")
    _PROVIDERS[kind] = provider
    return provider


def unregister(kind: str) -> None:
    """Remove a provider (tests, or a provider that is withdrawn)."""
    _PROVIDERS.pop(kind, None)


def kinds() -> tuple[str, ...]:
    """Kinds of all registered providers (the allowed values of the setting)."""
    return tuple(_PROVIDERS)


def get(kind: str) -> IdentityProvider | None:
    return _PROVIDERS.get(kind)


def active(store: SettingsStore) -> list[IdentityProvider]:
    """The providers to ask, in the configured order. Unregistered kinds are skipped."""
    selected: list[str] = store.get(SETTING_KEY)
    return [_PROVIDERS[kind] for kind in selected if kind in _PROVIDERS]


def is_active(store: SettingsStore, kind: str) -> bool:
    return any(provider.kind == kind for provider in active(store))


# The setting's allowed elements are exactly the registered kinds, at the time of the PUT.
set_choices_source(SETTING_KEY, kinds)
