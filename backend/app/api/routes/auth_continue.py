"""``GET /auth/continue?next=<path>``: finish a sign-in with a full-page navigation.

The web UI sends the browser here (outside ``/api``, so the service worker never answers
it). With a valid session the browser is sent on to ``next``; otherwise the active identity
providers are asked, and a recognised identity opens a session (cookies set) before the
redirect. Without either the answer is 401. ``next`` is followed only when it is a plain
relative path on this host (see :func:`safe_next`); anything else redirects to ``/``.
"""

from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import unquote, urlsplit

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.auth import sessions as ui_sessions
from app.auth.dependencies import session_cookie
from app.auth.sign_in import open_identity_session
from app.db.session import get_session
from app.schemas.problem import ProblemDetail

router = APIRouter(tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

MAX_NEXT_LENGTH = 2048
_DECODE_ROUNDS = 3
# Characters a browser removes from a URL before parsing it.
_BROWSER_STRIPPED = re.compile(r"[\t\n\r]")


def _has_control(text: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in text)


def _looks_absolute(path: str) -> bool:
    if not path.startswith("/") or path.startswith(("//", "/\\")):
        return True
    parts = urlsplit(path)
    return bool(parts.scheme or parts.netloc)


def safe_next(value: str | None) -> str:
    r"""``value`` if it is a relative path on this host, else ``"/"``.

    The value itself must be printable ASCII without backslash or whitespace (browsers drop
    tabs and newlines, so ``/\t/evil`` would become ``//evil``). Refused besides: anything
    not starting with a single ``/``; ``//host`` and ``/\host`` (which browsers treat as
    another host); a scheme or authority. These shape checks are repeated after up to three
    rounds of percent-decoding (with tabs and newlines removed, as a browser would, and
    no other control character allowed), so
    encoded variants such as ``/%2F%2Fevil`` or ``/%5Cevil`` are refused as well.
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


@router.get(
    "/auth/continue",
    status_code=status.HTTP_303_SEE_OTHER,
    summary="Continue to the web UI after sign-in",
    response_class=RedirectResponse,
    responses={
        303: {"description": "Signed in; redirect to ``next``"},
        401: {"model": ProblemDetail},
        503: {"model": ProblemDetail},
    },
)
async def auth_continue(
    request: Request,
    db: SessionDep,
    next_path: Annotated[str | None, Query(alias="next")] = None,
) -> RedirectResponse:
    target = safe_next(next_path)
    token = session_cookie(request)
    if token is not None and await ui_sessions.load_valid(
        db, token, request.app.state.settings_store, request.app.state.session_keys
    ):
        return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    opened = await open_identity_session(request, db)
    if opened is None:
        raise ApiError(401, "not_authenticated", "Authentication required")
    _row, new_token = opened
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    ui_sessions.set_cookies(
        response, request.app.state.settings, request.app.state.session_keys, new_token
    )
    return response
