"""Request body size limit: ``413 payload_too_large`` before the application runs.

FastAPI reads and parses a JSON body before it resolves any dependency, so neither the
Origin check, the rate limits nor the authentication would stop a multi-gigabyte body from
being collected in memory. This pure ASGI middleware refuses a request whose
``Content-Length`` is over ``MAX_REQUEST_BODY_BYTES`` without reading it, and reads every
other body completely, counting its bytes, before it calls the application: the chunk that
crosses the limit gets ``413`` and is never handed on. Reading first also covers routes that
never read a body (static files, ``/healthz``): they would answer before the limit was
reached. At most ``MAX_REQUEST_BODY_BYTES`` are held per request. Every route of this API
takes small JSON bodies; a future upload route gets its own, explicit limit.

The header block and chunked trailers are bounded by the HTTP server, not here (see
``app.entrypoint``).
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.errors import problem_response

MAX_REQUEST_BODY_BYTES = 64 * 1024


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
        buffered: list[Message] = []
        received = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # the client went away before the body was complete
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                await _too_large()(scope, receive, send)
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        async def replay() -> Message:
            # The body as read; afterwards the server's own messages (``http.disconnect``).
            if buffered:
                return buffered.pop(0)
            return await receive()

        await self.app(scope, replay, send)
