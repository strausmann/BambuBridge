from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.session import make_session_factory
from app.events.partitions import ensure_partitions
from app.events.service import EventService
from app.models.event import Event
from app.models.event_delivery import EventDelivery
from app.security.secret_box import secret_box_from_key
from app.settings_store.store import SettingsStore

SOURCE_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
SOURCE_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
EVENT_TYPE = "integration.demo.tick"


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_session_factory(engine)


@pytest_asyncio.fixture(autouse=True)
async def current_partitions(sessions: async_sessionmaker[AsyncSession]) -> None:
    """The partitions the running server would have: this month and the next two."""
    async with sessions() as session:
        await ensure_partitions(session, datetime.now(UTC))
        await session.commit()


@pytest.fixture
def store() -> SettingsStore:
    return SettingsStore(secret_box_from_key(b"A" * 32))


@pytest.fixture
def service(store: SettingsStore) -> EventService:
    return EventService(store)


@pytest_asyncio.fixture
async def session2(sessions: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """A second, independent session (the first one is ``db_session``)."""
    async with sessions() as session:
        yield session
        await session.rollback()


async def emit(
    service: EventService,
    session: AsyncSession,
    *,
    source: uuid.UUID | None = SOURCE_A,
    n: int = 0,
    dedup_key: str | None = None,
) -> uuid.UUID | None:
    return await service.emit(
        session,
        type=EVENT_TYPE,
        source_instance_id=source,
        payload={"n": n},
        schema_version=1,
        dedup_key=dedup_key,
    )


async def counts(sessions: async_sessionmaker[AsyncSession]) -> tuple[int, int]:
    """(events, deliveries) as a fresh session sees them, i.e. committed rows only."""
    async with sessions() as session:
        events = await session.scalar(select(func.count()).select_from(Event))
        deliveries = await session.scalar(select(func.count()).select_from(EventDelivery))
    return int(events or 0), int(deliveries or 0)
