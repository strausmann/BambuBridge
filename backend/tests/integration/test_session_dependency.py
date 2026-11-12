from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.exc import InvalidRequestError

from app.db.session import get_session

APP_DIR = Path(__file__).resolve().parents[2] / "app"
# Request handlers live here; CLI code (e.g. app/security/rotation.py) opens its own
# sessions and may use begin().
API_DIR = APP_DIR / "api"


class _Request:
    def __init__(self, app: FastAPI) -> None:
        self.app = app


async def test_request_session_already_has_a_transaction(app: FastAPI):
    # get_session acquires the connection up front (503 translation), which also starts
    # the transaction. Handlers therefore commit() or use begin_nested(); begin() raises.
    sessions = get_session(_Request(app))  # type: ignore[arg-type]
    session = await anext(sessions)
    try:
        assert session.in_transaction()
        with pytest.raises(InvalidRequestError):
            await session.begin()
        async with session.begin_nested():
            pass
        await session.commit()
    finally:
        await sessions.aclose()


def test_no_handler_calls_session_begin():
    # Source guard, not a behaviour test: it matches the text ``.begin(`` on a name ending
    # in ``session``. It cannot see aliases (``s = session; s.begin()``), ``getattr`` calls
    # or a begin() in a helper outside app/api/ that a handler calls; the test above pins
    # the behaviour itself.
    pattern = re.compile(r"\bsession\.begin\(")
    hits = [
        f"{path.relative_to(APP_DIR.parent)}:{number}"
        for path in sorted(API_DIR.rglob("*.py"))
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        if pattern.search(line)
    ]
    assert list(API_DIR.rglob("*.py")), "guard scans nothing"
    assert hits == [], f"session.begin() in request code: {hits}"
