from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.build_info import BUILD_ID, VERSION
from app.web.version_header import VERSION_HEADER


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/api/v1/info", 200),
        ("GET", "/api/v1/admin/api-keys", 401),
        ("GET", "/api/v1/nope", 404),
        ("DELETE", "/api/v1/info", 405),
        ("PUT", "/api/v1/settings", 401),
    ],
)
async def test_every_api_response_has_version_header(
    client: httpx.AsyncClient, method: str, path: str, status: int
):
    r = await client.request(method, path)
    assert r.status_code == status, r.text
    assert r.headers[VERSION_HEADER] == f"{VERSION}+{BUILD_ID}"
    assert len(r.headers.get_list(VERSION_HEADER)) == 1


async def test_internal_error_has_version_header(app: FastAPI):
    @app.get("/api/v1/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/v1/boom")
    assert r.status_code == 500
    assert r.headers[VERSION_HEADER] == f"{VERSION}+{BUILD_ID}"


async def test_non_api_responses_have_no_version_header(client: httpx.AsyncClient):
    assert VERSION_HEADER not in (await client.get("/healthz")).headers
