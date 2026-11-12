"""RFC 9457 problem details (successor of RFC 7807) for all error responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProblemDetail(BaseModel):
    """Problem details object returned with ``application/problem+json``."""

    type: str = Field(default="about:blank", description="URI reference identifying the problem")
    title: str = Field(description="Short human-readable summary")
    status: int = Field(description="HTTP status code")
    detail: str | None = Field(default=None, description="Explanation specific to this occurrence")
    instance: str | None = Field(default=None, description="URI reference of this occurrence")
    error_code: str | None = Field(
        default=None,
        description="Stable machine-readable error code (snake_case), e.g. ``invalid_token``",
    )
    extensions: dict[str, object] = Field(
        default_factory=dict, description="Problem-type-specific fields"
    )
