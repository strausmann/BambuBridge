"""Bodies of ``/api/v1/auth/session``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.auth.scopes import Scope


class SignInRequest(BaseModel):
    """Sign in with an API token. Without a body the identity providers are asked."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    token: str = Field(min_length=1, max_length=512)

    def __repr__(self) -> str:
        return "SignInRequest(token=<hidden>)"


class SessionInfo(BaseModel):
    kind: Literal["session", "token"]
    scope: Scope
    user: str | None = Field(default=None, description="Display name of the signed-in user")
    identity_provider: str | None = Field(
        default=None, description="Provider that opened the session; null for a token sign-in"
    )
    identity_subject: str | None = Field(
        default=None,
        description="Subject the identity provider reported; null for a token sign-in",
    )
    expires_at: datetime | None = None
    csrf_token: str | None = Field(
        default=None,
        description="Send in X-BambuBridge-CSRF with every state-changing request",
    )

    def __repr__(self) -> str:
        return f"SessionInfo(kind={self.kind!r}, scope={self.scope!r})"
