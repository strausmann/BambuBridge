"""Runtime settings table.

A plain value lives in ``value`` (JSONB). A secret is stored only as the sealed token in
``secret_token`` together with the id of the key that sealed it in ``secret_key_id``;
``value`` stays NULL for secrets, so a plaintext secret never reaches the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        CheckConstraint("(secret_token IS NULL) = (secret_key_id IS NULL)", name="secret_pair"),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    # none_as_null: Python None is SQL NULL, not the JSON value ``null``.
    value: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    secret_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_key_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Who wrote the value last (NULL: written before users existed or by the system).
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
