"""Server-side browser sessions.

The session cookie carries ``secrets.token_urlsafe(32)``; only its SHA-256 is stored, and a
session is found by that hash (a hash lookup of a 256-bit random value leaks nothing useful
through timing). Sessions expire 12 h after creation (absolute) and are re-checked on
every use: not revoked, not expired, the user still enabled; a session opened with an API
token needs the token still usable; a session opened by an identity provider needs that
provider still active and its binding material (for example the SSO trust token)
unchanged. The effective scope is the stored scope capped by the user's current role
(and the token's scope).

Cookies: ``__Host-bb_session`` (HttpOnly) and ``__Host-bb_csrf`` (readable by the web UI)
when ``BAMBUBRIDGE_PUBLIC_URL`` is https; otherwise ``bb_session``/``bb_csrf`` without
``Secure`` and a warning at start. Both ``SameSite=Strict``, ``Path=/``, 12 h.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.auth import csrf
from app.auth.identity import registry
from app.auth.scopes import Scope, lower_scope
from app.config import Settings
from app.models.api_key import ApiKey
from app.models.ui_session import UiSession
from app.models.user import User
from app.security.keys import decode_secret_key

if TYPE_CHECKING:
    from app.auth.identity.base import Identity
    from app.settings_store.store import SettingsStore

_log = logging.getLogger(__name__)

SESSION_TTL = timedelta(hours=12)
MAX_ACTIVE_SESSIONS = 20
PURGE_AFTER = timedelta(days=1)

SESSION_COOKIE = "bb_session"
CSRF_COOKIE = "bb_csrf"
# token_urlsafe(32) gives 43 characters; anything else is not one of our cookies.
_TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{43}")


def _now() -> datetime:
    """Current UTC time; a module function so tests can move the clock."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SessionKeys:
    """Keys derived from ``BAMBUBRIDGE_SECRET_KEY``; never the secret key itself."""

    csrf: bytes
    binding: bytes

    def __repr__(self) -> str:
        return "SessionKeys(<hidden>)"


def _derive(master: bytes, label: str) -> bytes:
    return hmac.new(master, b"bambubridge/" + label.encode() + b"/v1", hashlib.sha256).digest()


def session_keys(settings: Settings) -> SessionKeys:
    master = decode_secret_key(
        settings.secret_key.get_secret_value(), name="BAMBUBRIDGE_SECRET_KEY"
    )
    return SessionKeys(csrf=_derive(master, "csrf"), binding=_derive(master, "session-binding"))


def is_secure(settings: Settings) -> bool:
    return settings.public_url.scheme == "https"


def cookie_names(settings: Settings) -> tuple[str, str]:
    """``(session, csrf)`` cookie names; ``__Host-`` prefixed when served over https."""
    if is_secure(settings):
        return f"__Host-{SESSION_COOKIE}", f"__Host-{CSRF_COOKIE}"
    return SESSION_COOKIE, CSRF_COOKIE


def public_origin(settings: Settings) -> str:
    """Origin (``scheme://host[:port]``) of the public URL, default port omitted, lower case."""
    url = settings.public_url
    default_port = 443 if url.scheme == "https" else 80
    origin = f"{url.scheme}://{url.host}"
    if url.port is not None and url.port != default_port:
        origin += f":{url.port}"
    return origin.lower()


def warn_if_insecure(settings: Settings) -> None:
    if not is_secure(settings):
        _log.warning(
            "BAMBUBRIDGE_PUBLIC_URL is not https: session cookies are sent without the Secure "
            "flag and without the __Host- prefix. Use https outside of a local test setup."
        )


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def binding_hash(keys: SessionKeys, kind: str, material: str) -> str:
    """Keyed hash of a provider's binding material; the material itself is never stored."""
    message = kind.encode() + b"\0" + material.encode()
    return hmac.new(keys.binding, message, hashlib.sha256).hexdigest()


def set_cookies(response: Response, settings: Settings, keys: SessionKeys, token: str) -> None:
    session_name, csrf_name = cookie_names(settings)
    secure = is_secure(settings)
    max_age = int(SESSION_TTL.total_seconds())
    for name, value, httponly in (
        (session_name, token, True),
        (csrf_name, csrf.derive_token(keys.csrf, token), False),
    ):
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            path="/",
            secure=secure,
            httponly=httponly,
            samesite="strict",
        )


def clear_cookies(response: Response, settings: Settings) -> None:
    session_name, csrf_name = cookie_names(settings)
    secure = is_secure(settings)
    for name, httponly in ((session_name, True), (csrf_name, False)):
        response.delete_cookie(name, path="/", secure=secure, httponly=httponly, samesite="strict")


def session_token_from(request_cookies: dict[str, str], settings: Settings) -> str | None:
    """The session cookie's value if it has the shape of one of our tokens."""
    value = request_cookies.get(cookie_names(settings)[0], "")
    return value if _TOKEN_SHAPE.fullmatch(value) else None


async def create_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    scope: Scope,
    api_key_id: UUID | None = None,
    identity: Identity | None = None,
    binding: str | None = None,
) -> tuple[UiSession, str]:
    """Insert a session, commit, and return ``(row, cookie_token)``.

    At most ``MAX_ACTIVE_SESSIONS`` active sessions per user: opening one more revokes the
    oldest. Sessions that expired more than ``PURGE_AFTER`` ago are deleted on the way, so
    the table stays bounded without a background job.

    Count, revoke and insert run under a lock on the user's row (``FOR NO KEY UPDATE``,
    held until the commit), so concurrent sign-ins of the same user are serialised and
    cannot both see room under the cap. Under ``READ COMMITTED`` the count after the lock
    sees the sessions the previous holder committed. ``NO KEY`` keeps the lock out of the
    way of inserts that merely reference the user (foreign keys take ``KEY SHARE``).
    """
    await db.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))
    now = _now()
    token = secrets.token_urlsafe(32)
    await db.execute(delete(UiSession).where(UiSession.expires_at < now - PURGE_AFTER))
    active = (
        await db.scalars(
            select(UiSession.id)
            .where(
                UiSession.user_id == user_id,
                UiSession.revoked_at.is_(None),
                UiSession.expires_at > now,
            )
            .order_by(UiSession.created_at, UiSession.id)
        )
    ).all()
    excess = len(active) - (MAX_ACTIVE_SESSIONS - 1)
    if excess > 0:
        await db.execute(
            update(UiSession).where(UiSession.id.in_(active[:excess])).values(revoked_at=now)
        )
    row = UiSession(
        token_hash=hash_token(token),
        user_id=user_id,
        api_key_id=api_key_id,
        identity_provider=identity.provider if identity else None,
        identity_subject=identity.subject if identity else None,
        identity_binding=binding,
        scope=scope,
        created_at=now,
        expires_at=now + SESSION_TTL,
    )
    db.add(row)
    await db.commit()
    return row, token


@dataclass(frozen=True, slots=True)
class ValidSession:
    row: UiSession
    user: User
    scope: Scope
    api_key: ApiKey | None


def _binding_holds(row: UiSession, store: SettingsStore, keys: SessionKeys) -> bool:
    kind = row.identity_provider or ""
    provider = registry.get(kind)
    if provider is None or not registry.is_active(store, kind) or row.identity_binding is None:
        return False
    material = provider.session_binding(store)
    if not material:
        return False
    expected = binding_hash(keys, kind, material)
    return hmac.compare_digest(expected.encode(), row.identity_binding.encode())


async def load_valid(
    db: AsyncSession, token: str, store: SettingsStore, keys: SessionKeys
) -> ValidSession | None:
    """Return the session for ``token`` if it may still be used, else ``None``."""
    row = await db.scalar(select(UiSession).where(UiSession.token_hash == hash_token(token)))
    now = _now()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    user = await db.get(User, row.user_id)
    if user is None or not user.enabled:
        return None
    scope = lower_scope(cast(Scope, row.scope), cast(Scope, user.role))
    key: ApiKey | None = None
    if row.api_key_id is not None:
        key = await db.get(ApiKey, row.api_key_id)
        if key is None or not key.enabled or key.owner_user_id != user.id:
            return None
        if key.expires_at is not None and key.expires_at <= now:
            return None
        scope = lower_scope(scope, cast(Scope, key.scope))
    if row.identity_provider is not None and not _binding_holds(row, store, keys):
        return None
    return ValidSession(row=row, user=user, scope=scope, api_key=key)


async def revoke(db: AsyncSession, session_id: UUID) -> None:
    """Revoke a session and commit."""
    await db.execute(
        update(UiSession)
        .where(UiSession.id == session_id, UiSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await db.commit()
