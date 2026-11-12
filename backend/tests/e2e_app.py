"""The app the browser tests (Playwright, ``frontend/e2e``) run against.

``uvicorn tests.e2e_app:app`` serves the real FastAPI app and the built web UI on a
throw-away PostgreSQL database. Nothing is faked: sign-in, sessions, CSRF and bootstrap
are the production code paths.

Environment:

- ``BAMBUBRIDGE_TEST_DATABASE_URL``: the PostgreSQL server of the test suite (see
  ``tests/conftest.py``). The module creates the database ``bb_e2e_<port>`` on it, migrated
  to head, and drops a leftover of the same name first.
- ``E2E_PORT``: the port uvicorn listens on (default 8765); it forms the public URL
  ``http://127.0.0.1:<port>``, which the sign-in checks ``Origin`` against.
- ``E2E_WEB_DIST_DIR``: the built web UI (default ``../frontend/dist``).

One control path exists only here: ``POST /__e2e/reset`` empties every table and forgets
the rate-limit counters, so each browser test starts from a fresh install (bootstrap open).
The bootstrap key is the fixed, obviously fake ``E2E_BOOTSTRAP_KEY``; the server must only
ever listen on the loopback interface.
"""

from __future__ import annotations

import asyncio
import base64
import os
import threading
from functools import lru_cache
from pathlib import Path

from alembic import command
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from app.auth.rate_limit import SlidingWindowRateLimiter
from app.config import Settings
from app.main import create_app
from app.migrations import make_alembic_config
from tests.db_support import admin_url, truncate_all, url_for_database

# Readable text, not a secret: the key of a server that exists only during a test run.
E2E_BOOTSTRAP_KEY = "e2e-bootstrap-key-for-browser-tests-only"
RESET_PATH = "/__e2e/reset"
DEFAULT_PORT = 8765
_LIMITERS = (
    "rate_limiter",
    "failed_auth_limiter",
    "failed_auth_client_limiter",
    "sign_in_limiter",
    "failed_bootstrap_limiter",
)


def e2e_settings(database_url: str, port: int) -> Settings:
    """Settings of the server under test: fake key material, the loopback public URL."""
    key = base64.urlsafe_b64encode(b"e2e-secret-key-0123456789abcdef!").decode()
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=database_url,  # type: ignore[arg-type]
        secret_key=key,  # type: ignore[arg-type]
        public_url=f"http://127.0.0.1:{port}",  # type: ignore[arg-type]
        bootstrap_admin_key=E2E_BOOTSTRAP_KEY,  # type: ignore[arg-type]
    )


async def _reset(request: Request) -> Response:
    """Back to a fresh install: empty tables, no rate-limit history."""
    app: FastAPI = request.app
    await truncate_all(app.state.engine)
    for name in _LIMITERS:
        setattr(app.state, name, SlidingWindowRateLimiter())
    return Response(status_code=204)


def build_app(database_url: str, port: int, web_dist_dir: Path | None) -> FastAPI:
    """The production app on ``database_url`` plus the reset path."""
    app = create_app(e2e_settings(database_url, port), web_dist_dir=web_dist_dir)
    # First in the table: the web UI's catch-all route would answer the path otherwise.
    app.router.routes.insert(0, Route(RESET_PATH, _reset, methods=["POST"]))
    return app


async def _recreate_database(name: str) -> None:
    admin = create_async_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()


def prepare_database(name: str) -> str:
    """Create ``name`` empty, migrate it to head and return its URL."""
    url = url_for_database(admin_url(), name)

    def work() -> None:
        asyncio.run(_recreate_database(name))
        command.upgrade(make_alembic_config(url), "head")

    # uvicorn imports this module inside its running event loop; the database work needs
    # loops of its own, so it runs on a separate thread.
    failure: list[BaseException] = []

    def guarded() -> None:
        try:
            work()
        except BaseException as exc:  # re-raised on the calling thread below
            failure.append(exc)

    thread = threading.Thread(target=guarded, name="e2e-database")
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return url


@lru_cache
def _default_app() -> FastAPI:
    port = int(os.environ.get("E2E_PORT", str(DEFAULT_PORT)))
    dist = Path(os.environ.get("E2E_WEB_DIST_DIR", "../frontend/dist"))
    return build_app(prepare_database(f"bb_e2e_{port}"), port, dist)


def __getattr__(name: str) -> FastAPI:
    """Build ``tests.e2e_app:app`` for uvicorn on first use, not at import by pytest."""
    if name == "app":
        return _default_app()
    raise AttributeError(name)
