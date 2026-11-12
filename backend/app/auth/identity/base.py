"""The interface of a sign-in (identity) provider.

A provider looks at a request and answers "this is subject X of my kind" or "not mine".
It never creates sessions or users itself: :mod:`app.auth.sso` maps an :class:`Identity`
to a user, :mod:`app.auth.sessions` opens the session. Adding a provider (OIDC, for
example) is a new module plus its own settings; sessions, CSRF and routes stay unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol

from fastapi import Request

from app.auth.scopes import Scope

if TYPE_CHECKING:
    from app.settings_store.store import SettingsStore


@dataclass(frozen=True, slots=True)
class Identity:
    """An external identity recognised by a provider.

    ``scopes`` is the most a session opened from this identity may get; the session's
    scope is the strongest of these, capped by the role of the user the identity maps to.
    ``subject`` is chosen by the provider (a user name, an e-mail address); it is never
    logged.
    """

    subject: str
    provider: str
    scopes: frozenset[Scope]

    def __repr__(self) -> str:
        # The subject identifies a person; keep it out of logs and tracebacks.
        return f"Identity(provider={self.provider!r}, subject=<hidden>)"


class IdentityProvider(Protocol):
    """A sign-in provider. Implementations are registered in ``identity.registry``."""

    kind: ClassVar[str]

    async def identify(self, request: Request, store: SettingsStore) -> Identity | None:
        """The identity the request proves, or ``None`` (not mine, not configured, wrong)."""
        ...

    def session_binding(self, store: SettingsStore) -> str | None:
        """Secret material a session of this provider stays bound to, or ``None``.

        Stored only as a keyed hash on the session. A session is valid only while the
        current material hashes to the stored value, so rotating or clearing it (for
        example the SSO trust token) ends every session the old material opened. ``None``
        means the provider cannot be used right now; its sessions are then invalid too.
        """
        ...
