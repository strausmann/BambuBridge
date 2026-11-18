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

- ``E2E_BOOTSTRAP_KEY``: the bootstrap key of this run. The Playwright configuration makes a
  random one per run and hands the same value to the tests. Without it the server makes its
  own, which nobody else knows.

- ``E2E_WEB_DIST_NEXT_DIR``: optional, a second build of the web UI with another build id
  (``E2E_NEXT_BUILD_ID``, default ``e2e-next``). With it the server serves a working copy of
  ``E2E_WEB_DIST_DIR``, and ``POST /__e2e/next-build`` turns the running server into the next
  release: the next build is copied over the working copy and ``X-BambuBridge-Version`` reports
  the next build id, as after a deployment. The update test (``frontend/e2e/update.spec.ts``)
  uses it.

Two control paths exist only here: ``POST /__e2e/reset`` empties every table, forgets the
rate-limit counters and goes back to the first build, so each browser test starts from a fresh
install (bootstrap open); ``POST /__e2e/next-build`` is described above.

The server is a tool on a developer's machine, and it is built so that a web page open in a
browser on that machine cannot use it:

- It refuses to start when uvicorn is told to listen on anything but the loopback interface,
  and it refuses every request that did not arrive on a loopback address.
- It answers only for the ``Host`` ``127.0.0.1:<port>`` or ``localhost:<port>``. A page that
  points its own host name at 127.0.0.1 (DNS rebinding) sends its own name and is refused.
- The reset path needs the header ``X-BambuBridge-E2E: reset`` (the next-build path
  ``X-BambuBridge-E2E: next-build``). A page of another origin
  cannot send a custom header without a preflight, which the server does not grant.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from alembic import command
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.rate_limit import SlidingWindowRateLimiter
from app.build_info import VERSION
from app.config import Settings
from app.main import create_app
from app.migrations import make_alembic_config
from tests.db_support import admin_url, truncate_all, url_for_database

RESET_PATH = "/__e2e/reset"
RESET_HEADER = "X-BambuBridge-E2E"
RESET_HEADER_VALUE = "reset"
NEXT_BUILD_PATH = "/__e2e/next-build"
NEXT_BUILD_HEADER_VALUE = "next-build"
DEFAULT_NEXT_BUILD_ID = "e2e-next"
_VERSION_HEADER = b"x-bambubridge-version"
DEFAULT_PORT = 8765
LOOPBACK_NAMES = ("127.0.0.1", "localhost")
_LIMITERS = (
    "rate_limiter",
    "failed_auth_limiter",
    "failed_auth_client_limiter",
    "sign_in_limiter",
    "failed_bootstrap_limiter",
)


def e2e_settings(database_url: str, port: int, bootstrap_key: str) -> Settings:
    """Settings of the server under test: fake key material, the loopback public URL."""
    key = base64.urlsafe_b64encode(b"e2e-secret-key-0123456789abcdef!").decode()
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=database_url,  # type: ignore[arg-type]
        secret_key=key,  # type: ignore[arg-type]
        public_url=f"http://127.0.0.1:{port}",  # type: ignore[arg-type]
        bootstrap_admin_key=bootstrap_key,  # type: ignore[arg-type]
    )


def is_loopback(host: str) -> bool:
    """True for ``localhost`` and for addresses of the loopback interface (127.0.0.0/8, ::1)."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def refuse_non_loopback_bind(argv: Sequence[str]) -> None:
    """Stop when the uvicorn command line names a host other than the loopback interface."""
    host = "127.0.0.1"  # uvicorn's default
    for index, arg in enumerate(argv):
        if arg == "--host" and index + 1 < len(argv):
            host = argv[index + 1]
        elif arg.startswith("--host="):
            host = arg.removeprefix("--host=")
    if not is_loopback(host):
        raise RuntimeError(
            f"tests.e2e_app must only listen on the loopback interface, not on {host!r}: "
            "it has a path that empties the database"
        )


class LoopbackOnly:
    """Refuses requests that did not arrive on a loopback address or name another host.

    A pure ASGI middleware around the whole app, the web UI included.
    """

    def __init__(self, app: ASGIApp, port: int) -> None:
        self.app = app
        self.hosts = frozenset(f"{name}:{port}".encode() for name in LOOPBACK_NAMES)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        server = scope.get("server")
        named = [value for key, value in scope["headers"] if key == b"host"]
        arrived_on_loopback = server is None or is_loopback(str(server[0]))
        if not arrived_on_loopback or len(named) != 1 or named[0].lower() not in self.hosts:
            refused = Response("This test server answers on the loopback interface only.\n", 421)
            await refused(scope, receive, send)
            return
        await self.app(scope, receive, send)


class Builds:
    """The two builds of the update test and the working copy the server serves.

    ``serving`` is what ``mount_spa`` got: a copy of ``first``. ``to_next`` copies ``next`` over
    it (new hashed files next to the old ones, as on a real server between two releases) and
    makes the version header report ``version``; ``to_first`` restores the copy.
    """

    def __init__(self, first: Path, next_dir: Path, next_build_id: str) -> None:
        self.first = first
        self.next = next_dir
        self.build_id = next_build_id
        self.version = f"{VERSION}+{next_build_id}"
        self.serving = Path(tempfile.mkdtemp(prefix="bb-e2e-dist-"))
        self.override: bytes | None = None
        self.to_first()

    def to_first(self) -> None:
        for child in self.serving.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        shutil.copytree(self.first, self.serving, dirs_exist_ok=True)
        self.override = None

    def to_next(self) -> None:
        shutil.copytree(self.next, self.serving, dirs_exist_ok=True)
        self.override = self.version.encode("latin-1")


INFO_PATH = "/api/v1/info"


class VersionOverride:
    """Reports the next build once the server was switched to it: in ``X-BambuBridge-Version``
    of every API answer, and as ``build`` in the body of ``GET /api/v1/info`` (the device page
    shows it as the server's build, so header and body must agree)."""

    def __init__(self, app: ASGIApp, builds: Builds) -> None:
        self.app = app
        self.builds = builds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        override = self.builds.override
        if scope["type"] != "http" or override is None:
            await self.app(scope, receive, send)
            return

        is_info = scope["path"] == INFO_PATH and scope["method"] == "GET"
        held: list[Message] = []

        def with_version(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
            if any(key.lower() == _VERSION_HEADER for key, _ in headers):
                headers = [(k, v) for k, v in headers if k.lower() != _VERSION_HEADER]
                headers.append((_VERSION_HEADER, override))
            return headers

        async def send_with_version(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": with_version(list(message.get("headers", [])))}
                if is_info:
                    held.append(message)
                    return
            elif is_info and message["type"] == "http.response.body":
                held.append(message)
                if message.get("more_body", False):
                    return
                start, *bodies = held
                content = b"".join(part.get("body", b"") for part in bodies)
                if start["status"] == 200:
                    data = json.loads(content)
                    data["build"] = self.builds.build_id
                    content = json.dumps(data).encode()
                headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(content)).encode()))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": content})
                return
            await send(message)

        await self.app(scope, receive, send_with_version)


async def _reset(request: Request) -> Response:
    """Back to a fresh install: empty tables and memory, no rate-limit history, the first build."""
    if request.headers.get(RESET_HEADER) != RESET_HEADER_VALUE:
        return Response(status_code=403)
    app: FastAPI = request.app
    await truncate_all(app.state.engine)
    # What lives in memory follows the empty database: running provider instances are stopped
    # (they would keep emitting for rows that are gone) and the settings are the defaults again.
    await app.state.provider_manager.start_all()
    async with app.state.session_factory() as session:
        await app.state.settings_store.load(session)
    for name in _LIMITERS:
        setattr(app.state, name, SlidingWindowRateLimiter())
    builds: Builds | None = app.state.e2e_builds
    if builds is not None:
        builds.to_first()
    return Response(status_code=204)


async def _next_build(request: Request) -> Response:
    """The running server becomes the next release (only with ``E2E_WEB_DIST_NEXT_DIR``)."""
    if request.headers.get(RESET_HEADER) != NEXT_BUILD_HEADER_VALUE:
        return Response(status_code=403)
    builds: Builds | None = request.app.state.e2e_builds
    if builds is None:
        return Response(status_code=404)
    builds.to_next()
    return Response(status_code=204)


def build_app(
    database_url: str,
    port: int,
    web_dist_dir: Path | None,
    bootstrap_key: str | None = None,
    *,
    next_dist_dir: Path | None = None,
    next_build_id: str = DEFAULT_NEXT_BUILD_ID,
) -> FastAPI:
    """The production app on ``database_url`` plus the control paths and the loopback guard.

    Without ``bootstrap_key`` a random one is made; it is kept on ``app.state.e2e_bootstrap_key``.
    With ``next_dist_dir`` (and ``web_dist_dir``) the web UI is served from a working copy that
    ``POST /__e2e/next-build`` switches to the next build.
    """
    key = bootstrap_key or secrets.token_urlsafe(32)
    builds = (
        Builds(web_dist_dir, next_dist_dir, next_build_id)
        if web_dist_dir is not None and next_dist_dir is not None
        else None
    )
    served = builds.serving if builds is not None else web_dist_dir
    app = create_app(e2e_settings(database_url, port, key), web_dist_dir=served)
    app.state.e2e_bootstrap_key = key
    app.state.e2e_builds = builds
    # First in the table: the web UI's catch-all route would answer the paths otherwise.
    app.router.routes.insert(0, Route(RESET_PATH, _reset, methods=["POST"]))
    app.router.routes.insert(0, Route(NEXT_BUILD_PATH, _next_build, methods=["POST"]))
    if builds is not None:
        app.add_middleware(VersionOverride, builds=builds)
    app.add_middleware(LoopbackOnly, port=port)
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
    refuse_non_loopback_bind(sys.argv)
    port = int(os.environ.get("E2E_PORT", str(DEFAULT_PORT)))
    dist = Path(os.environ.get("E2E_WEB_DIST_DIR", "../frontend/dist"))
    key = os.environ.get("E2E_BOOTSTRAP_KEY") or None
    next_dist = os.environ.get("E2E_WEB_DIST_NEXT_DIR")
    return build_app(
        prepare_database(f"bb_e2e_{port}"),
        port,
        dist,
        key,
        next_dist_dir=Path(next_dist) if next_dist else None,
        next_build_id=os.environ.get("E2E_NEXT_BUILD_ID", DEFAULT_NEXT_BUILD_ID),
    )


def __getattr__(name: str) -> FastAPI:
    """Build ``tests.e2e_app:app`` for uvicorn on first use, not at import by pytest."""
    if name == "app":
        return _default_app()
    raise AttributeError(name)
