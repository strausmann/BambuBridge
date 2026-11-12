"""Serve the built web UI (single page application) from the backend.

``mount_spa`` registers one catch-all ``GET`` route after every router. A path that names
a file of the build is served from it; any other path gets ``index.html`` so client-side
routes survive a reload, except paths the server owns: ``/api/...``, ``/auth/...``,
``/docs`` and ``/openapi.json`` keep their JSON 404, and a missing ``/assets/...`` file is
a real 404 (a browser that asked for a script must not get HTML). The route takes every
method so that an unknown path answers 404 for any method; a wrong method on a path another
route knows still answers 405 with an ``Allow`` header, as without the web UI.

Without ``index.html`` in the build directory the server runs API-only: one warning, no
route.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from starlette.exceptions import HTTPException
from starlette.routing import Match
from starlette.types import Scope

from app.web.security_headers import NO_CACHE

_log = logging.getLogger(__name__)

IMMUTABLE = "public, max-age=31536000, immutable"

_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]

# Paths owned by the server; never answered with the app shell.
_RESERVED = ("api", "auth", "docs", "openapi.json")


def is_reserved(path: str) -> bool:
    """``path`` without the leading slash belongs to the server, not to the web UI."""
    return any(path == name or path.startswith(name + "/") for name in _RESERVED)


def _allowed_methods(app: FastAPI, scope: Scope, skip: object) -> list[str]:
    """Methods under which a route other than ``skip`` fully matches the path of ``scope``.

    Probes each method through the routes' public ``matches`` instead of reading their
    ``methods``: FastAPI wraps included routers in an object that reports a partial match
    without saying which methods the route accepts.
    """
    allowed: list[str] = []
    for method in _ALL_METHODS:
        probe = {**scope, "method": method}
        probe.pop("fastapi", None)  # per-lookup bookkeeping of FastAPI, never share it
        for route in app.router.routes:
            if getattr(route, "endpoint", None) is skip:
                continue
            if route.matches(probe)[0] is Match.FULL:
                allowed.append(method)
                break
    return allowed


def mount_spa(app: FastAPI, dist_dir: Path) -> bool:
    """Serve ``dist_dir`` (a Vite build); call after all routers. Returns whether mounted."""
    index = dist_dir / "index.html"
    if not index.is_file():
        _log.warning("web UI build not found - running API-only")
        return False
    root = dist_dir.resolve()

    async def spa(request: Request) -> Response:
        full_path: str = request.path_params.get("full_path", "")
        # Only GET/HEAD are answered from the build. Any other method is a 405 with Allow
        # when a route knows the path (this route matches every method, so Starlette
        # never reports the partial match itself), else a 404, as without the web UI.
        # Control characters (a NUL makes the filesystem calls raise) never name a file
        # of the build.
        if request.method not in ("GET", "HEAD"):
            allowed = _allowed_methods(request.app, request.scope, spa)
            if allowed:
                raise HTTPException(status_code=405, headers={"Allow": ", ".join(allowed)})
        if (
            request.method not in ("GET", "HEAD")
            or is_reserved(full_path)
            or any(ord(c) < 0x20 or ord(c) == 0x7F for c in full_path)
        ):
            raise HTTPException(status_code=404)
        if full_path:
            try:
                candidate = (root / full_path).resolve()
                found = candidate.is_file() and candidate.is_relative_to(root)
            except OSError, ValueError:
                raise HTTPException(status_code=404) from None
            if found:
                is_asset = candidate.is_relative_to(root / "assets")
                return FileResponse(
                    candidate, headers={"Cache-Control": IMMUTABLE if is_asset else NO_CACHE}
                )
            if full_path.startswith("assets/"):
                raise HTTPException(status_code=404)
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": NO_CACHE})

    app.add_route("/{full_path:path}", spa, methods=_ALL_METHODS, include_in_schema=False)
    return True
