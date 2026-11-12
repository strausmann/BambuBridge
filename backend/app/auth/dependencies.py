"""Request authentication: ``require_scope`` and the bootstrap path.

Order in ``require_scope``: API token header ``X-BambuBridge-Key`` -> browser session
cookie (added in a later task) -> 401. The token header is deliberately not
``Authorization``, so a reverse proxy's basic-auth bypass can sit next to it.

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
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import ApiError
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.auth.scopes import Scope, lower_scope, satisfies
from app.auth.tokens import dummy_verify, looks_like_token, token_prefix, verify_token
from app.config import Settings
from app.db.session import connected
from app.repositories import api_keys as api_keys_repo

KEY_HEADER = "X-BambuBridge-Key"
# Attribute set on every scope-guard dependency; the OpenAPI gate walks route dependants
# and requires it on every non-public route.
SCOPE_MARKER = "__bambubridge_scope__"
# Wrong token bodies tolerated per known prefix and minute before answering 429.
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
    """

    kind: Literal["token", "session", "bootstrap"]
    scope: Scope
    user_id: UUID | None
    key_id: UUID | None
    user: str | None


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


async def authenticate_token(request: Request, presented: str, need: Scope) -> AuthContext:
    """Check an API token from the header and return its context (or raise ``ApiError``)."""
    if not looks_like_token(presented):
        raise _invalid_token()
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    limiter: SlidingWindowRateLimiter = request.app.state.rate_limiter
    failures: SlidingWindowRateLimiter = request.app.state.failed_auth_limiter
    async with factory() as session:
        await connected(session)
        found = await api_keys_repo.get_by_prefix(session, token_prefix(presented))
        if found is None:
            await dummy_verify(presented)  # same bcrypt work as for a known prefix
            raise _invalid_token()
        key, owner = found
        if not await verify_token(presented, key.hash):
            # Wrong bodies for a known prefix have their own budget; the token's own
            # rate limit is untouched, so guessing never locks out the real holder.
            allowed, retry_after = failures.hit(key.id, limit=FAILED_VERIFICATIONS_PER_MINUTE)
            if not allowed:
                raise _rate_limited(retry_after)
            raise _invalid_token()
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
        raise ApiError(
            403,
            "insufficient_scope",
            "Insufficient scope",
            detail=f"This operation needs the scope '{need}'.",
        )
    return AuthContext(
        kind="token", scope=effective, user_id=owner.id, key_id=key.id, user=owner.display_name
    )


def _not_authenticated() -> ApiError:
    return _unauthorized("not_authenticated", "Authentication required")


def require_scope(need: Scope) -> Callable[..., Awaitable[AuthContext]]:
    """Dependency factory: the caller must hold at least ``need``."""

    async def dependency(
        request: Request,
        key: Annotated[str | None, Security(_key_header, scopes=[need])] = None,
    ) -> AuthContext:
        if key:
            return await authenticate_token(request, key, need)
        # Seam for the browser session (cookie) path; until then no header means 401.
        raise _not_authenticated()

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
    key: Annotated[str | None, Security(_key_header, scopes=["admin"])] = None,
    bootstrap: Annotated[str | None, Security(_bootstrap_header)] = None,
) -> AuthContext:
    """``require_scope("admin")`` that also accepts the bootstrap header (token wins)."""
    if key:
        return await authenticate_token(request, key, "admin")
    if bootstrap:
        return check_bootstrap_key(request.app.state.settings, bootstrap)
    # Seam for the browser session (cookie) path; until then 401.
    raise _not_authenticated()


setattr(require_admin_or_bootstrap, SCOPE_MARKER, "admin")
