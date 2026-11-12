"""OpenAPI completeness gate: every API route declares a scope or is explicitly public.

A route declares its scope through ``require_scope`` (or the bootstrap-aware create
dependency); FastAPI then lists the ``BambuBridgeKey`` security scheme with exactly one
scope on the operation. Anything else must be on ``PUBLIC_OPERATIONS``.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.config import Settings
from app.main import create_app

# The only operations that may be called without a token or session.
PUBLIC_OPERATIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("get", "/healthz"),
        ("post", "/api/v1/auth/session"),
        ("get", "/api/v1/info"),
    }
)
KEY_SCHEME = "BambuBridgeKey"
SCOPES = {"read", "operate", "admin"}
METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def application() -> FastAPI:
    key = base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://user:pw@db.example.invalid/bb",  # type: ignore[arg-type]
        secret_key=key,  # type: ignore[arg-type]
        public_url="https://bb.example.com",  # type: ignore[arg-type]
    )
    return create_app(settings)


@pytest.fixture(scope="module")
def schema(application: FastAPI) -> dict[str, Any]:
    return application.openapi()


def _operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method, path, op)
        for path, methods in schema["paths"].items()
        for method, op in methods.items()
        if method in METHODS
    ]


def _declared_scopes(op: dict[str, Any]) -> list[str]:
    return [
        scope
        for requirement in op.get("security") or []
        for scope in requirement.get(KEY_SCHEME, [])
    ]


def test_every_api_route_declares_scope_or_is_public(schema: dict[str, Any]):
    violations = []
    for method, path, op in _operations(schema):
        scopes = _declared_scopes(op)
        if (method, path) in PUBLIC_OPERATIONS:
            assert not scopes, f"{method.upper()} {path} is public but declares {scopes}"
            continue
        if len(scopes) != 1 or scopes[0] not in SCOPES:
            violations.append(f"{method.upper()} {path}: scopes {scopes}")
    assert violations == [], "routes without exactly one declared scope:\n" + "\n".join(violations)


def test_no_api_route_is_hidden_from_the_schema(application: FastAPI):
    # A route outside the schema would escape the scope check above.
    hidden = [
        route.path
        for route in application.routes
        if isinstance(route, APIRoute) and not route.include_in_schema
    ]
    assert hidden == []


def test_api_key_routes_require_admin(schema: dict[str, Any]):
    expected = {
        ("get", "/api/v1/admin/api-keys"),
        ("post", "/api/v1/admin/api-keys"),
        ("patch", "/api/v1/admin/api-keys/{key_id}"),
        ("delete", "/api/v1/admin/api-keys/{key_id}"),
    }
    found = {(m, p): _declared_scopes(op) for m, p, op in _operations(schema)}
    for operation in expected:
        assert found.get(operation) == ["admin"], operation


def test_security_schemes_are_api_key_headers(schema: dict[str, Any]):
    schemes = schema["components"]["securitySchemes"]
    assert schemes[KEY_SCHEME] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-BambuBridge-Key",
        "description": schemes[KEY_SCHEME]["description"],
    }
    assert schemes["BambuBridgeBootstrap"]["name"] == "X-BambuBridge-Bootstrap"


def test_every_operation_has_tag_and_summary(schema: dict[str, Any]):
    for method, path, op in _operations(schema):
        assert op.get("tags"), (method, path)
        assert op.get("summary"), (method, path)


def test_problem_detail_is_a_component(schema: dict[str, Any]):
    assert "ProblemDetail" in schema["components"]["schemas"]
