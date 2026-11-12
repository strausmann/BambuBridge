"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routes import api_keys, health
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.config import Settings, get_settings
from app.db.engine import make_engine
from app.db.session import make_session_factory


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        await app.state.engine.dispose()


def create_app(settings: Settings, *, web_dist_dir: Path | None = None) -> FastAPI:
    """Build the FastAPI application.

    ``web_dist_dir`` is the built web UI directory; it is served from a later task on.
    The engine connects lazily, so building the app needs no database.
    """
    app = FastAPI(title="BambuBridge", docs_url=None, redoc_url=None, lifespan=_lifespan)
    app.state.settings = settings
    app.state.web_dist_dir = web_dist_dir
    app.state.engine = make_engine(settings.database_url.get_secret_value())
    app.state.session_factory = make_session_factory(app.state.engine)
    # Per process (see app.auth.rate_limit).
    app.state.rate_limiter = SlidingWindowRateLimiter()
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(api_keys.router)
    return app


@lru_cache
def _default_app() -> FastAPI:
    return create_app(get_settings(), web_dist_dir=Path("/opt/app/web"))


def __getattr__(name: str) -> FastAPI:
    """Lazily build ``app.main:app`` for uvicorn without reading settings at import time."""
    if name == "app":
        return _default_app()
    raise AttributeError(name)
