"""Identity provider ``pangolin_header``: the user Pangolin vouches for in trusted headers.

Pangolin's badger sets ``Remote-User`` (and friends) after authenticating the user and
strips the client's own ``Remote-*`` headers; Pangolin's header authentication adds the
trust header. See :func:`app.auth.sso.trusted_sso_user` for the rules. Sessions opened
through this provider have scope ``admin`` (capped by the user's role) and end when the
trust token is rotated or cleared.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from fastapi import Request

from app.auth.identity.base import Identity
from app.auth.sso import trusted_sso_user

if TYPE_CHECKING:
    from app.settings_store.store import SettingsStore


class PangolinHeaderProvider:
    kind: ClassVar[str] = "pangolin_header"

    async def identify(self, request: Request, store: SettingsStore) -> Identity | None:
        user = trusted_sso_user(request, store)
        if user is None:
            return None
        return Identity(subject=user, provider=self.kind, scopes=frozenset({"admin"}))

    def session_binding(self, store: SettingsStore) -> str | None:
        return store.secret("sso.trust_token")
