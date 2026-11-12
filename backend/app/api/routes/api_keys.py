"""Admin management of API tokens: ``/api/v1/admin/api-keys``.

All operations need scope ``admin``. ``POST`` also accepts the one-time bootstrap header
while no usable admin token exists; it then creates exactly one unrestricted admin token
for the single user ``admin``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.auth.dependencies import AuthContext, require_admin_or_bootstrap, require_scope
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.db.session import get_session
from app.repositories import api_keys as api_keys_repo
from app.repositories import users as users_repo
from app.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyRead, ApiKeyUpdate
from app.schemas.problem import ProblemDetail

router = APIRouter(prefix="/api/v1/admin/api-keys", tags=["api-keys"])

# The request session already has an open transaction: commit() or begin_nested(), never
# begin() (see ``app.db.session.get_session``).
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminDep = Annotated[AuthContext, Depends(require_scope("admin"))]

_PROBLEMS: dict[int | str, dict[str, Any]] = {
    code: {"model": ProblemDetail} for code in (401, 403, 429, 503)
}


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "API token not found")


def _check_expiry(expires_at: datetime | None) -> None:
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise ApiError(422, "invalid_expiry", "Expiry must be in the future")


@router.get("", summary="List API tokens", responses=_PROBLEMS)
async def list_api_keys(session: SessionDep, _auth: AdminDep) -> list[ApiKeyRead]:
    """Metadata of all tokens; the token itself and its hash are never included."""
    return [ApiKeyRead.model_validate(k) for k in await api_keys_repo.list_all(session)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create an API token",
    responses={**_PROBLEMS, 422: {"model": ProblemDetail}},
)
async def create_api_key(
    body: ApiKeyCreate,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_admin_or_bootstrap)],
) -> ApiKeyCreated:
    """Create a token. The response's ``token`` is the only time the plaintext is shown."""
    _check_expiry(body.expires_at)
    if auth.kind == "bootstrap":
        if body.scope != "admin" or body.expires_at is not None:
            raise ApiError(
                403,
                "bootstrap_admin_key_only",
                "Bootstrap creates only an unrestricted admin token",
            )
        # Lock, check and create in one transaction: concurrent bootstraps get one token.
        await api_keys_repo.lock_bootstrap(session)
        if await api_keys_repo.usable_admin_token_exists(session):
            raise ApiError(403, "bootstrap_closed", "Bootstrap is closed")
        owner = await users_repo.get_or_create_admin(session)
        # Never issue a dead token: it would close bootstrap without granting access.
        if not owner.enabled:
            raise ApiError(403, "bootstrap_owner_disabled", "The admin user is disabled")
        if owner.role != "admin":
            raise ApiError(403, "bootstrap_owner_not_admin", "The admin user lacks the admin role")
        owner_id = owner.id
    else:
        if auth.user_id is None:  # pragma: no cover - tokens and sessions always carry a user
            raise RuntimeError("authenticated caller without a user")
        owner_id = auth.user_id
    key, plaintext = await api_keys_repo.create(
        session,
        owner_user_id=owner_id,
        name=body.name,
        scope=body.scope,
        note=body.note,
        expires_at=body.expires_at,
        rate_limit_per_minute=body.rate_limit_per_minute,
    )
    await session.commit()
    return ApiKeyCreated.model_validate(
        {**ApiKeyRead.model_validate(key).model_dump(), "token": plaintext}
    )


@router.patch(
    "/{key_id}",
    summary="Update an API token",
    responses={**_PROBLEMS, 404: {"model": ProblemDetail}, 422: {"model": ProblemDetail}},
)
async def update_api_key(
    key_id: UUID, body: ApiKeyUpdate, session: SessionDep, _auth: AdminDep
) -> ApiKeyRead:
    """Change name, note, enabled or expiry. Scope and token value cannot change."""
    changes = body.model_dump(include=body.model_fields_set)
    if "expires_at" in changes:
        _check_expiry(changes["expires_at"])
    key = await api_keys_repo.get(session, key_id)
    if key is None:
        raise _not_found()
    for field, value in changes.items():
        setattr(key, field, value)
    await session.commit()
    return ApiKeyRead.model_validate(key)


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an API token",
    responses={**_PROBLEMS, 404: {"model": ProblemDetail}},
)
async def delete_api_key(
    key_id: UUID, request: Request, session: SessionDep, _auth: AdminDep
) -> Response:
    """Delete a token; it is rejected from the next request on."""
    if not await api_keys_repo.delete(session, key_id):
        raise _not_found()
    await session.commit()
    limiter: SlidingWindowRateLimiter = request.app.state.rate_limiter
    limiter.reset(key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
