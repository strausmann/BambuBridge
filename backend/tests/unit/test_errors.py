from __future__ import annotations

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.api.errors import InternalErrorMiddleware


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


async def test_middleware_reraises_when_response_already_started():
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("late failure")

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    with pytest.raises(RuntimeError, match="late failure"):
        await InternalErrorMiddleware(app)({"type": "http"}, _receive, send)
    assert [m["type"] for m in sent] == ["http.response.start"]


async def test_middleware_passes_non_http_scopes_through():
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])
        raise RuntimeError("lifespan failure is not turned into a response")

    async def send(message: Message) -> None:  # pragma: no cover - never called
        raise AssertionError(message)

    with pytest.raises(RuntimeError):
        await InternalErrorMiddleware(app)({"type": "lifespan"}, _receive, send)
    assert seen == ["lifespan"]
