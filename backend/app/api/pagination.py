"""Keyset cursors and time ranges of the list routes (events, communication log).

A cursor is ``<occurred_at ISO 8601>|<id>`` in base64url without padding: the key of the
last row of a page. Lists are ordered newest first by ``(occurred_at, id)``, so the next page
holds the rows strictly before that key. Rows written after the first page have later times
and never shift a later page.
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Query
from pydantic import AwareDatetime

from app.api.errors import ApiError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
# A cursor is short; anything much longer is not one of ours.
MAX_CURSOR_LENGTH = 200

# The list parameters shared by the routes. A time without a zone fails validation (422).
FromQuery = Annotated[
    AwareDatetime | None,
    Query(alias="from", description="Earliest time (inclusive), ISO 8601 with a zone"),
]
ToQuery = Annotated[
    AwareDatetime | None,
    Query(alias="to", description="Latest time (exclusive), ISO 8601 with a zone"),
]
CursorQuery = Annotated[
    str | None,
    Query(description="``next_cursor`` of the previous page", max_length=MAX_CURSOR_LENGTH),
]
LimitQuery = Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Page size")]


def _invalid_cursor() -> ApiError:
    return ApiError(
        422,
        "invalid_cursor",
        "Invalid cursor",
        detail="The cursor is not one this API returned.",
    )


def encode_cursor(occurred_at: datetime, row_id: UUID) -> str:
    text = f"{occurred_at.astimezone(UTC).isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    """The key in ``cursor``; ``ApiError`` 422 ``invalid_cursor`` for anything else."""
    if len(cursor) > MAX_CURSOR_LENGTH:
        raise _invalid_cursor()
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        when, _, row_id = raw.partition("|")
        occurred_at = datetime.fromisoformat(when)
        key = UUID(row_id)
    except binascii.Error, UnicodeDecodeError, ValueError:
        raise _invalid_cursor() from None
    if occurred_at.tzinfo is None:
        raise _invalid_cursor()
    return occurred_at.astimezone(UTC), key


def check_range(start: datetime | None, end: datetime | None) -> tuple[datetime | None, ...]:
    """Both bounds in UTC; ``from`` must lie before ``to`` (422 ``invalid_range``)."""
    start_utc = start.astimezone(UTC) if start is not None else None
    end_utc = end.astimezone(UTC) if end is not None else None
    if start_utc is not None and end_utc is not None and start_utc >= end_utc:
        raise ApiError(
            422, "invalid_range", "Invalid time range", detail="'from' must be before 'to'."
        )
    return start_utc, end_utc
