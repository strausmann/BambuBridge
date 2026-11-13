"""The public path list: files a browser (and an auth proxy) load without a sign-in.

``frontend/pwa-public-paths.json`` names them; the backend serves exactly these from the build
without app authentication. The API keeps asking for a sign-in, also on a path that merely
looks like one of the files.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.main import create_app
from app.web.spa import PUBLIC_PATHS, is_public_file

REPO = Path(__file__).resolve().parents[4]
FRONTEND_LIST = REPO / "frontend" / "pwa-public-paths.json"

# One real file per entry of the list (a directory entry gets one file in it).
FILES = {
    "sw.js": "self.addEventListener('fetch', () => {});",
    "manifest.webmanifest": '{"name": "BambuBridge"}',
    "index.html": "<!doctype html><title>BambuBridge shell</title>",
    "theme-init.js": "document.documentElement.dataset.theme = 'light';",
    "favicon.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>",
    "favicon.ico": "ico",
    "icons/icon-192.png": "png",
    "assets/index-abc123.js": "// app",
}


def sample_path(pattern: str) -> str:
    """A path the pattern covers that names one of FILES."""
    if not pattern.endswith("/*"):
        return pattern
    directory = pattern[1:-1]
    return "/" + next(name for name in FILES if name.startswith(directory))


@pytest.fixture
async def client(settings: Settings, tmp_path: Path, engine: object):
    for name, text in FILES.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    application = create_app(settings, web_dist_dir=tmp_path)
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await application.state.engine.dispose()


def test_backend_list_equals_the_frontend_list():
    assert list(PUBLIC_PATHS) == json.loads(FRONTEND_LIST.read_text())


def test_every_entry_has_a_sample_file():
    for pattern in PUBLIC_PATHS:
        assert is_public_file(sample_path(pattern)), pattern


@pytest.mark.parametrize("pattern", PUBLIC_PATHS)
async def test_each_public_path_is_served_without_a_cookie(client: httpx.AsyncClient, pattern: str):
    path = sample_path(pattern)
    r = await client.get(path)
    assert r.status_code == 200, path
    assert r.text == FILES[path.lstrip("/")], path
    assert "set-cookie" not in r.headers


async def test_service_worker_is_javascript_and_never_cached(client: httpx.AsyncClient):
    r = await client.get("/sw.js")
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-store"
    m = await client.get("/manifest.webmanifest")
    assert m.headers["content-type"].startswith("application/manifest+json")
    assert m.headers["cache-control"] == "no-cache"


async def test_a_missing_public_file_is_404_not_the_shell(
    client: httpx.AsyncClient, tmp_path: Path
):
    (tmp_path / "sw.js").unlink()
    for path in ("/sw.js", "/icons/missing.png", "/assets/missing.js", "/assets/x/y.js"):
        r = await client.get(path)
        assert r.status_code == 404, path
        assert "BambuBridge shell" not in r.text, path
    # Not on the list: a client route like any other path.
    assert (await client.get("/favicon.svg.map")).status_code == 200


async def test_the_list_opens_nothing_else(client: httpx.AsyncClient):
    for path in ("/api/v1/auth/session", "/api/v1/settings", "/api/v1/admin/api-keys"):
        r = await client.get(path)
        assert r.status_code == 401, path
    # A path that only starts like a public file is no public file.
    assert not is_public_file("/assets/../api/v1/settings")
    assert not is_public_file("/icons/")
    assert not is_public_file("/sw.js/x")
