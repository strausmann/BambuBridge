"""Liveness probe."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    """Report that the process is up. No auth, no version, no dependencies."""
    return {"status": "ok"}
