"""Application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.routes import api_keys, auth_continue, auth_session, health, system
from app.api.routes import settings as settings_routes

# ``identity`` registers the built-in identity providers before any setting is validated.
# (Imported by name: ``import app.auth.identity`` would bind ``app`` in this module and
# shadow the lazy ``app`` attribute below.)
from app.auth import identity as _identity  # noqa: F401
from app.auth import sessions as ui_sessions
from app.auth.rate_limit import SlidingWindowRateLimiter
from app.config import Settings, get_settings
from app.db.engine import make_engine
from app.db.session import make_session_factory
from app.security.secret_box import secret_box_from_settings
from app.settings_store.listener import SettingsListener
from app.settings_store.store import SettingsStore
from app.web.security_headers import SecurityHeadersMiddleware
from app.web.spa import mount_spa
from app.web.version_header import VersionHeaderMiddleware


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    ui_sessions.warn_if_insecure(app.state.settings)
    # The listener loads every setting once connected and keeps the store current.
    listener = SettingsListener(app.state.engine, app.state.settings_store)
    app.state.settings_listener = listener
    try:
        await listener.start()
        yield
    finally:
        await listener.stop()
        app.state.settings_listener = None
        await app.state.engine.dispose()


def create_app(settings: Settings, *, web_dist_dir: Path | None = None) -> FastAPI:
    """Build the FastAPI application.

    ``web_dist_dir`` is the built web UI directory (served when it holds ``index.html``).
    The engine connects lazily, so building the app needs no database. Settings are loaded
    by the listener started in the lifespan; until then the store answers with defaults.
    """
    app = FastAPI(title="BambuBridge", docs_url=None, redoc_url=None, lifespan=_lifespan)
    app.state.settings = settings
    app.state.web_dist_dir = web_dist_dir
    app.state.engine = make_engine(settings.database_url.get_secret_value())
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.settings_store = SettingsStore(secret_box_from_settings(settings))
    app.state.settings_listener = None
    app.state.session_keys = ui_sessions.session_keys(settings)
    # Per process (see app.auth.rate_limit): requests per token, failed checks per prefix,
    # sign-in attempts per client address.
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.failed_auth_limiter = SlidingWindowRateLimiter()
    app.state.sign_in_limiter = SlidingWindowRateLimiter()
    register_error_handlers(app)
    # Added after the error middleware, so they wrap it: problem responses get the headers.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(VersionHeaderMiddleware)
    for router in (
        health.router,
        system.router,
        auth_session.router,
        auth_continue.router,
        api_keys.router,
        settings_routes.router,
    ):
        app.include_router(router)
    if web_dist_dir is not None:
        mount_spa(app, web_dist_dir)
    return app


@lru_cache
def _default_app() -> FastAPI:
    return create_app(get_settings(), web_dist_dir=Path("/opt/app/web"))


def __getattr__(name: str) -> FastAPI:
    """Lazily build ``app.main:app`` for uvicorn without reading settings at import time."""
    if name == "app":
        return _default_app()
    raise AttributeError(name)
