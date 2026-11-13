"""Retention against the real database clock (the other retention tests replace it)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events import retention
from app.events.partitions import ensure_partitions
from app.events.retention import RetentionMaintenance, RetentionResult, run_retention
from app.models.communication_entry import CommunicationEntry
from app.settings_store.store import SettingsStore

INSTANCE = uuid.UUID("00000000-0000-4000-8000-0000000000c2")


async def _database_now(sessions: async_sessionmaker[AsyncSession]) -> datetime:
    async with sessions() as session:
        value = await session.scalar(text("SELECT clock_timestamp()"))
    assert isinstance(value, datetime)
    return value


async def _add_log(sessions: async_sessionmaker[AsyncSession], moment: datetime) -> None:
    async with sessions() as session:
        await ensure_partitions(session, moment - timedelta(days=2))
        session.add(
            CommunicationEntry(
                id=uuid.uuid4(),
                occurred_at=moment,
                instance_id=INSTANCE,
                direction="outbound",
                method="GET",
                target="/",
                duration_ms=1,
                request_headers={},
                response_headers={},
                truncated=False,
            )
        )
        await session.commit()


async def _log_count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(CommunicationEntry)) or 0)


async def test_the_database_clock_is_read_from_the_database(
    sessions: async_sessionmaker[AsyncSession],
):
    async with sessions() as session:
        value = await retention._database_now(session)
    assert value.utcoffset() is not None
    assert abs(value - datetime.now(UTC)) < timedelta(minutes=1)


async def test_cutoffs_follow_the_database_clock_not_the_application_clock(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    async with sessions() as session:
        await store.set_many(session, {"retention.communication_days": 1})
    # Two minutes newer than the database's cut-off, older than one the application clock
    # (three minutes ahead, within the allowed difference) would give.
    await _add_log(sessions, await _database_now(sessions) - timedelta(days=1, minutes=-2))

    async with sessions() as session:
        result = await run_retention(session, datetime.now(UTC) + timedelta(minutes=3), store)

    assert result.skipped is False
    assert await _log_count(sessions) == 1


async def test_a_host_clock_far_ahead_drops_nothing(
    sessions: async_sessionmaker[AsyncSession],
    store: SettingsStore,
    caplog: pytest.LogCaptureFixture,
):
    # Audit H9: with the host clock 160 days ahead every log partition used to be dropped.
    await _add_log(sessions, await _database_now(sessions))
    async with sessions() as session:
        before = await session.scalar(
            text("SELECT count(*) FROM pg_inherits WHERE inhparent = 'communication_log'::regclass")
        )
    job = RetentionMaintenance(
        sessions, store, clock=lambda: datetime.now(UTC) + timedelta(days=160)
    )

    with caplog.at_level(logging.WARNING, logger="app.events.retention"):
        assert await job.run_once() is True

    async with sessions() as session:
        after = await session.scalar(
            text("SELECT count(*) FROM pg_inherits WHERE inhparent = 'communication_log'::regclass")
        )
    assert after == before
    assert await _log_count(sessions) == 1
    assert [r.getMessage().startswith("retention skipped:") for r in caplog.records] == [True]


async def test_a_run_with_matching_clocks_is_not_skipped(
    sessions: async_sessionmaker[AsyncSession], store: SettingsStore
):
    async with sessions() as session:
        result = await run_retention(session, datetime.now(UTC), store)
    assert result == RetentionResult()
