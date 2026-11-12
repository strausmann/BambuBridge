"""Definition of every runtime setting: type, default, section and bounds.

There is no environment override: the database is the only source of runtime settings.
For a ``secret`` setting ``min`` is the minimum length of a non-empty value; an empty value
means "not set".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

SettingType = Literal["str", "int", "bool", "url", "secret", "choice"]

_MAX_TEXT = 256
_MAX_URL = 2048
_MAX_SECRET = 4096

# Pangolin's badger only removes ``Remote-*`` request headers before it sets its own, so
# any other header name could be forged by the client.
SSO_USER_HEADERS = ("Remote-User", "Remote-User-Id", "Remote-Email")


class SettingsError(Exception):
    """Base class; ``code`` is the machine-readable error code for the API."""

    code = "settings_error"

    def __init__(self, message: str, *, keys: list[str] | None = None) -> None:
        super().__init__(message)
        self.keys = keys or []


class UnknownSettingError(SettingsError):
    code = "unknown_setting"


class InvalidSettingValueError(SettingsError):
    code = "invalid_value"


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: SettingType
    default: Any
    section: str
    min: int | None = None
    max: int | None = None
    choices: tuple[str, ...] | None = None


_DEFS: list[SettingDef] = [
    SettingDef("sso.user_header", "choice", "Remote-User", "sso", choices=SSO_USER_HEADERS),
    SettingDef("sso.trust_header", "str", "X-Pangolin-Token", "sso"),
    # Empty (default) switches SSO off.
    SettingDef("sso.trust_token", "secret", "", "sso", min=32),
    SettingDef("auth.sign_in_limit_per_minute", "int", 10, "auth", min=1, max=600),
    SettingDef("retention.events_days", "int", 90, "retention", min=1, max=3650),
    SettingDef("retention.communication_days", "int", 30, "retention", min=1, max=3650),
    SettingDef("events.dedup_window_seconds", "int", 600, "events", min=0, max=86400),
]

SETTINGS: dict[str, SettingDef] = {d.key: d for d in _DEFS}


def validate_value(d: SettingDef, value: Any) -> Any:
    """Return the normalised value or raise ``InvalidSettingValueError``.

    The message names the key and the rule, never the offending value (it may be a secret).
    """

    def bad(message: str) -> InvalidSettingValueError:
        return InvalidSettingValueError(f"{d.key}: {message}", keys=[d.key])

    if d.type == "bool":
        if not isinstance(value, bool):
            raise bad("expected a boolean")
        return value
    if d.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad("expected an integer")
        if (d.min is not None and value < d.min) or (d.max is not None and value > d.max):
            raise bad(f"must be between {d.min} and {d.max}")
        return value
    if not isinstance(value, str):
        raise bad("expected a string")
    if d.type == "secret":
        # Printable ASCII only: the value is sent in an HTTP header.
        if len(value) > _MAX_SECRET or any(not 0x20 <= ord(c) <= 0x7E for c in value):
            raise bad("must be printable ASCII")
        if value and d.min is not None and len(value) < d.min:
            raise bad(f"must be empty or at least {d.min} characters")
        return value
    text = value.strip()
    if d.type == "choice":
        if text not in (d.choices or ()):
            raise bad("must be one of: " + ", ".join(d.choices or ()))
        return text
    if d.type == "url":
        return _validate_url(text, bad)
    if len(text) > _MAX_TEXT:
        raise bad("too long")
    return text


def _validate_url(text: str, bad: Any) -> str:
    if text == "":
        return ""
    try:
        parts = urlsplit(text)
        host = parts.hostname
        _ = parts.port
    except ValueError:
        raise bad("not a valid URL") from None
    if parts.scheme not in ("http", "https") or not host or len(text) > _MAX_URL:
        raise bad("must be an http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise bad("credentials in the URL are not allowed")
    if any(c.isspace() for c in text):
        raise bad("not a valid URL")
    return text.rstrip("/")
