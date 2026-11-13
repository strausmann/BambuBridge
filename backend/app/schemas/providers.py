"""Bodies of ``/api/v1/provider-types`` and ``/api/v1/providers``.

A secret is never part of a response: ``secrets`` maps each secret field to ``{set}``.
In a request, secrets are sent in ``config`` like any other field: a non-empty string sets
one, ``""`` or leaving it out keeps the stored one, ``null`` clears it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.providers.base import ProviderKind, ProviderStatusState

NAME_MAX_LENGTH = 100


def _check_name(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("must not be empty or start or end with white space")
    return value


class EventTypeView(BaseModel):
    name: str
    schema_version: int
    payload_schema: dict[str, Any]


class ActionView(BaseModel):
    name: str
    params_schema: dict[str, Any]


class ProviderTypeView(BaseModel):
    kind: ProviderKind
    type_name: str
    config_schema: dict[str, Any] = Field(
        description='JSON schema of the configuration; secret fields carry "x-secret": true'
    )
    event_types: list[EventTypeView]
    actions: list[ActionView]


class SecretState(BaseModel):
    set: bool = Field(description="A value is stored")


class StatusView(BaseModel):
    state: ProviderStatusState
    message: str | None
    since: datetime


class ProviderInstanceView(BaseModel):
    id: UUID
    kind: ProviderKind
    type_name: str
    name: str
    enabled: bool
    config: dict[str, Any] = Field(description="Plain configuration; never holds a secret")
    secrets: dict[str, SecretState]
    status: StatusView
    created_by: UUID | None
    updated_by: UUID | None
    updated_at: datetime


class ProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProviderKind
    type_name: str = Field(max_length=63)
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict, max_length=100)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _check_name(value)


class ProviderUpdate(BaseModel):
    """Fields left out stay as they are; ``config`` is merged field by field."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    enabled: bool | None = None
    config: dict[str, Any] = Field(default_factory=dict, max_length=100)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _check_name(value)


class ProviderTest(BaseModel):
    """Unsaved form values; for a stored instance merged over what is stored."""

    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any] = Field(default_factory=dict, max_length=100)


class ProbeResultView(BaseModel):
    ok: bool
    message: str
    duration_ms: int


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    params: dict[str, Any] = Field(default_factory=dict, max_length=100)


class ActionResult(BaseModel):
    result: dict[str, Any]
