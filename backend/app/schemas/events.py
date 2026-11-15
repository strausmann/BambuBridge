"""Bodies of ``/api/v1/events`` and ``/api/v1/communication``.

Times are ISO 8601 with a zone and always come back in UTC. A communication log entry is
returned exactly as it was stored: masked when it was written (see
:mod:`app.events.communication`); nothing here derives or adds a value.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

DeliveryStatus = Literal["pending", "done", "failed"]
Direction = Literal["outbound", "inbound"]


class StreamEvent(BaseModel):
    """An event as the live stream sends it (the ``data`` of an SSE message)."""

    id: UUID
    occurred_at: datetime
    type: str
    source_instance_id: UUID | None = Field(
        description="The provider instance the event came from; null for the bridge itself"
    )
    schema_version: int
    correlation_id: UUID | None
    payload: dict[str, Any]


class EventView(StreamEvent):
    delivery_status: DeliveryStatus = Field(
        description=(
            "Delivery state over all subscribers: failed = at least one delivery failed, "
            "pending = at least one is pending and none failed, done = all are done"
        )
    )


class DeliveryView(BaseModel):
    subscriber: str
    status: DeliveryStatus
    attempts: int
    last_error: str | None


class EventDetail(EventView):
    deliveries: list[DeliveryView]


class EventPage(BaseModel):
    items: list[EventView] = Field(description="Newest first")
    next_cursor: str | None = Field(
        description="Pass as ``cursor`` for the next (older) page; null on the last page"
    )


class CommunicationSummary(BaseModel):
    id: UUID
    occurred_at: datetime
    instance_id: UUID
    direction: Direction
    method: str
    target: str
    status: int | None = Field(description="Status code of the answer; null without an answer")
    duration_ms: int
    truncated: bool
    error: str | None


class CommunicationDetail(CommunicationSummary):
    request_headers: dict[str, Any]
    request_body: str | None
    response_headers: dict[str, Any]
    response_body: str | None


class CommunicationPage(BaseModel):
    items: list[CommunicationSummary] = Field(description="Newest first")
    next_cursor: str | None = Field(
        description="Pass as ``cursor`` for the next (older) page; null on the last page"
    )
