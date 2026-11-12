"""Outbox: one row per event and subscriber, written in the transaction of the event.

There is no foreign key to ``events``: old event partitions are dropped as a whole, and a
delivery whose event is gone is still handed to its subscriber (without the event).

``claimed_by`` / ``claimed_until`` are the lease of the worker that took a pending delivery
(see :mod:`app.events.outbox`); both are NULL when nobody holds it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventDelivery(Base):
    __tablename__ = "event_deliveries"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'done', 'failed')", name="status"),
        CheckConstraint("(claimed_by IS NULL) = (claimed_until IS NULL)", name="lease"),
        # The order in which ``claim`` hands deliveries out.
        Index("ix_event_deliveries_claim", "subscriber", "status", "event_occurred_at", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subscriber: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
