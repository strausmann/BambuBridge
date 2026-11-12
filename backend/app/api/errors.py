"""Error responses as RFC 9457 problem details with a stable ``error_code``.

Routes and dependencies raise ``ApiError``; database failures become 503
``database_unavailable``. Messages are fixed strings chosen here: a token, the bootstrap
key or SQL text never reaches a response.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.schemas.problem import ProblemDetail

PROBLEM_MEDIA_TYPE = "application/problem+json"

_log = logging.getLogger(__name__)


class ApiError(Exception):
    """An error answered with a problem-details body."""

    def __init__(
        self,
        status: int,
        error_code: str,
        title: str,
        *,
        detail: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(error_code)
        self.status = status
        self.error_code = error_code
        self.title = title
        self.detail = detail
        self.headers = dict(headers or {})


def problem_response(
    status: int,
    error_code: str,
    title: str,
    *,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        title=title, status=status, detail=detail, error_code=error_code
    ).model_dump(exclude_none=True, exclude={"extensions"})
    return JSONResponse(
        status_code=status,
        content=problem,
        headers=dict(headers or {}),
        media_type=PROBLEM_MEDIA_TYPE,
    )


async def _api_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # pragma: no cover - registered for ApiError only
        raise TypeError("handler registered for another exception type")
    return problem_response(
        exc.status, exc.error_code, exc.title, detail=exc.detail, headers=exc.headers
    )


async def _database_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    # Only the exception type is logged: SQLAlchemy messages carry SQL and bound values.
    _log.error("database error while handling a request: %s", type(exc).__name__)
    return problem_response(
        503,
        "database_unavailable",
        "Database unavailable",
        detail="The database could not be reached. Try again later.",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(SQLAlchemyError, _database_error_handler)
    # asyncpg raises plain OSError (e.g. ConnectionRefusedError) when it cannot connect.
    app.add_exception_handler(OSError, _database_error_handler)
