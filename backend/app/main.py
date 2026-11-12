"""Application factory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.exc import DBAPIError

from app.api.errors import CONNECTION_ERRORS, DatabaseUnavailableError, register_error_handlers
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
from app.db.session import connected, make_session_factory
from app.events.partitions import PartitionMaintenance
from app.events.retention import RetentionMaintenance
from app.events.service import EventService
from app.repositories import api_keys as api_keys_repo
from app.security.secret_box import secret_box_from_settings
from app.settings_store.listener import SettingsListener
from app.settings_store.store import SettingsStore
from app.web.body_limit import BodySizeLimitMiddleware
from app.web.head import HeadAsGetMiddleware
from app.web.security_headers import SecurityHeadersMiddleware
from app.web.spa import mount_spa
from app.web.version_header import VersionHeaderMiddleware

_log = logging.getLogger(__name__)
_STARTUP_DB_ERRORS: tuple[type[BaseException], ...] = (
    *CONNECTION_ERRORS,
    DatabaseUnavailableError,
    TimeoutError,
)
BOOTSTRAP_CHECK_TIMEOUT_SECONDS = 3.0


async def warn_if_bootstrap_open(app: FastAPI) -> None:
    """Warn while ``BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY`` is set and bootstrap is still open.

    An unreachable or stalled database skips the check, and so does any other database
    error (for example a schema that is not migrated): the server must always start.
    """
    settings: Settings = app.state.settings
    if not settings.bootstrap_admin_key.get_secret_value():
        return

    async def closed() -> bool:
        async with app.state.session_factory() as session:
            await connected(session)
            return await api_keys_repo.usable_admin_token_exists(session)

    try:
        if await asyncio.wait_for(closed(), timeout=BOOTSTRAP_CHECK_TIMEOUT_SECONDS):
            return
    except _STARTUP_DB_ERRORS:
        return
    except DBAPIError:
        _log.warning("bootstrap state check skipped: database error")
        return
    _log.warning(
        "BAMBUBRIDGE_BOOTSTRAP_ADMIN_KEY is set and bootstrap is open (no usable admin "
        "token exists): anyone who can reach the API and knows the key can create an admin "
        "token. Create the first admin token, then remove the variable."
    )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    ui_sessions.warn_if_insecure(app.state.settings)
    await warn_if_bootstrap_open(app)
    # The listener loads every setting once connected and keeps the store current.
    listener = SettingsListener(app.state.engine, app.state.settings_store)
    app.state.settings_listener = listener
    # Monthly partitions of the event tables: now, and every day at 00:05 UTC.
    partition_maintenance = PartitionMaintenance(app.state.session_factory)
    app.state.partition_maintenance = partition_maintenance
    # Retention of events and the communication log: now (in the background), and every day
    # at 00:15 UTC. It reads its periods from the database itself, not from the store's cache.
    retention_maintenance = RetentionMaintenance(
        app.state.session_factory, app.state.settings_store
    )
    app.state.retention_maintenance = retention_maintenance
    try:
        await listener.start()
        await partition_maintenance.start()
        await retention_maintenance.start()
        yield
    finally:
        await retention_maintenance.stop()
        app.state.retention_maintenance = None
        await partition_maintenance.stop()
        app.state.partition_maintenance = None
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
    app.state.event_service = EventService(app.state.settings_store)
    app.state.partition_maintenance = None
    app.state.retention_maintenance = None
    app.state.session_keys = ui_sessions.session_keys(settings)
    # Per process (see app.auth.rate_limit): requests per token, failed checks per prefix and
    # per client address, sign-in attempts and failed bootstrap keys per client address.
    app.state.rate_limiter = SlidingWindowRateLimiter()
    app.state.failed_auth_limiter = SlidingWindowRateLimiter()
    app.state.failed_auth_client_limiter = SlidingWindowRateLimiter()
    app.state.sign_in_limiter = SlidingWindowRateLimiter()
    app.state.failed_bootstrap_limiter = SlidingWindowRateLimiter()
    register_error_handlers(app)
    # Wraps the error middleware (an oversize body never reaches a handler) and is wrapped
    # by the header middlewares below, so the 413 carries them too.
    app.add_middleware(BodySizeLimitMiddleware)
    # Added after the error middleware, so they wrap it: problem responses get the headers.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(VersionHeaderMiddleware)
    # Outermost: every layer below sees a HEAD request as the GET it stands for.
    app.add_middleware(HeadAsGetMiddleware)
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
