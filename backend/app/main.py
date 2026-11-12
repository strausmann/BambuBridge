"""Application factory."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI

from app.api.routes import health
from app.config import Settings, get_settings


def create_app(settings: Settings, *, web_dist_dir: Path | None = None) -> FastAPI:
    """Build the FastAPI application.

    ``web_dist_dir`` is the built web UI directory; it is served from a later task on.
    """
    app = FastAPI(title="BambuBridge", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.web_dist_dir = web_dist_dir
    app.include_router(health.router)
    return app


@lru_cache
def _default_app() -> FastAPI:
    return create_app(get_settings(), web_dist_dir=Path("/opt/app/web"))


def __getattr__(name: str) -> FastAPI:
    """Lazily build ``app.main:app`` for uvicorn without reading settings at import time."""
    if name == "app":
        return _default_app()
    raise AttributeError(name)
