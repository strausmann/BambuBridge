"""Input checks of ``emit``: nothing the database would refuse reaches it."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events import service as service_module
from app.events.service import (
    MAX_DEDUP_KEY_LENGTH,
    MAX_PAYLOAD_BYTES,
    MAX_PAYLOAD_DEPTH,
    EventService,
    SourceBusyError,
)
from tests.integration.events.conftest import EVENT_TYPE, SOURCE_A, SOURCE_B, counts, emit

MARKER = "SECRETTOKEN-abc123"


def _nested(levels: int) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for _ in range(levels - 1):
        value = {"a": value}
    return value


async def _emit(service: EventService, session: AsyncSession, **overrides: Any) -> uuid.UUID | None:
    arguments: dict[str, Any] = {
        "type": EVENT_TYPE,
        "source_instance_id": SOURCE_A,
        "payload": {},
        "schema_version": 1,
    }
    arguments.update(overrides)
    return await service.emit(session, **arguments)


async def _usable(
    service: EventService, session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The refused call left the caller's transaction alone: it can still write and commit."""
    assert await _emit(service, session) is not None
    await session.commit()
    assert await counts(sessions) == (1, 1)


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "PLA\x00x"},
        {"na\x00me": 1},
        {"n": "a\ud800b"},
        {"n": "\udc00"},
        {"a\udfff": 1},
        {"list": [1, {"deep": ["ok", "x\x00"]}]},
        {"t": float("nan")},
        {"t": [float("inf")]},
        {"t": {"u": float("-inf")}},
        {1: "number as key"},
        {"when": datetime(2026, 1, 1, tzinfo=UTC)},
        {"raw": b"bytes"},
        {"set": {1, 2}},
        {"id": SOURCE_A},
        _nested(MAX_PAYLOAD_DEPTH + 1),
    ],
    ids=[
        "nul-in-value",
        "nul-in-key",
        "surrogate-in-value",
        "low-surrogate",
        "surrogate-in-key",
        "nul-nested",
        "nan",
        "inf",
        "minus-inf",
        "key-not-str",
        "datetime",
        "bytes",
        "set",
        "uuid",
        "too-deep",
    ],
)
async def test_emit_rejects_a_payload_the_database_would_refuse(
    bad: dict[Any, Any],
    service: EventService,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
):
    payload = {"api_token": MARKER, **bad}
    await db_session.execute(text("SELECT 1"))  # the caller's transaction is already open

    with pytest.raises(ValueError, match="payload") as exc:
        await _emit(service, db_session, payload=payload)

    # The message names the rule, never a value of the payload.
    assert MARKER not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__suppress_context__ or exc.value.__context__ is None
    await _usable(service, db_session, sessions)


async def test_emit_accepts_every_json_value(service: EventService, db_session: AsyncSession):
    payload = {
        "text": "Größe 😀",
        "int": -3,
        "big": 2**70,
        "float": 1.5,
        "true": True,
        "none": None,
        "list": [1, [2, (3, 4)]],
        "nested": _nested(MAX_PAYLOAD_DEPTH - 1),
    }
    assert await _emit(service, db_session, payload=payload) is not None


async def test_emit_limits_the_payload_to_64_kib_of_json(
    service: EventService,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
):
    assert MAX_PAYLOAD_BYTES == 64 * 1024
    frame = len('{"a":""}')

    with pytest.raises(ValueError, match="payload"):
        await _emit(service, db_session, payload={"a": "x" * (MAX_PAYLOAD_BYTES - frame + 1)})
    # Bytes of the UTF-8 JSON text count, not characters.
    with pytest.raises(ValueError, match="payload"):
        await _emit(service, db_session, payload={"a": "ä" * (MAX_PAYLOAD_BYTES // 2)})
    with pytest.raises(ValueError, match="payload"):
        await _emit(service, db_session, payload={"n": 10**5000})

    assert await _emit(service, db_session, payload={"a": "x" * (MAX_PAYLOAD_BYTES - frame)})
    await db_session.commit()
    assert await counts(sessions) == (1, 1)


@pytest.mark.parametrize(
    "key",
    ["", "a\x00b", "a\ud800", "k" * (MAX_DEDUP_KEY_LENGTH + 1), 5, b"k"],
    ids=["empty", "nul", "surrogate", "too-long", "int", "bytes"],
)
async def test_emit_rejects_a_bad_dedup_key(
    key: object,
    service: EventService,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
):
    await db_session.execute(text("SELECT 1"))
    with pytest.raises(ValueError, match="dedup_key") as exc:
        await _emit(service, db_session, dedup_key=key)
    if isinstance(key, str) and key:
        assert key not in str(exc.value)
    await _usable(service, db_session, sessions)


async def test_emit_accepts_a_dedup_key_of_200_characters(
    service: EventService, db_session: AsyncSession
):
    assert MAX_DEDUP_KEY_LENGTH == 200
    key = "k" * MAX_DEDUP_KEY_LENGTH
    assert await _emit(service, db_session, dedup_key=key) is not None
    assert await _emit(service, db_session, dedup_key=key) is None


async def test_an_empty_dedup_key_is_not_a_key(service: EventService, db_session: AsyncSession):
    # Before the check, "" counted as a key and the second event was dropped.
    for _ in range(2):
        with pytest.raises(ValueError, match="dedup_key"):
            await _emit(service, db_session, dedup_key="")


@pytest.mark.parametrize(
    "source",
    [str(SOURCE_A), str(SOURCE_A).upper(), SOURCE_A.hex, SOURCE_A.int, SOURCE_A.bytes, ""],
    ids=["str", "upper-str", "hex", "int", "bytes", "empty"],
)
async def test_emit_takes_the_source_as_uuid_only(
    source: object,
    service: EventService,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
):
    await db_session.execute(text("SELECT 1"))
    with pytest.raises(ValueError, match="source_instance_id"):
        await _emit(service, db_session, source_instance_id=source, dedup_key="job-7")
    await _usable(service, db_session, sessions)


async def test_emit_takes_the_correlation_id_as_uuid_only(
    service: EventService, db_session: AsyncSession
):
    with pytest.raises(ValueError, match="correlation_id"):
        await _emit(service, db_session, correlation_id=str(uuid.uuid4()))


async def test_dedup_is_per_source_type_and_key(
    service: EventService, db_session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
):
    started = await _emit(service, db_session, type="integration.print.started", dedup_key="job-7")
    finished = await _emit(
        service, db_session, type="integration.print.finished", dedup_key="job-7"
    )
    again = await _emit(service, db_session, type="integration.print.finished", dedup_key="job-7")
    await db_session.commit()

    assert started is not None and finished is not None
    assert again is None
    assert await counts(sessions) == (2, 2)


async def test_emit_gives_up_when_the_source_stays_locked(
    service: EventService,
    db_session: AsyncSession,
    session2: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(service_module, "SOURCE_LOCK_TIMEOUT_SECONDS", 0.4)
    await emit(service, db_session, n=1)  # holds the lock of the source: no commit yet

    try:
        with pytest.raises(SourceBusyError, match="source"):
            await asyncio.wait_for(emit(service, session2, n=2), timeout=5)
    except TimeoutError:
        pytest.fail("emit waited for the source lock without a bound")
    await session2.rollback()

    # Another source is not affected, and the waiting side works again once the holder is done.
    assert await asyncio.wait_for(emit(service, session2, source=SOURCE_B, n=3), timeout=5)
    await session2.commit()
    await db_session.commit()
    assert await asyncio.wait_for(emit(service, session2, n=4), timeout=5)
    await session2.commit()
    assert await counts(sessions) == (3, 3)


def test_the_source_lock_wait_is_five_seconds():
    assert service_module.SOURCE_LOCK_TIMEOUT_SECONDS == 5.0


async def test_emit_leaves_the_callers_lock_timeout_alone(
    service: EventService, db_session: AsyncSession
):
    await db_session.execute(text("SET LOCAL lock_timeout = '1234ms'"))
    assert await emit(service, db_session) is not None
    assert (await db_session.execute(text("SHOW lock_timeout"))).scalar_one() == "1234ms"
