"""Events: what happened, written once and never changed.

The table is partitioned by month on ``occurred_at`` (children ``events_yYYYYmMM``, created
by :mod:`app.events.partitions`; there is no default partition). The partition key has to be
part of the primary key, hence ``(id, occurred_at)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_source_instance_id_occurred_at", "source_instance_id", "occurred_at"),
        Index("ix_events_type_occurred_at", "type", "occurred_at"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=text("clock_timestamp()")
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    # The provider instance the event came from; NULL for events of the bridge itself.
    source_instance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    dedup_key: Mapped[str | None] = mapped_column(Text, nullable=True)
