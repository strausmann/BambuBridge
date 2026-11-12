"""OpenAPI completeness gate: every API route declares a scope or is explicitly public.

A route declares its scope through ``require_scope`` (or the bootstrap-aware create
dependency); FastAPI then lists the ``BambuBridgeKey`` security scheme with exactly one
scope on the operation. Anything else must be on ``PUBLIC_OPERATIONS``.

The schema tests check the *declaration* only. That the declared dependency actually
guards the route is checked separately on the route's dependant tree
(``test_every_non_public_route_is_guarded_by_a_scope_dependency``); the behaviour itself
is tested in ``tests/integration/api``.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, RouteContext, iter_route_contexts

from app.auth.dependencies import SCOPE_MARKER
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
    # Declaration only: see the module docstring and the dependant-tree test below.
    violations = []
    for method, path, op in _operations(schema):
        scopes = _declared_scopes(op)
        if (method, path) in PUBLIC_OPERATIONS:
            assert not scopes, f"{method.upper()} {path} is public but declares {scopes}"
            continue
        if len(scopes) != 1 or scopes[0] not in SCOPES:
            violations.append(f"{method.upper()} {path}: scopes {scopes}")
    assert violations == [], "routes without exactly one declared scope:\n" + "\n".join(violations)


def _api_routes(application: FastAPI) -> list[RouteContext]:
    """Every API route with its effective path and dependencies.

    ``application.routes`` holds included routers as unexpanded entries, so the routes are
    expanded with ``iter_route_contexts`` (the same walk FastAPI's OpenAPI uses).
    """
    routes = [
        ctx
        for ctx in iter_route_contexts(application.routes)
        if isinstance(ctx.original_route, APIRoute)
    ]
    assert routes, "no API routes found; the route walk is broken"
    return routes


def test_no_api_route_is_hidden_from_the_schema(application: FastAPI):
    # A route outside the schema would escape the scope check above.
    hidden = [ctx.path for ctx in _api_routes(application) if not ctx.include_in_schema]
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


def _guard_scopes(dependant: Dependant) -> list[str]:
    """Scopes of every scope-guard dependency anywhere in the dependant tree."""
    found = []
    call = dependant.call
    if call is not None and hasattr(call, SCOPE_MARKER):
        found.append(getattr(call, SCOPE_MARKER))
    for sub in dependant.dependencies:
        found.extend(_guard_scopes(sub))
    return found


def test_every_non_public_route_is_guarded_by_a_scope_dependency(
    application: FastAPI, schema: dict[str, Any]
):
    declared = {(m, p): _declared_scopes(op) for m, p, op in _operations(schema)}
    unguarded = []
    checked = 0
    for ctx in _api_routes(application):
        for method in sorted(m.lower() for m in ctx.methods or ()):
            checked += 1
            if (method, ctx.path) in PUBLIC_OPERATIONS:
                continue
            guards = _guard_scopes(ctx.dependant)
            if not guards:
                unguarded.append(f"{method.upper()} {ctx.path}")
                continue
            # The guard really enforces the scope the schema declares.
            assert guards == declared[(method, ctx.path)], (method, ctx.path, guards)
    assert checked == len(_operations(schema))  # every documented operation was walked
    assert unguarded == [], "routes without require_scope/require_admin_or_bootstrap:\n" + (
        "\n".join(unguarded)
    )
