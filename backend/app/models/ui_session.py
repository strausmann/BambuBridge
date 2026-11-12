"""Browser sessions of the web UI.

The cookie carries a random token; only its SHA-256 (``token_hash``) is stored, never the
token itself. A session belongs to a user and was opened either with an API token
(``api_key_id``) or by an identity provider (``identity_provider`` and ``identity_subject``).
``identity_binding`` is a keyed hash of the provider's binding material (for the Pangolin
header provider: the trust token), so rotating or clearing that material ends the session.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UiSession(Base):
    __tablename__ = "ui_sessions"
    __table_args__ = (CheckConstraint("scope IN ('read', 'operate', 'admin')", name="scope"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Set when the session was opened with an API token: the session ends with the token.
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=True
    )
    identity_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    identity_binding: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
