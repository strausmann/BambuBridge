"""Answer ``HEAD`` wherever ``GET`` is answered, as Starlette routes do.

FastAPI registers a ``GET`` route for ``GET`` only, so ``HEAD /healthz`` would be a 405 and
HEAD-based monitors would see the service as broken. This pure ASGI middleware hands a
``HEAD`` request to the application as ``GET`` and drops every body chunk of the response:
status and headers (``Content-Length`` included) stay those of the ``GET``. A ``405`` whose
``Allow`` names ``GET`` also names ``HEAD``. ``HEAD`` is safe in the same way ``GET`` is, so
authentication, rate limits and every other check run unchanged.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


def _with_head_allowed(message: Message) -> Message:
    if message.get("status") != 405:
        return message
    headers: list[tuple[bytes, bytes]] = []
    for key, value in message.get("headers", []):
        if key.lower() == b"allow":
            methods = [m.strip() for m in value.decode("latin-1").split(",") if m.strip()]
            if "GET" in methods and "HEAD" not in methods:
                methods.insert(methods.index("GET") + 1, "HEAD")
            value = ", ".join(methods).encode("latin-1")
        headers.append((key, value))
    return {**message, "headers": headers}


class HeadAsGetMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        head = scope["method"] == "HEAD"
        if head:
            scope = {**scope, "method": "GET"}

        async def head_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = _with_head_allowed(message)
            elif head and message["type"] == "http.response.body":
                message = {**message, "body": b""}
            await send(message)

        await self.app(scope, receive, head_send)
