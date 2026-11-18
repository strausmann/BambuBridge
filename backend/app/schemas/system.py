"""Bodies of the system routes (``/readiness``, ``/api/v1/info``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "unavailable"]


class Readiness(BaseModel):
    database: Status
    listener: Status


class Info(BaseModel):
    name: Literal["BambuBridge"] = "BambuBridge"
    version: str
    build: str
    bootstrap_open: bool = Field(
        description=(
            "The first admin token can still be created with the bootstrap key: a key is "
            "configured and no usable admin token exists. A hint for the sign-in page."
        )
    )
