"""Every error is a problem-details body; exception messages and request input never leak."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError, MultipleResultsFound
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth.tokens import TOKEN_PREFIX
from app.config import Settings
from app.db.engine import make_engine
from app.main import create_app
from tests.conftest import KEY_HEADER

MARKER = "leak-marker-7f3k"
BASE = "/api/v1/admin/api-keys"


def _problem(r: httpx.Response, status: int, error_code: str) -> dict[str, object]:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == status
    assert body["error_code"] == error_code
    assert body["title"]
    return body


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=database_url,  # type: ignore[arg-type]
        secret_key=base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode(),  # type: ignore[arg-type]
        public_url="https://bb.example.com",  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def unreachable_client() -> AsyncIterator[httpx.AsyncClient]:
    # Nothing listens on port 1: connecting fails for real (no monkeypatching).
    application = create_app(_settings("postgresql+asyncpg://u:pw@127.0.0.1:1/bb"))
    transport = httpx.ASGITransport(app=application)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        await application.state.engine.dispose()


async def test_unreachable_database_is_503(unreachable_client: httpx.AsyncClient):
    token = TOKEN_PREFIX + "A" * 40
    r = await unreachable_client.get(BASE, headers={KEY_HEADER: token})
    body = _problem(r, 503, "database_unavailable")
    assert "127.0.0.1" not in r.text
    assert "Connect" not in str(body)


@pytest_asyncio.fixture
async def failing_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """The test app plus routes that raise errors which are not database outages."""

    @app.get("/test/file-not-found")
    async def file_not_found() -> None:
        raise FileNotFoundError(f"/etc/{MARKER}")

    @app.get("/test/integrity")
    async def integrity() -> None:
        raise IntegrityError(f"INSERT {MARKER}", {"p": MARKER}, Exception(MARKER))

    @app.get("/test/multiple")
    async def multiple() -> None:
        raise MultipleResultsFound(MARKER)

    @app.get("/test/unique-violation")
    async def unique_violation() -> None:
        raise IntegrityError("INSERT INTO t VALUES ($1)", (MARKER,), _UniqueViolationError())

    @app.get("/test/status-499")
    async def status_499() -> None:
        raise StarletteHTTPException(status_code=499, detail=MARKER)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class _UniqueViolationError(Exception):
    """Stands in for asyncpg's error: its text carries the conflicting values."""

    sqlstate = "23505"

    def __init__(self) -> None:
        super().__init__(f"duplicate key\nDETAIL:  Key (name)=({MARKER}) already exists.")


@pytest.mark.parametrize(
    "path", ["/test/file-not-found", "/test/integrity", "/test/multiple", "/test/unique-violation"]
)
async def test_non_database_errors_are_500(
    failing_client: httpx.AsyncClient, path: str, caplog: pytest.LogCaptureFixture
):
    r = await failing_client.get(path)
    _problem(r, 500, "internal_error")
    assert MARKER not in r.text
    assert caplog.records  # logged for the operator


@pytest.mark.parametrize("path", ["/test/file-not-found", "/test/multiple"])
async def test_non_database_errors_are_logged_with_traceback(
    failing_client: httpx.AsyncClient, path: str, caplog: pytest.LogCaptureFixture
):
    await failing_client.get(path)
    assert any(rec.exc_info for rec in caplog.records)


async def test_database_error_log_has_class_and_sqlstate_but_no_values(
    failing_client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
):
    caplog.set_level("DEBUG")
    _problem(await failing_client.get("/test/unique-violation"), 500, "internal_error")
    assert MARKER not in caplog.text  # message, exc_info and traceback text included
    for rec in caplog.records:
        assert MARKER not in rec.getMessage()
        assert rec.exc_info is None
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert "IntegrityError" in logged
    assert "23505" in logged


async def test_non_standard_status_code_gets_a_generic_title(failing_client: httpx.AsyncClient):
    body = _problem(await failing_client.get("/test/status-499"), 499, "http_error")
    assert body["title"] == "HTTP error"
    assert MARKER not in str(body)


async def test_malformed_uuid_is_not_echoed(admin_client: httpx.AsyncClient):
    # Pydantic's uuid_parsing message quotes the offending character and the length.
    r = await admin_client.delete(f"{BASE}/Ж{MARKER}")
    body = _problem(r, 422, "validation_failed")
    assert "Ж" not in r.text
    assert MARKER not in r.text
    assert str(len("Ж" + MARKER)) not in str(body["extensions"])
    errors = body["extensions"]["errors"]  # type: ignore[index]
    assert errors == [{"loc": ["path", "key_id"], "msg": "Invalid UUID", "type": "uuid_parsing"}]


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x" * 101, "scope": "read"},
        {"name": "x", "scope": "read", "rate_limit_per_minute": "x" + MARKER},
        {"name": "x", "scope": "read", "expires_at": f"20{MARKER}"},
        {"name": "x", "scope": "read", "rate_limit_per_minute": 10**9},
    ],
)
async def test_validation_messages_are_fixed_texts(
    admin_client: httpx.AsyncClient, payload: dict[str, object]
):
    r = await admin_client.post(BASE, json=payload)
    body = _problem(r, 422, "validation_failed")
    assert MARKER not in r.text
    assert "10000" not in r.text and "100" not in str(body["extensions"])


async def test_validation_error_is_problem_without_input(admin_client: httpx.AsyncClient):
    r = await admin_client.post(BASE, json={"name": "x", "scope": MARKER, MARKER: MARKER})
    body = _problem(r, 422, "validation_failed")
    assert MARKER not in r.text
    errors = body["extensions"]["errors"]  # type: ignore[index]
    locations = [e["loc"] for e in errors]  # type: ignore[union-attr]
    assert ["body", "scope"] in locations
    assert ["body", "<unknown field>"] in locations
    for error in errors:  # type: ignore[union-attr]
        assert set(error) == {"loc", "msg", "type"}


async def test_invalid_json_is_problem(admin_client: httpx.AsyncClient):
    r = await admin_client.post(
        BASE, content=f'{{"name": "{MARKER}"', headers={"content-type": "application/json"}
    )
    _problem(r, 422, "validation_failed")
    assert MARKER not in r.text


async def test_unknown_route_is_404_problem(client: httpx.AsyncClient):
    r = await client.get(f"/api/v1/{MARKER}")
    _problem(r, 404, "not_found")
    assert MARKER not in r.text


async def test_wrong_method_is_405_problem(client: httpx.AsyncClient):
    r = await client.put("/healthz")
    _problem(r, 405, "method_not_allowed")
    assert "GET" in r.headers["allow"]


async def test_engine_hides_bound_parameters():
    engine = make_engine("postgresql+asyncpg://u:pw@db.example.invalid/bb")
    try:
        assert engine.sync_engine.hide_parameters is True
    finally:
        await engine.dispose()
