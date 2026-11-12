"""Request body size limit: ``413 payload_too_large`` before a handler reads the body.

FastAPI reads and parses a JSON body before it resolves any dependency, so neither the
Origin check, the rate limits nor the authentication would stop a multi-gigabyte body from
being collected in memory. This pure ASGI middleware refuses a request whose
``Content-Length`` is over ``MAX_REQUEST_BODY_BYTES`` without calling the application, and
counts the bytes of a body without ``Content-Length`` (chunked) while it is read: the chunk
that crosses the limit raises ``413`` instead of being handed on. Every route of this API
takes small JSON bodies; a future upload route gets its own, explicit limit.
"""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import problem_response

MAX_REQUEST_BODY_BYTES = 64 * 1024


class _BodyTooLargeError(HTTPException):
    """Raised from ``receive``; FastAPI re-raises HTTP exceptions met while reading a body."""

    def __init__(self) -> None:
        super().__init__(status_code=413, headers={"Connection": "close"})


def _too_large() -> JSONResponse:
    return problem_response(
        413, "payload_too_large", "Content Too Large", headers={"Connection": "close"}
    )


def _declared_length(scope: Scope) -> int | None:
    """The largest ``Content-Length`` the request declares, ``None`` if none is usable."""
    lengths = [
        int(value)
        for key, value in scope.get("headers", [])
        if key.lower() == b"content-length" and value.strip().isdigit()
    ]
    return max(lengths) if lengths else None


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            await _too_large()(scope, receive, send)
            return
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            # Read outside a route's body parsing (no handler turned it into a response).
            if started:
                raise
            await _too_large()(scope, receive, send)
