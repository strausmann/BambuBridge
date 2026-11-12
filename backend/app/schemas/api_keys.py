"""Request and response bodies of ``/api/v1/admin/api-keys``.

The token plaintext appears only in ``ApiKeyCreated`` (the POST response) and is kept out
of its repr; list and update responses carry the prefix only, never the hash.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.auth.scopes import Scope

Name = Annotated[str, Field(min_length=1, max_length=100, pattern=r"\S")]
Note = Annotated[str, Field(max_length=500)]


class ApiKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    scope: Scope
    note: Note | None = None
    expires_at: AwareDatetime | None = None
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)


class ApiKeyUpdate(BaseModel):
    """Only the fields that are sent change; ``null`` clears ``note`` and ``expires_at``."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    note: Note | None = None
    enabled: bool | None = None
    expires_at: AwareDatetime | None = None

    @field_validator("name", "enabled", mode="before")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Runs only for sent values (defaults are not validated): omitting keeps the
        # field, an explicit null is rejected because these fields cannot be cleared.
        if value is None:
            raise ValueError("must not be null")
        return value


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_user_id: UUID
    prefix: str
    name: str
    note: str | None
    scope: Scope
    expires_at: datetime | None
    last_used_at: datetime | None
    rate_limit_per_minute: int
    enabled: bool
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    token: str = Field(repr=False, description="The full token. Shown once, never again.")
