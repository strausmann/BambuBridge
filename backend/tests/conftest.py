"""Shared pytest fixtures. Database fixtures arrive with the database task."""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    # Obviously fake values, derived at runtime from readable text.
    key = base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode()
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        secret_key=key,  # type: ignore[arg-type]
        public_url="https://bb.example.com",  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=create_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
