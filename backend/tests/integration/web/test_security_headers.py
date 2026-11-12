from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app
from app.web.security_headers import REACT_ARIA_STYLE_HASHES


def _directives(csp: str) -> dict[str, list[str]]:
    parts = [p.strip().split() for p in csp.split(";") if p.strip()]
    return {p[0]: p[1:] for p in parts}


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text("<!doctype html><title>BambuBridge</title>")
    (tmp_path / "sw.js").write_text("// service worker")
    (tmp_path / "manifest.webmanifest").write_text("{}")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-1234.js").write_text("// app")
    return tmp_path


@pytest.fixture
async def web_client(settings: Settings, dist: Path, engine: object):
    application = create_app(settings, web_dist_dir=dist)
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await application.state.engine.dispose()


async def test_csp_script_src_self_only(web_client: httpx.AsyncClient):
    for path in ("/", "/healthz", "/api/v1/info"):
        csp = (await web_client.get(path)).headers["content-security-policy"]
        directives = _directives(csp)
        assert directives["script-src"] == ["'self'"], path
        assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
        assert "'wasm-unsafe-eval'" not in csp
        assert directives["style-src"] == ["'self'", *REACT_ARIA_STYLE_HASHES]
        assert directives["frame-ancestors"] == ["'none'"]


async def test_fixed_security_headers(web_client: httpx.AsyncClient):
    r = await web_client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "same-origin"
    assert len(r.headers.get_list("content-security-policy")) == 1


@pytest.mark.parametrize(
    ("path", "cache"),
    [
        ("/api/v1/info", "no-store"),
        ("/api/v1/nope", "no-store"),
        ("/readiness", "no-store"),
        ("/healthz", "no-store"),
        ("/sw.js", "no-store"),
        ("/auth/continue", "no-store"),
        ("/index.html", "no-cache"),
        ("/manifest.webmanifest", "no-cache"),
        ("/", "no-cache"),
        ("/printers/1", "no-cache"),
        ("/assets/app-1234.js", "public, max-age=31536000, immutable"),
    ],
)
async def test_cache_control(web_client: httpx.AsyncClient, path: str, cache: str):
    r = await web_client.get(path)
    assert r.headers.get_list("cache-control") == [cache], path


async def test_headers_on_problem_responses(app: FastAPI, client: httpx.AsyncClient):
    r = await client.get("/api/v1/admin/api-keys")
    assert r.status_code == 401
    assert r.headers["cache-control"] == "no-store"
    assert "content-security-policy" in r.headers
