"""Bodies of ``/api/v1/settings``.

``SettingView.value`` is always ``null`` for a secret: a secret is reported only as
``set`` / ``undecryptable``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.settings_store.registry import SettingType


class SettingView(BaseModel):
    key: str
    type: SettingType
    section: str
    value: Any = Field(description="Effective value; always null for secrets")
    default: Any = Field(description="Default value; always null for secrets")
    set: bool = Field(description="A value is stored (otherwise the default applies)")
    undecryptable: bool = Field(description="A stored secret cannot be decrypted")
    min: int | None = None
    max: int | None = None
    choices: list[str] | None = Field(default=None, description="Allowed values, if fixed")


class SettingsUpdate(BaseModel):
    """``null`` resets a setting to its default; ``null`` or ``""`` clears a secret."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, Any] = Field(max_length=100)
