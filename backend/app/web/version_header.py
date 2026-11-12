"""``X-BambuBridge-Version: <VERSION>+<BUILD_ID>`` on every response under ``/api/``.

A pure ASGI middleware (``BaseHTTPMiddleware`` would buffer streamed responses). It sits
outside the error middleware, so problem responses (401, 404, 500) carry the header too.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.build_info import BUILD_ID, VERSION

VERSION_HEADER = "X-BambuBridge-Version"


def version_value() -> str:
    return f"{VERSION}+{BUILD_ID}"


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


class VersionHeaderMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._value = version_value().encode("latin-1")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_api(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        async def send_with_version(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != VERSION_HEADER.lower().encode()
                ]
                headers.append((VERSION_HEADER.lower().encode(), self._value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_version)
