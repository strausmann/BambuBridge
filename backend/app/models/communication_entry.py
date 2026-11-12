"""Communication log: one row per exchange with a provider, already masked.

Written by :class:`app.events.communication.CommunicationRecorder`, which masks secrets and
bounds the sizes before a row is built; nothing else may insert here. The table is
partitioned by month on ``occurred_at`` like ``events`` (children
``communication_log_yYYYYmMM``, no default partition), hence the primary key
``(id, occurred_at)``. Old rows are removed by :mod:`app.events.retention`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CommunicationEntry(Base):
    __tablename__ = "communication_log"
    __table_args__ = (
        CheckConstraint("direction IN ('outbound', 'inbound')", name="direction"),
        Index("ix_communication_log_instance_id_occurred_at", "instance_id", "occurred_at"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=text("clock_timestamp()")
    )
    # The provider instance that talked. No foreign key: the log outlives a removed instance.
    instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL: there was no answer (connection error, timeout).
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    request_headers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_headers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A body, a header list or another text was longer than is stored.
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
