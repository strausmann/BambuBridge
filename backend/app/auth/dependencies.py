"""Request authentication: ``require_scope`` and the bootstrap path.

Order in ``require_scope``: API token header ``X-BambuBridge-Key`` -> browser session
cookie -> 401. The token header is deliberately not ``Authorization``, so a reverse
proxy's basic-auth bypass can sit next to it. SSO headers never authenticate an API call
directly: they only open a session (``POST /api/v1/auth/session``, ``GET /auth/continue``).

A session request with a state-changing method must come from the public origin and carry
the session's CSRF token (``app.auth.csrf``); token requests are exempt.

A token's effective scope is the lower of its own scope and its owner's role; a disabled
owner makes all of their tokens invalid.

Bootstrap: ``POST /api/v1/admin/api-keys`` alone also accepts ``X-BambuBridge-Bootstrap``
with the configured ``BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY`` (constant-time compare). Whether
bootstrap is still open is decided by the route inside a locked transaction.
"""

# No ``from __future__ import annotations``: the dependency inside ``require_scope``
# annotates with the closure variable ``need``, which FastAPI must be able to resolve.

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, NoReturn, cast
from uuid import UUID

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.auth import csrf
from app.auth import sessions as ui_sessions
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.auth.scopes import Scope, lower_scope, satisfies
from app.auth.tokens import (
    dummy_verify,
    looks_like_token,
    token_prefix,
    verify_token,
)
from app.config import Settings
from app.db.session import get_session
from app.repositories import api_keys as api_keys_repo

# The request's own session (FastAPI caches it per request, so the route gets the same one):
# a request never holds two pool connections, which could exhaust the pool under load.
# It arrives with a transaction already open: use commit() or begin_nested(), never
# begin() (see ``app.db.session.get_session``).
SessionDep = Annotated[AsyncSession, Depends(get_session)]

KEY_HEADER = "X-BambuBridge-Key"
# Attribute set on every scope-guard dependency; the OpenAPI gate walks route dependants
# and requires it on every non-public route.
SCOPE_MARKER = "__bambubridge_scope__"
# Failed checks tolerated per presented prefix and minute before answering 429.
FAILED_VERIFICATIONS_PER_MINUTE = 10
BOOTSTRAP_HEADER = "X-BambuBridge-Bootstrap"

_key_header = APIKeyHeader(
    name=KEY_HEADER,
    scheme_name="BambuBridgeKey",
    description="API token (bb_pat_...). The required scope is listed per operation.",
    auto_error=False,
)
_bootstrap_header = APIKeyHeader(
    name=BOOTSTRAP_HEADER,
    scheme_name="BambuBridgeBootstrap",
    description=(
        "One-time bootstrap key; only for creating the first admin token while no usable "
        "admin token exists."
    ),
    auto_error=False,
)


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Who is calling and with which effective scope.

    ``user_id`` is set for tokens and sessions; ``None`` only for the bootstrap call.
    ``key_id`` is the token (also of a session opened with a token), ``session_id`` the
    browser session.
    """

    kind: Literal["token", "session", "bootstrap"]
    scope: Scope
    user_id: UUID | None
    key_id: UUID | None
    user: str | None
    session_id: UUID | None = None


def _unauthorized(error_code: str, title: str) -> ApiError:
    return ApiError(401, error_code, title)


def _invalid_token() -> ApiError:
    return _unauthorized("invalid_token", "Invalid API token")


def _rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        429,
        "rate_limited",
        "Rate limit exceeded",
        detail=f"Retry after {retry_after} seconds.",
        headers={"Retry-After": str(retry_after)},
    )


def _record_failure(failures: SlidingWindowRateLimiter, prefix: str) -> NoReturn:
    """Count a failed check against the presented prefix and reject the request.

    Keyed by the prefix string for known and unknown prefixes alike, so the answers
    (401 ... then 429 after the same number of failures) do not reveal whether a prefix
    exists. Only failed attempts count; the token's own request limit is untouched.

    The limiter changes the status code of a *failed* check, not the cost of a check: every
    attempt is verified with bcrypt (a dummy check for an unknown prefix). Answering 429
    before bcrypt was rejected: anyone who knows a prefix could then lock out its holder
    whenever the holder's token is not in the verify cache (restart, eviction, first use),
    and skipping only unknown prefixes would bring back the prefix-existence timing oracle.
    A correct token is therefore always accepted. Concurrent bcrypt work is capped by a
    semaphore (``app.auth.tokens.BCRYPT_CONCURRENCY``), so a flood queues requests instead
    of exhausting the thread pool; protecting CPU against floods is the job of the reverse
    proxy in front of the service. The limiter's LRU cap bounds the stored prefixes.
    """
    allowed, retry_after = failures.hit(prefix, limit=FAILED_VERIFICATIONS_PER_MINUTE)
    if not allowed:
        raise _rate_limited(retry_after)
    raise _invalid_token()


async def authenticate_token(
    request: Request, session: AsyncSession, presented: str, need: Scope
) -> AuthContext:
    """Check an API token from the header and return its context (or raise ``ApiError``)."""
    if not looks_like_token(presented):
        raise _invalid_token()
    limiter: SlidingWindowRateLimiter = request.app.state.rate_limiter
    failures: SlidingWindowRateLimiter = request.app.state.failed_auth_limiter
    prefix = token_prefix(presented)
    found = await api_keys_repo.get_by_prefix(session, prefix)
    if found is None:
        await dummy_verify(presented)  # same bcrypt work as for a known prefix
        _record_failure(failures, prefix)
    key, owner = found
    if not await verify_token(presented, key.hash):
        _record_failure(failures, prefix)
    if not key.enabled:
        raise _unauthorized("token_disabled", "API token disabled")
    if key.expires_at is not None and key.expires_at <= datetime.now(UTC):
        raise _unauthorized("token_expired", "API token expired")
    if not owner.enabled:
        raise _unauthorized("owner_disabled", "Owner of the API token is disabled")
    allowed, retry_after = limiter.hit(key.id, limit=key.rate_limit_per_minute)
    if not allowed:
        raise _rate_limited(retry_after)
    if await api_keys_repo.touch_last_used(session, key.id):
        await session.commit()
    effective = lower_scope(cast(Scope, key.scope), cast(Scope, owner.role))
    if not satisfies(effective, need):
        raise _insufficient_scope(need)
    return AuthContext(
        kind="token", scope=effective, user_id=owner.id, key_id=key.id, user=owner.display_name
    )


def _not_authenticated() -> ApiError:
    return _unauthorized("not_authenticated", "Authentication required")


def _insufficient_scope(need: Scope) -> ApiError:
    return ApiError(
        403,
        "insufficient_scope",
        "Insufficient scope",
        detail=f"This operation needs the scope '{need}'.",
    )


def session_cookie(request: Request) -> str | None:
    """The browser session token from the cookie, if it has the right shape."""
    settings: Settings = request.app.state.settings
    return ui_sessions.session_token_from(request.cookies, settings)


def has_credentials(request: Request, key: str | None) -> bool:
    return bool(key) or session_cookie(request) is not None


async def authenticate_session(
    request: Request, session: AsyncSession, token: str, need: Scope
) -> AuthContext:
    """Check the browser session ``token`` (cookie) and return its context."""
    settings: Settings = request.app.state.settings
    valid = await ui_sessions.load_valid(
        session, token, request.app.state.settings_store, request.app.state.session_keys
    )
    if valid is None:
        raise _unauthorized("invalid_session", "Session expired or invalid")
    if csrf.is_unsafe(request):
        csrf.check_origin(request, ui_sessions.public_origin(settings))
        csrf.check_token(request, csrf.derive_token(request.app.state.session_keys.csrf, token))
    if valid.api_key is not None:
        # A session opened with a token shares the token's request limit.
        limiter: SlidingWindowRateLimiter = request.app.state.rate_limiter
        allowed, retry_after = limiter.hit(
            valid.api_key.id, limit=valid.api_key.rate_limit_per_minute
        )
        if not allowed:
            raise _rate_limited(retry_after)
    if not satisfies(valid.scope, need):
        raise _insufficient_scope(need)
    return AuthContext(
        kind="session",
        scope=valid.scope,
        user_id=valid.user.id,
        key_id=valid.row.api_key_id,
        user=valid.user.display_name,
        session_id=valid.row.id,
    )


async def authenticate_request(
    request: Request, session: AsyncSession, key: str | None, need: Scope
) -> AuthContext:
    """Token header, then session cookie, then 401."""
    if key:
        return await authenticate_token(request, session, key, need)
    token = session_cookie(request)
    if token is not None:
        return await authenticate_session(request, session, token, need)
    raise _not_authenticated()


def mark_scope[F](dependency: F, need: Scope) -> F:
    """Mark ``dependency`` as a scope guard for ``need`` (checked by the OpenAPI gate)."""
    setattr(dependency, SCOPE_MARKER, need)
    return dependency


def key_security(need: Scope) -> Any:
    """The token header as a FastAPI security dependency declaring ``need``."""
    return Security(_key_header, scopes=[need])


def require_scope(need: Scope) -> Callable[..., Awaitable[AuthContext]]:
    """Dependency factory: the caller must hold at least ``need``."""

    async def dependency(
        request: Request,
        session: SessionDep,
        key: Annotated[str | None, Security(_key_header, scopes=[need])] = None,
    ) -> AuthContext:
        return await authenticate_request(request, session, key, need)

    setattr(dependency, SCOPE_MARKER, need)
    return dependency


def check_bootstrap_key(settings: Settings, presented: str) -> AuthContext:
    """Accept the bootstrap key (constant time). Wrong or unconfigured key: one fixed 401.

    The answer does not reveal whether bootstrap is configured or already closed.
    ``hmac.compare_digest`` is constant-time only for inputs of equal length; a presented
    value of a different length can reveal the key's length through timing. That is
    acceptable: the key is at least 32 characters, so knowing its length does not help.
    """
    expected = settings.bootstrap_admin_key.get_secret_value()
    matches = hmac.compare_digest(presented.encode(), expected.encode())
    if not (matches and expected):
        raise _unauthorized("invalid_bootstrap_key", "Bootstrap key rejected")
    return AuthContext(kind="bootstrap", scope="admin", user_id=None, key_id=None, user=None)


async def require_admin_or_bootstrap(
    request: Request,
    session: SessionDep,
    key: Annotated[str | None, Security(_key_header, scopes=["admin"])] = None,
    bootstrap: Annotated[str | None, Security(_bootstrap_header)] = None,
) -> AuthContext:
    """``require_scope("admin")`` that also accepts the bootstrap header (token wins)."""
    if key:
        return await authenticate_token(request, session, key, "admin")
    if bootstrap:
        return check_bootstrap_key(request.app.state.settings, bootstrap)
    return await authenticate_request(request, session, None, "admin")


setattr(require_admin_or_bootstrap, SCOPE_MARKER, "admin")
