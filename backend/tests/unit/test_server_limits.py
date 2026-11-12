"""The HTTP server bounds the header block and chunked trailers (the body limit cannot)."""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator

import pytest
import uvicorn
from starlette.types import Receive, Scope, Send

from app.entrypoint import MAX_HEADER_BYTES, server_options

OVERSIZE = 4 * MAX_HEADER_BYTES


async def _reading_app(scope: Scope, receive: Receive, send: Send) -> None:
    assert scope["type"] == "http"
    while True:
        message = await receive()
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.fixture
async def port() -> AsyncIterator[int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    config = uvicorn.Config(
        _reading_app, lifespan="off", log_level="critical", **server_options("127.0.0.1")
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(500):
        if server.started:
            break
        await asyncio.sleep(0.01)
    assert server.started
    try:
        yield sock.getsockname()[1]
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)


async def _exchange(port: int, request: bytes) -> bytes:
    """Send ``request`` in pieces; return the response bytes (empty when the server closed)."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    try:
        for start in range(0, len(request), 8192):
            writer.write(request[start : start + 8192])
            await writer.drain()
        with contextlib.suppress(TimeoutError):
            return await asyncio.wait_for(reader.read(65536), 5)
        return b""
    except ConnectionError:
        return b""  # closed or reset while sending: refused
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError):
            await writer.wait_closed()


def _refused(response: bytes) -> bool:
    return response == b"" or response.startswith((b"HTTP/1.1 400", b"HTTP/1.1 431"))


def _padding(size: int) -> bytes:
    line = b"X-Pad: " + b"a" * 1000 + b"\r\n"
    return line * (size // len(line))


async def test_an_oversize_header_block_is_refused(port: int):
    request = b"GET / HTTP/1.1\r\nHost: test\r\n" + _padding(OVERSIZE) + b"\r\n"
    response = await _exchange(port, request)
    assert _refused(response), response[:80]


async def test_oversize_chunked_trailers_are_refused(port: int):
    request = (
        b"POST / HTTP/1.1\r\nHost: test\r\nTransfer-Encoding: chunked\r\n\r\n"
        b"5\r\nhello\r\n0\r\n" + _padding(OVERSIZE) + b"\r\n"
    )
    response = await _exchange(port, request)
    assert _refused(response), response[:80]


async def test_normal_requests_and_headers_below_the_cap_are_served(port: int):
    plain = await _exchange(port, b"GET / HTTP/1.1\r\nHost: test\r\nConnection: close\r\n\r\n")
    assert plain.startswith(b"HTTP/1.1 200")
    assert b"\r\nok\r\n" in plain
    padded = (
        b"GET / HTTP/1.1\r\nHost: test\r\nConnection: close\r\n"
        + _padding(MAX_HEADER_BYTES // 2)
        + b"\r\n"
    )
    assert (await _exchange(port, padded)).startswith(b"HTTP/1.1 200")
    chunked = (
        b"POST / HTTP/1.1\r\nHost: test\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n"
        b"\r\n5\r\nhello\r\n0\r\nX-Trailer: 1\r\n\r\n"
    )
    assert (await _exchange(port, chunked)).startswith(b"HTTP/1.1 200")


def test_the_header_cap_is_64_kib():
    assert MAX_HEADER_BYTES == 64 * 1024
