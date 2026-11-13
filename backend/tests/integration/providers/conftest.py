from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import make_session_factory
from app.events.partitions import ensure_partitions
from app.providers.manager import ProviderManager
from tests.conftest import issue_token
from tests.integration.providers import fakes

PROVIDERS_URL = "/api/v1/providers"


@pytest_asyncio.fixture(autouse=True)
async def current_partitions(engine: AsyncEngine) -> None:
    async with make_session_factory(engine)() as session:
        await ensure_partitions(session, datetime.now(UTC))
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def fake_types(app: FastAPI) -> AsyncIterator[None]:
    """Register the fake provider types in this app's registry; release hung ones after."""
    fakes.HangingStopProvider.release = asyncio.Event()
    fakes.HangingStartProvider.release = asyncio.Event()
    fakes.RecordingProvider.probes = []
    fakes.RecordingProvider.starts = []
    for cls in fakes.FAKES:
        app.state.provider_registry.register(cls)
    yield
    fakes.HangingStopProvider.release.set()
    fakes.HangingStartProvider.release.set()


@pytest_asyncio.fixture
async def admin_token(engine: AsyncEngine) -> str:
    """An admin token that polling tests cannot exhaust (the default is 60 a minute)."""
    return await issue_token(engine, "admin", rate_limit_per_minute=10_000)


@pytest_asyncio.fixture
async def manager(app: FastAPI) -> AsyncIterator[ProviderManager]:
    """The app's provider manager, started (ASGITransport runs no lifespan)."""
    mgr: ProviderManager = app.state.provider_manager
    await mgr.start()
    try:
        yield mgr
    finally:
        await mgr.stop()


async def eventually[T](
    probe: Callable[[], Awaitable[T]], accept: Callable[[T], bool], timeout: float
) -> T:
    """Call ``probe`` until ``accept`` holds or ``timeout`` passes; return the last value."""
    deadline = time.monotonic() + timeout
    while True:
        value = await probe()
        if accept(value) or time.monotonic() >= deadline:
            return value
        await asyncio.sleep(0.05)


async def create(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    r = await client.post(PROVIDERS_URL, json=body)
    assert r.status_code == 201, r.text
    created: dict[str, Any] = r.json()
    return created


async def state_of(client: httpx.AsyncClient, instance_id: str) -> dict[str, Any]:
    r = await client.get(f"{PROVIDERS_URL}/{instance_id}")
    assert r.status_code == 200, r.text
    status: dict[str, Any] = r.json()["status"]
    return status
