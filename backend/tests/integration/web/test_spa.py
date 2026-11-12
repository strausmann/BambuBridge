from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app

INDEX = "<!doctype html><title>BambuBridge shell</title>"


@pytest.fixture
async def web_client(settings: Settings, tmp_path: Path, engine: object):
    (tmp_path / "index.html").write_text(INDEX)
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("// app")
    (tmp_path / "robots.txt").write_text("User-agent: *")
    (tmp_path.parent / "secret.txt").write_text("outside the build")
    application = create_app(settings, web_dist_dir=tmp_path)
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await application.state.engine.dispose()


async def test_spa_fallback_excludes_api_docs_openapi_auth(web_client: httpx.AsyncClient):
    for path in ("/api/x", "/api", "/docs", "/docs/x", "/auth/x", "/auth"):
        r = await web_client.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/problem+json"), path
    r = await web_client.get("/auth/continue")
    assert r.status_code == 401
    assert INDEX not in r.text
    r = await web_client.get("/openapi.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


async def test_spa_serves_index_for_client_routes(web_client: httpx.AsyncClient):
    for path in ("/", "/printers", "/printers/1/settings"):
        r = await web_client.get(path)
        assert r.status_code == 200, path
        assert r.text == INDEX
        assert r.headers["content-type"].startswith("text/html")


async def test_spa_serves_files_and_404s_missing_assets(web_client: httpx.AsyncClient):
    assert (await web_client.get("/robots.txt")).text == "User-agent: *"
    assert (await web_client.get("/assets/app.js")).text == "// app"
    assert (await web_client.get("/assets/missing.js")).status_code == 404
    traversal = await web_client.get("/..%2Fsecret.txt")
    assert "outside the build" not in traversal.text


async def test_without_build_the_server_runs_api_only(
    settings: Settings, tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.WARNING, logger="app.web.spa"):
        application = create_app(settings, web_dist_dir=tmp_path)
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            assert (await c.get("/")).status_code == 404
    finally:
        await application.state.engine.dispose()
    assert "API-only" in caplog.text


async def test_control_characters_in_path_are_404_not_500(
    web_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.WARNING):
        for path in ("/x%00y", "/assets/a%00.js", "/%01"):
            r = await web_client.get(path)
            assert r.status_code == 404, (path, r.text)
    assert [rec for rec in caplog.records if rec.levelno >= logging.ERROR] == []


async def test_unknown_non_get_api_paths_are_404(web_client: httpx.AsyncClient):
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        for path in ("/api/v1/unknown", "/printers", "/auth/x"):
            r = await web_client.request(method, path)
            assert r.status_code == 404, (method, path)
            assert r.headers["content-type"].startswith("application/problem+json")
