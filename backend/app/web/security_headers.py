"""Security headers, CSP and cache rules for every response.

CSP (after LPH ``backend/app/web/spa.py``): ``script-src 'self'`` with no hash and no
``'unsafe-inline'`` (the theme bootstrap ``theme-init.js`` is an external file) and no
``'wasm-unsafe-eval'`` (BambuBridge has no code scanner). ``style-src 'self'`` allows,
besides files, exactly the fixed inline styles react-aria injects, each by its hash; the
frontend build test keeps that list in sync with the bundle.

Cache rules: ``no-store`` for ``/api/``, ``/auth/``, ``/readiness``, ``/healthz`` and the
service worker ``/sw.js`` (never cache an answer that depends on who asks or a worker that
must update); ``no-cache`` (revalidate) for ``/index.html`` and ``/manifest.webmanifest``.
Hashed assets get their long cache from the SPA mount.

A pure ASGI middleware, so streamed responses are not buffered.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# react-aria injects two fixed ``<style>`` elements at runtime: the touch-action rule of
# usePress (id ``react-aria-pressable-style``) and, while a modal is open on iOS, the
# overscroll-behavior rule of the scroll lock. Same texts and hashes as LPH.
REACT_ARIA_STYLE_HASHES: tuple[str, ...] = (
    "'sha256-38RhXrc7EdReTKsOm23ZPOCUgniTUUcjky8QOOrQx6o='",
    "'sha256-gYiS/BvZvRcK27JIXTuwhZ3hs2+VJ1X+2gUlE+farlg='",
)

CSP = (
    "default-src 'self'; script-src 'self'; worker-src 'self'; "
    "img-src 'self' data: blob:; connect-src 'self'; "
    "style-src 'self' " + " ".join(REACT_ARIA_STYLE_HASHES) + "; "
    "object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

NO_STORE = "no-store"
NO_CACHE = "no-cache"

_NO_STORE_PREFIXES = ("/api/", "/auth/")
_NO_STORE_PATHS = frozenset({"/api", "/auth", "/readiness", "/healthz", "/sw.js"})
_NO_CACHE_PATHS = frozenset({"/index.html", "/manifest.webmanifest"})

_FIXED_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"same-origin"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
)


def cache_rule(path: str) -> str | None:
    """The forced ``Cache-Control`` for ``path``, or ``None`` to keep the route's own."""
    if path in _NO_STORE_PATHS or path.startswith(_NO_STORE_PREFIXES):
        return NO_STORE
    if path in _NO_CACHE_PATHS:
        return NO_CACHE
    return None


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cache = cache_rule(scope.get("path", ""))
        replaced = {name for name, _ in _FIXED_HEADERS}
        if cache is not None:
            replaced.add(b"cache-control")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() not in replaced
                ]
                headers.extend(_FIXED_HEADERS)
                if cache is not None:
                    headers.append((b"cache-control", cache.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
