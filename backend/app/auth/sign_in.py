"""Opening a session from an identity provider (shared by the sign-in routes).

Only :func:`app.auth.identity.registry.active` is asked, never a provider directly, so a
new provider needs no change here, in the session code or in the routes.
"""

from __future__ import annotations

from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.auth import sessions
from app.auth.identity import registry
from app.auth.identity.base import Identity, IdentityProvider
from app.auth.scopes import SCOPES, Scope, lower_scope
from app.auth.sso import user_for_identity
from app.models.ui_session import UiSession
from app.settings_store.store import SettingsStore


async def _first_identity(
    request: Request, store: SettingsStore
) -> tuple[IdentityProvider, Identity] | None:
    for provider in registry.active(store):
        identity = await provider.identify(request, store)
        if identity is not None:
            return provider, identity
    return None


def _strongest(scopes: frozenset[Scope]) -> Scope | None:
    ranked = [scope for scope in SCOPES if scope in scopes]
    return ranked[-1] if ranked else None


async def open_identity_session(request: Request, db: AsyncSession) -> tuple[UiSession, str] | None:
    """Ask the active providers; on the first identity open a session and commit.

    ``None`` when no provider recognises the request. A recognised identity whose user is
    disabled, or that grants no scope, is refused with 401.
    """
    store: SettingsStore = request.app.state.settings_store
    keys: sessions.SessionKeys = request.app.state.session_keys
    found = await _first_identity(request, store)
    if found is None:
        return None
    provider, identity = found
    granted = _strongest(identity.scopes)
    material = provider.session_binding(store)
    if granted is None or not material:
        return None
    user = await user_for_identity(db, identity)
    if not user.enabled:
        await db.rollback()
        raise ApiError(401, "user_disabled", "User disabled")
    scope = lower_scope(granted, cast(Scope, user.role))
    return await sessions.create_session(
        db,
        user_id=user.id,
        scope=scope,
        identity=identity,
        binding=sessions.binding_hash(keys, provider.kind, material),
    )
