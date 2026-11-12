"""Error responses as RFC 9457 problem details with a stable ``error_code``.

Routes and dependencies raise ``ApiError``. Database outages are translated at the
database boundary (``DatabaseUnavailableError``, see ``app.db.session``) or recognised as
connection-level SQLAlchemy errors; everything else is a 500 ``internal_error``.
Messages are fixed strings chosen here: an exception message, a token, the bootstrap
key, SQL text or request input never reaches a response.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.schemas.problem import ProblemDetail

PROBLEM_MEDIA_TYPE = "application/problem+json"
# Exceptions that mean "the database cannot be reached", not "the query was wrong".
CONNECTION_ERRORS: tuple[type[BaseException], ...] = (OSError, OperationalError, InterfaceError)

_log = logging.getLogger(__name__)
_MAX_VALIDATION_ERRORS = 20


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

    def response(self) -> JSONResponse:
        return problem_response(
            self.status, self.error_code, self.title, detail=self.detail, headers=self.headers
        )


class DatabaseUnavailableError(ApiError):
    """The database could not be reached (raised at the connection boundary)."""

    def __init__(self) -> None:
        super().__init__(
            503,
            "database_unavailable",
            "Database unavailable",
            detail="The database could not be reached. Try again later.",
        )


def problem_response(
    status: int,
    error_code: str,
    title: str,
    *,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
    extensions: dict[str, object] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        title=title,
        status=status,
        detail=detail,
        error_code=error_code,
        extensions=extensions or {},
    ).model_dump(exclude_none=True)
    if not problem["extensions"]:
        del problem["extensions"]
    return JSONResponse(
        status_code=status,
        content=problem,
        headers=dict(headers or {}),
        media_type=PROBLEM_MEDIA_TYPE,
    )


def _internal_error() -> JSONResponse:
    return problem_response(500, "internal_error", "Internal server error")


async def _api_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):  # pragma: no cover - registered for ApiError only
        raise TypeError("handler registered for another exception type")
    return exc.response()


def _sqlstate(exc: DBAPIError) -> str:
    code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    return str(code) if code else "unknown"


async def _dbapi_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Connection-level errors are 503; any other driver error is a bug (500).

    Logged with class and SQLSTATE only. The driver text (``orig``) can carry row values
    (``DETAIL: Key (name)=(...)``), so neither the message nor ``exc_info`` is logged;
    the traceback frames (code locations, no message) are kept for debugging.
    """
    if not isinstance(exc, DBAPIError):  # pragma: no cover - registered for DBAPIError only
        raise TypeError("handler registered for another exception type")
    if isinstance(exc, (OperationalError, InterfaceError)) or exc.connection_invalidated:
        _log.error(
            "database unavailable while handling a request: %s (SQLSTATE %s)",
            type(exc).__name__,
            _sqlstate(exc),
        )
        return DatabaseUnavailableError().response()
    _log.error(
        "unhandled database error: %s (SQLSTATE %s)\n%s",
        type(exc).__name__,
        _sqlstate(exc),
        "".join(traceback.format_tb(exc.__traceback__)),
    )
    return _internal_error()


# Fixed texts per Pydantic error type. Pydantic's own messages may quote input (the
# offending character of a UUID, a length, a limit); unknown types get the generic text.
_VALIDATION_MESSAGES: dict[str, str] = {
    "missing": "Field required",
    "extra_forbidden": "Unknown field",
    "string_type": "Must be a string",
    "string_too_short": "Too short",
    "string_too_long": "Too long",
    "string_pattern_mismatch": "Does not match the required format",
    "literal_error": "Not an allowed value",
    "enum": "Not an allowed value",
    "uuid_parsing": "Invalid UUID",
    "uuid_type": "Invalid UUID",
    "int_parsing": "Must be an integer",
    "int_type": "Must be an integer",
    "int_from_float": "Must be an integer",
    "bool_parsing": "Must be a boolean",
    "bool_type": "Must be a boolean",
    "greater_than_equal": "Value too small",
    "greater_than": "Value too small",
    "less_than_equal": "Value too large",
    "less_than": "Value too large",
    "datetime_parsing": "Invalid date-time",
    "datetime_from_date_parsing": "Invalid date-time",
    "datetime_type": "Invalid date-time",
    "timezone_aware": "Date-time must include a time zone",
    "json_invalid": "Invalid JSON",
    "model_attributes_type": "Must be an object",
    "dict_type": "Must be an object",
    "list_type": "Must be a list",
}
_GENERIC_VALIDATION_MESSAGE = "Invalid value"


def _sanitize_validation_errors(errors: Any) -> list[dict[str, object]]:
    """Location, a fixed message and the type of each error; never ``input`` or ``ctx``."""
    result: list[dict[str, object]] = []
    for err in list(errors)[:_MAX_VALIDATION_ERRORS]:
        loc = [str(part) for part in err.get("loc", ())]
        if err.get("type") == "extra_forbidden" and loc:
            loc[-1] = "<unknown field>"  # a field name the client chose is not echoed
        kind = str(err.get("type"))
        message = _VALIDATION_MESSAGES.get(kind, _GENERIC_VALIDATION_MESSAGE)
        result.append({"loc": loc, "msg": message, "type": kind})
    return result


async def _validation_handler(_request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):  # pragma: no cover
        raise TypeError("handler registered for another exception type")
    return problem_response(
        422,
        "validation_failed",
        "Request validation failed",
        extensions={"errors": _sanitize_validation_errors(exc.errors())},
    )


_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
}


async def _http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Framework errors (unknown route, wrong method, ...). ``exc.detail`` is not echoed."""
    if not isinstance(exc, StarletteHTTPException):  # pragma: no cover
        raise TypeError("handler registered for another exception type")
    status = exc.status_code
    try:
        title = HTTPStatus(status).phrase
    except ValueError:  # non-standard code such as 499
        title = "HTTP error"
    return problem_response(
        status, _HTTP_ERROR_CODES.get(status, "http_error"), title, headers=exc.headers
    )


class InternalErrorMiddleware:
    """Answer any unhandled exception with a 500 problem and log it with its traceback.

    Starlette's own fallback (``ServerErrorMiddleware``) answers with plain text and
    re-raises; this middleware sits inside it so the client always gets problem details.
    If the response has already started, the exception is re-raised unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if started:
                raise
            _log.error("unhandled error while handling a request", exc_info=exc)
            await _internal_error()(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(DBAPIError, _dbapi_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_middleware(InternalErrorMiddleware)
