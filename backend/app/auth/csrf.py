"""CSRF and origin checks for requests authenticated by the session cookie.

The CSRF token is derived from the session token (HMAC with a key derived from
``BAMBUBRIDGE_SECRET_KEY``), so nothing extra is stored. The browser reads it from the
non-HttpOnly CSRF cookie (or ``GET /api/v1/auth/session``) and sends it in
``X-BambuBridge-CSRF`` with every state-changing request. In addition the request's
``Origin`` must be the origin of ``BAMBUBRIDGE_PUBLIC_URL``. Requests authenticated by
the API token header are exempt: a browser never attaches that header on its own.

Error responses carry fixed texts only; neither the presented nor the expected token is
ever echoed or logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from fastapi import Request

from app.api.errors import ApiError

CSRF_HEADER = "X-BambuBridge-CSRF"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def derive_token(key: bytes, session_token: str) -> str:
    """CSRF token of a session: ``base64url(HMAC-SHA256(key, session_token))``."""
    digest = hmac.new(key, b"csrf:" + session_token.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def is_unsafe(request: Request) -> bool:
    return request.method.upper() in UNSAFE_METHODS


def check_origin(request: Request, public_origin: str) -> None:
    """Raise 403 ``origin_mismatch`` unless ``Origin`` equals the public origin."""
    values = request.headers.getlist("origin")
    origin = values[0].strip().rstrip("/").lower() if len(values) == 1 else ""
    if not origin or not hmac.compare_digest(origin.encode(), public_origin.encode()):
        raise ApiError(
            403,
            "origin_mismatch",
            "Origin not allowed",
            detail="State-changing browser requests must come from the public URL.",
        )


def check_token(request: Request, expected: str) -> None:
    """Raise 403 ``csrf_failed`` unless the CSRF header equals ``expected`` (constant time)."""
    presented = request.headers.get(CSRF_HEADER, "")
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise ApiError(
            403,
            "csrf_failed",
            "CSRF check failed",
            detail=f"Send the session's CSRF token in the {CSRF_HEADER} header.",
        )
