"""System routes: ``GET /readiness`` (scope ``read``) and ``GET /api/v1/info`` (public).

Readiness reports ``database`` (a ``SELECT 1`` within a short timeout) and ``listener``
(the settings ``LISTEN`` connection is up). 200 only when both are ``ok``, otherwise 503.
While the database is down the caller cannot be checked (tokens and sessions live in the
database): a request that presents credentials then gets the readiness answer instead of
a generic 503, which tells nothing beyond "the database is unavailable". Without
credentials the answer is 401 as for every other guarded route.

``/api/v1/info`` is public by design: name, version and build id, plus one hint for the
sign-in page: whether the first-start screen is still of use (``bootstrap_open``).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.errors import CONNECTION_ERRORS, ApiError, DatabaseUnavailableError
from app.auth.dependencies import (
    AuthContext,
    authenticate_request,
    has_credentials,
    key_security,
    mark_scope,
)
from app.build_info import BUILD_ID, VERSION
from app.config import Settings
from app.db.session import connected
from app.repositories import api_keys as api_keys_repo
from app.schemas.problem import ProblemDetail
from app.schemas.system import Info, Readiness

router = APIRouter(tags=["system"])

DATABASE_CHECK_TIMEOUT_SECONDS = 3.0
_DB_DOWN: tuple[type[BaseException], ...] = (
    DatabaseUnavailableError,
    OperationalError,
    InterfaceError,
    *CONNECTION_ERRORS,
)
_CHECK_FAILED: tuple[type[BaseException], ...] = (TimeoutError, *_DB_DOWN)
_HINT_FAILED: tuple[type[BaseException], ...] = (*_CHECK_FAILED, DBAPIError)


async def _readiness_auth(
    request: Request,
    key: Annotated[str | None, key_security("read")] = None,
) -> AuthContext | None:
    """``require_scope("read")`` that yields ``None`` instead of 503 when the DB is down.

    "Down" includes stalled: the lookup is bounded by ``DATABASE_CHECK_TIMEOUT_SECONDS``.
    """
    if not has_credentials(request, key):
        raise ApiError(401, "not_authenticated", "Authentication required")

    async def check() -> AuthContext:
        async with request.app.state.session_factory() as session:
            await connected(session)
            return await authenticate_request(request, session, key, "read")

    # A stalled database (accepts, never answers) must not hold the probe: the same bound
    # as the database check applies to the credential lookup.
    try:
        return await asyncio.wait_for(check(), timeout=DATABASE_CHECK_TIMEOUT_SECONDS)
    except _CHECK_FAILED:
        return None


mark_scope(_readiness_auth, "read")


async def _database_ok(engine: AsyncEngine) -> bool:
    async def probe() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(probe(), timeout=DATABASE_CHECK_TIMEOUT_SECONDS)
    except _CHECK_FAILED:
        return False
    return True


def _listener_ok(request: Request) -> bool:
    listener = getattr(request.app.state, "settings_listener", None)
    return listener is not None and listener.connected


_READINESS_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemDetail},
    403: {"model": ProblemDetail},
    429: {"model": ProblemDetail},
    503: {"model": Readiness, "description": "Database or settings listener unavailable"},
}


@router.get(
    "/readiness",
    summary="Readiness probe",
    response_model=Readiness,
    responses=_READINESS_RESPONSES,
)
async def readiness(
    request: Request, _auth: Annotated[AuthContext | None, Depends(_readiness_auth)]
) -> JSONResponse:
    # ``None``: the credential lookup already found the database down or stalled; probing
    # again would only add a second timeout.
    database_ok = _auth is not None and await _database_ok(request.app.state.engine)
    body = Readiness(
        database="ok" if database_ok else "unavailable",
        listener="ok" if _listener_ok(request) else "unavailable",
    )
    ready = body.database == "ok" and body.listener == "ok"
    return JSONResponse(status_code=200 if ready else 503, content=body.model_dump())


async def _bootstrap_open(request: Request) -> bool:
    """Whether the first-start screen can still create the first admin token.

    A hint for the sign-in page only: the bootstrap route enforces the rules itself. Open
    means a bootstrap key is configured and no usable admin token exists. When the database
    cannot answer, the state is unknown and reported open (the hint then stays visible; the
    route refuses a closed bootstrap anyway).
    """
    settings: Settings = request.app.state.settings
    if not settings.bootstrap_admin_key.get_secret_value():
        return False

    async def closed() -> bool:
        async with request.app.state.session_factory() as session:
            await connected(session)
            return await api_keys_repo.usable_admin_token_exists(session)

    try:
        return not await asyncio.wait_for(closed(), timeout=DATABASE_CHECK_TIMEOUT_SECONDS)
    except _HINT_FAILED:
        return True


@router.get("/api/v1/info", summary="Name, version and build of this server")
async def info(request: Request) -> Info:
    return Info(version=VERSION, build=BUILD_ID, bootstrap_open=await _bootstrap_open(request))
