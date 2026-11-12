"""Bodies of the system routes (``/readiness``, ``/api/v1/info``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Status = Literal["ok", "unavailable"]


class Readiness(BaseModel):
    database: Status
    listener: Status


class Info(BaseModel):
    name: Literal["BambuBridge"] = "BambuBridge"
    version: str
    build: str
