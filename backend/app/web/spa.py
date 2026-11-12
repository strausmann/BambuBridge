"""Serve the built web UI (single page application) from the backend.

``mount_spa`` registers one catch-all ``GET`` route after every router. A path that names
a file of the build is served from it; any other path gets ``index.html`` so client-side
routes survive a reload, except paths the server owns: ``/api/...``, ``/auth/...``,
``/docs`` and ``/openapi.json`` keep their JSON 404, and a missing ``/assets/...`` file is
a real 404 (a browser that asked for a script must not get HTML).

Without ``index.html`` in the build directory the server runs API-only: one warning, no
route.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from starlette.exceptions import HTTPException

from app.web.security_headers import NO_CACHE

_log = logging.getLogger(__name__)

IMMUTABLE = "public, max-age=31536000, immutable"

# Paths owned by the server; never answered with the app shell.
_RESERVED = ("api", "auth", "docs", "openapi.json")


def is_reserved(path: str) -> bool:
    """``path`` without the leading slash belongs to the server, not to the web UI."""
    return any(path == name or path.startswith(name + "/") for name in _RESERVED)


def mount_spa(app: FastAPI, dist_dir: Path) -> bool:
    """Serve ``dist_dir`` (a Vite build); call after all routers. Returns whether mounted."""
    index = dist_dir / "index.html"
    if not index.is_file():
        _log.warning("web UI build not found - running API-only")
        return False
    root = dist_dir.resolve()

    async def spa(request: Request) -> Response:
        full_path: str = request.path_params.get("full_path", "")
        if is_reserved(full_path):
            raise HTTPException(status_code=404)
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(root):
                is_asset = candidate.is_relative_to(root / "assets")
                return FileResponse(
                    candidate, headers={"Cache-Control": IMMUTABLE if is_asset else NO_CACHE}
                )
            if full_path.startswith("assets/"):
                raise HTTPException(status_code=404)
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": NO_CACHE})

    app.add_route("/{full_path:path}", spa, methods=["GET"], include_in_schema=False)
    return True
