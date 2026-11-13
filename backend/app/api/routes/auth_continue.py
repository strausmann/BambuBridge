"""``GET /auth/continue?next=<path>``: finish a sign-in with a full-page navigation.

The web UI sends the browser here (outside ``/api``, so the service worker never answers
it). With a valid session the browser is sent on to ``next``; otherwise the active identity
providers are asked, and a recognised identity opens a session (cookies set) before the
redirect. Without either the answer is 401. ``next`` is followed only when it is a plain
relative path on this host (see :func:`safe_next`); anything else redirects to ``/``.

The 401 is a problem document, except for a browser navigation (``Accept`` names
``text/html``): the web UI sends the browser here when a session ended, and a JSON page would
leave the person on a dead end. That 401 is a small page that moves on to the sign-in of the
web UI (``/sign-in?redirect=<next>``) by a meta refresh, with a link for browsers that do not
follow one. No script: the Content-Security-Policy allows none inline.
"""

from __future__ import annotations

import html
import re
from typing import Annotated
from urllib.parse import quote, unquote, urlsplit

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.auth import sessions as ui_sessions
from app.auth.dependencies import session_cookie
from app.auth.sign_in import check_sign_in_limit, open_identity_session
from app.db.session import get_session
from app.schemas.problem import ProblemDetail

router = APIRouter(tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

MAX_NEXT_LENGTH = 2048
_DECODE_ROUNDS = 3
# Characters a browser removes from a URL before parsing it.
_BROWSER_STRIPPED = re.compile(r"[\t\n\r]")
# An encoded ``?`` or ``#`` in the path: a browser keeps it in the path, but one more round
# of decoding here would move the rest into the query or fragment and hide dot segments
# that the browser resolves (``/a%3f/%2e%2e//host`` has the pathname ``//host``).
_ENCODED_QUERY_OR_FRAGMENT = re.compile(r"%(3f|23)", re.IGNORECASE)


def _has_control(text: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in text)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 section 5.2.4 for an absolute path, as browsers apply it."""
    segments = path.split("/")
    out: list[str] = []
    for segment in segments:
        if segment == ".":
            continue
        if segment == "..":
            if len(out) > 1:
                out.pop()
            continue
        out.append(segment)
    if segments[-1] in (".", ".."):
        out.append("")
    return "/".join(out)


def _looks_absolute(path: str) -> bool:
    if not path.startswith("/") or path.startswith(("//", "/\\")):
        return True
    parts = urlsplit(path)
    if parts.scheme or parts.netloc or _ENCODED_QUERY_OR_FRAGMENT.search(parts.path):
        return True
    # ``/.//host`` resolves to the path ``//host``: same origin today, but a page that
    # navigates to its own pathname would leave the site.
    return _remove_dot_segments(parts.path).startswith(("//", "/\\"))


def safe_next(value: str | None) -> str:
    r"""``value`` if it is a relative path on this host, else ``"/"``.

    The value itself must be printable ASCII without backslash or whitespace (browsers drop
    tabs and newlines, so ``/\t/evil`` would become ``//evil``). Refused besides: anything
    not starting with a single ``/``; ``//host`` and ``/\host`` (which browsers treat as
    another host), also when it only appears after resolving dot segments (``/.//host``,
    ``/x/..//host``); a scheme or authority; an encoded ``?`` or ``#`` in the path. These
    shape checks are repeated after up to three rounds of percent-decoding (with tabs and
    newlines removed, as a browser would, and no other control character allowed), so
    encoded variants such as ``/%2F%2Fevil``, ``/%5Cevil`` or ``/a%253f/...`` are refused
    as well.
    """
    if not value or len(value) > MAX_NEXT_LENGTH:
        return "/"
    if any(not 0x21 <= ord(c) <= 0x7E or c == "\\" for c in value):
        return "/"
    candidate = value
    for _ in range(_DECODE_ROUNDS + 1):
        stripped = _BROWSER_STRIPPED.sub("", candidate)
        if "\\" in candidate or _has_control(stripped) or _looks_absolute(stripped):
            return "/"
        decoded = unquote(candidate)
        if decoded == candidate:
            return value
        candidate = decoded
    return "/"  # still changing after several rounds: not a plain path


def wants_html(request: Request) -> bool:
    """The request is a browser navigation: its ``Accept`` header names ``text/html``."""
    return "text/html" in request.headers.get("accept", "").lower()


def sign_in_page(target: str) -> HTMLResponse:
    """401 for a browser: a page that moves on to the web UI's sign-in, remembering ``target``."""
    location = html.escape("/sign-in?redirect=" + quote(target, safe=""), quote=True)
    body = (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0; url={location}">'
        "<title>Sign-in required</title></head>"
        f'<body><p>Sign-in required. <a href="{location}">Continue to the sign-in</a>.</p>'
        "</body></html>\n"
    )
    return HTMLResponse(body, status_code=status.HTTP_401_UNAUTHORIZED)


@router.get(
    "/auth/continue",
    status_code=status.HTTP_303_SEE_OTHER,
    summary="Continue to the web UI after sign-in",
    response_class=RedirectResponse,
    responses={
        303: {"description": "Signed in; redirect to ``next``"},
        401: {
            "model": ProblemDetail,
            "description": "Not signed in; a browser navigation gets a page that moves on "
            "to the sign-in (text/html)",
        },
        503: {"model": ProblemDetail},
    },
)
async def auth_continue(
    request: Request,
    db: SessionDep,
    next_path: Annotated[str | None, Query(alias="next")] = None,
) -> Response:
    target = safe_next(next_path)
    token = session_cookie(request)
    if token is not None and await ui_sessions.load_valid(
        db, token, request.app.state.settings_store, request.app.state.session_keys
    ):
        return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    # A sign-in attempt from here on: the same per-client limit as POST /api/v1/auth/session.
    check_sign_in_limit(request)
    opened = await open_identity_session(request, db)
    if opened is None:
        if wants_html(request):
            return sign_in_page(target)
        raise ApiError(401, "not_authenticated", "Authentication required")
    new_token = opened.token
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    ui_sessions.set_cookies(
        response, request.app.state.settings, request.app.state.session_keys, new_token
    )
    return response
