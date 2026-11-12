"""Browser sign-in: ``/api/v1/auth/session``.

``POST`` is public by design (it is the sign-in): with a body ``{token}`` it exchanges an
API token for a session, without one it asks the active identity providers (trusted SSO
headers). It needs an ``Origin`` of the public URL and is rate limited per client
address (setting ``auth.sign_in_limit_per_minute``). ``GET`` reports the caller's own
sign-in; ``DELETE`` signs out. Both need at least scope ``read``.
"""

from __future__ import annotations

import ipaddress
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.auth import csrf
from app.auth import sessions as ui_sessions
from app.auth.dependencies import AuthContext, authenticate_token, require_scope
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.auth.scopes import Scope
from app.auth.sign_in import open_identity_session
from app.config import Settings
from app.db.session import get_session
from app.models.ui_session import UiSession
from app.schemas.auth_session import SessionInfo, SignInRequest
from app.schemas.problem import ProblemDetail
from app.settings_store.store import SettingsStore

router = APIRouter(prefix="/api/v1/auth/session", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_scope("read"))]

_PROBLEMS: dict[int | str, dict[str, Any]] = {
    code: {"model": ProblemDetail} for code in (401, 403, 429, 503)
}


def _client_key(request: Request) -> str:
    """The client address (behind the trusted proxy: the forwarded client, see entrypoint).

    Anything that is not an IP address shares one bucket instead of opening its own.
    """
    host = request.client.host if request.client else ""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return "unknown"


def _info(row: UiSession, user: str | None, scope: Scope, csrf_token: str) -> SessionInfo:
    return SessionInfo.model_validate(
        {
            "kind": "session",
            "scope": scope,
            "user": user,
            "identity_provider": row.identity_provider,
            "expires_at": row.expires_at,
            "csrf_token": csrf_token,
        }
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Sign in to the web UI",
    description=(
        "Opens a browser session and sets the session and CSRF cookies. With a body "
        "``{token}`` the API token is checked; without a body the active identity "
        "providers are asked (trusted SSO headers). Needs an ``Origin`` of the public URL; "
        "rate limited per client address."
    ),
    responses={**_PROBLEMS, 422: {"model": ProblemDetail}},
)
async def sign_in(
    request: Request,
    response: Response,
    db: SessionDep,
    body: SignInRequest | None = None,
) -> SessionInfo:
    settings: Settings = request.app.state.settings
    store: SettingsStore = request.app.state.settings_store
    keys: ui_sessions.SessionKeys = request.app.state.session_keys
    csrf.check_origin(request, ui_sessions.public_origin(settings))
    limiter: SlidingWindowRateLimiter = request.app.state.sign_in_limiter
    allowed, retry_after = limiter.hit(
        _client_key(request), limit=store.get("auth.sign_in_limit_per_minute")
    )
    if not allowed:
        raise ApiError(
            429,
            "rate_limited",
            "Too many sign-in attempts",
            detail=f"Retry after {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )
    if body is not None:
        ctx = await authenticate_token(request, db, body.token, "read")
        if ctx.user_id is None:  # pragma: no cover - a token always has an owner
            raise RuntimeError("token without an owner")
        row, token = await ui_sessions.create_session(
            db, user_id=ctx.user_id, scope=ctx.scope, api_key_id=ctx.key_id
        )
        user, scope = ctx.user, ctx.scope
    else:
        opened = await open_identity_session(request, db)
        if opened is None:
            raise ApiError(401, "not_authenticated", "Authentication required")
        row, token = opened
        user, scope = row.identity_subject, cast(Scope, row.scope)
    ui_sessions.set_cookies(response, settings, keys, token)
    return _info(row, user, scope, csrf.derive_token(keys.csrf, token))


@router.get("", summary="Current sign-in", responses=_PROBLEMS)
async def get_sign_in(request: Request, db: SessionDep, auth: ReadDep) -> SessionInfo:
    """The caller's own sign-in: a session (with its CSRF token) or the API token."""
    if auth.kind != "session" or auth.session_id is None:
        return SessionInfo(kind="token", scope=auth.scope, user=auth.user)
    row = await db.get(UiSession, auth.session_id)
    token = ui_sessions.session_token_from(request.cookies, request.app.state.settings)
    if row is None or token is None:  # pragma: no cover - checked by the dependency
        raise ApiError(401, "invalid_session", "Session expired or invalid")
    keys: ui_sessions.SessionKeys = request.app.state.session_keys
    return _info(row, auth.user, auth.scope, csrf.derive_token(keys.csrf, token))


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    responses=_PROBLEMS,
)
async def sign_out(request: Request, db: SessionDep, auth: ReadDep) -> Response:
    """Revoke the current browser session and clear its cookies."""
    if auth.session_id is not None:
        await ui_sessions.revoke(db, auth.session_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    ui_sessions.clear_cookies(response, request.app.state.settings)
    return response
