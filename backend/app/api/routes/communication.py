"""Communication log: ``GET /api/v1/communication`` and ``/api/v1/communication/{entry_id}``.

Both need ``admin``: the log shows what was sent to and received from devices and services.
Entries are returned exactly as stored, and they were masked when they were written
(:mod:`app.events.communication`); nothing here reads a secret or derives a value.

Times work as in the event list (with a zone, UTC, ``from`` inclusive, ``to`` exclusive),
and so does paging (newest first, ``cursor``). ``status`` is a status code (``404``), a class
(``4xx``) or ``none`` for exchanges without an answer.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.api.pagination import (
    DEFAULT_LIMIT,
    CursorQuery,
    FromQuery,
    LimitQuery,
    ToQuery,
    check_range,
    decode_cursor,
    encode_cursor,
)
from app.auth.dependencies import AuthContext, require_scope
from app.db.session import get_session
from app.models.communication_entry import CommunicationEntry
from app.repositories import event_log
from app.schemas.events import CommunicationDetail, CommunicationPage, CommunicationSummary
from app.schemas.problem import ProblemDetail

router = APIRouter(prefix="/api/v1", tags=["communication"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminDep = Annotated[AuthContext, Depends(require_scope("admin"))]

STATUS_PATTERN = r"^([1-5][0-9][0-9]|[1-5]xx|none)$"

_BASE: dict[int | str, dict[str, Any]] = {
    code: {"model": ProblemDetail} for code in (401, 403, 429, 503)
}

_SUMMARY_FIELDS = tuple(CommunicationSummary.model_fields)
_DETAIL_FIELDS = tuple(CommunicationDetail.model_fields)


def _summary(entry: CommunicationEntry) -> CommunicationSummary:
    return CommunicationSummary.model_validate({f: getattr(entry, f) for f in _SUMMARY_FIELDS})


@router.get(
    "/communication",
    summary="List communication log entries",
    response_model=CommunicationPage,
    responses={**_BASE, 422: {"model": ProblemDetail}},
)
async def list_communication(
    session: SessionDep,
    _auth: AdminDep,
    start: FromQuery = None,
    end: ToQuery = None,
    instance: Annotated[uuid.UUID | None, Query(description="Provider instance")] = None,
    status: Annotated[
        str | None,
        Query(pattern=STATUS_PATTERN, description="Status code, class (4xx) or 'none'"),
    ] = None,
    cursor: CursorQuery = None,
    limit: LimitQuery = DEFAULT_LIMIT,
) -> CommunicationPage:
    start_utc, end_utc = check_range(start, end)
    key = decode_cursor(cursor) if cursor is not None else None
    rows = await event_log.list_communication(
        session,
        start=start_utc,
        end=end_utc,
        instance=instance,
        status=status,
        cursor=key,
        limit=limit,
    )
    page = rows[:limit]
    next_cursor = encode_cursor(page[-1].occurred_at, page[-1].id) if len(rows) > limit else None
    return CommunicationPage(items=[_summary(row) for row in page], next_cursor=next_cursor)


@router.get(
    "/communication/{entry_id}",
    summary="Get a communication log entry",
    response_model=CommunicationDetail,
    responses={**_BASE, 404: {"model": ProblemDetail}},
)
async def get_communication(
    entry_id: uuid.UUID, session: SessionDep, _auth: AdminDep
) -> CommunicationDetail:
    entry = await event_log.get_communication(session, entry_id)
    if entry is None:
        raise ApiError(404, "communication_entry_not_found", "Communication log entry not found")
    return CommunicationDetail.model_validate({f: getattr(entry, f) for f in _DETAIL_FIELDS})
