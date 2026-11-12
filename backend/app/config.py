"""Startup configuration.

Exactly four values are read from the environment (prefix ``BAMBUBRIDGE_``).
Everything else is configured at runtime through the settings store. There is
no env file and no override of runtime settings by environment variable.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AnyHttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.security.keys import decode_secret_key

_BOOTSTRAP_MIN_LENGTH = 32


class Settings(BaseSettings):
    """The four startup settings."""

    model_config = SettingsConfigDict(
        env_prefix="BAMBUBRIDGE_",
        env_file=None,
        extra="forbid",
        # A mistyped secret must not be echoed in the validation error printed at startup.
        hide_input_in_errors=True,
    )

    # Contains the database password; SecretStr keeps it out of repr(), logs and tracebacks.
    database_url: SecretStr
    # Key for secrets stored in the database (base64url of exactly 32 bytes).
    secret_key: SecretStr
    # Public base URL (links, cookie scope).
    public_url: AnyHttpUrl
    # One-time bootstrap key; empty disables bootstrap, otherwise >= 32 characters.
    bootstrap_admin_key: SecretStr = SecretStr("")

    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: SecretStr) -> SecretStr:
        """Require base64url text that decodes to exactly 32 bytes (AES-256)."""
        text = v.get_secret_value().strip()
        decode_secret_key(text, name="BAMBUBRIDGE_SECRET_KEY")
        return SecretStr(text)

    @field_validator("bootstrap_admin_key")
    @classmethod
    def validate_bootstrap_key(cls, v: SecretStr) -> SecretStr:
        """Empty disables bootstrap; otherwise at least 32 non-whitespace characters."""
        value = v.get_secret_value().strip()
        if value and len(value) < _BOOTSTRAP_MIN_LENGTH:
            raise ValueError("bootstrap_admin_key must be empty or at least 32 characters")
        return SecretStr(value)


@lru_cache
def get_settings() -> Settings:
    """Return the settings, parsed once per process."""
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
