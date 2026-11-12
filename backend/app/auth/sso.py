"""Trusted SSO headers and the mapping of external identities to users.

``trusted_sso_user`` reads the user a reverse proxy (Pangolin) vouches for. It trusts the
user header only when the request also carries the configured trust header whose value
equals the stored ``sso.trust_token`` (constant-time compare). Without a stored, decryptable
trust token SSO is off, whatever headers a client sends: a client can always forge
``Remote-User``, it cannot forge a secret it does not know.

``user_for_identity`` maps a recognised identity to a user. 0.2.0 has a single user: an
identity seen for the first time is linked to the user ``admin``, once.
"""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories import users as users_repo

if TYPE_CHECKING:
    from app.auth.identity.base import Identity
    from app.settings_store.store import SettingsStore

# Longest user header value accepted; anything longer is not a user name we can trust.
MAX_SUBJECT_LENGTH = 256


def _single_header(request: Request, name: str) -> str | None:
    """The stripped value of ``name`` if sent exactly once and non-empty, else ``None``.

    A repeated header is refused: which copy a proxy checked and which one reaches the app
    is not defined.
    """
    values = request.headers.getlist(name)
    if len(values) != 1:
        return None
    value = values[0].strip()
    return value or None


def trusted_sso_user(request: Request, store: SettingsStore) -> str | None:
    """The SSO user if the trust header matches the stored trust token, else ``None``.

    Header names come from the settings ``sso.trust_header`` and ``sso.user_header`` and
    are read on every call, so a change applies to the next request.
    """
    expected = store.secret("sso.trust_token")
    if not expected:
        return None
    presented = _single_header(request, store.get("sso.trust_header"))
    if presented is None:
        return None
    user = _single_header(request, store.get("sso.user_header"))
    if user is None or len(user) > MAX_SUBJECT_LENGTH:
        return None
    if not hmac.compare_digest(presented.encode(), expected.encode()):
        return None
    return user


async def user_for_identity(session: AsyncSession, identity: Identity) -> User:
    """The user ``identity`` is linked to; a new identity is linked to ``admin`` once.

    ``get_or_create_admin`` takes a transaction-scoped advisory lock, so concurrent first
    sign-ins of the same identity are serialised; the lookup is repeated after the lock
    and sees a link another transaction committed meanwhile (READ COMMITTED). The caller
    commits.
    """
    user = await users_repo.resolve_identity(session, identity.provider, identity.subject)
    if user is not None:
        return user
    admin = await users_repo.get_or_create_admin(session)
    user = await users_repo.resolve_identity(session, identity.provider, identity.subject)
    if user is not None:
        return user
    await users_repo.link_identity(session, admin.id, identity.provider, identity.subject)
    return admin
