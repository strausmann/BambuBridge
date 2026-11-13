from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.engine import make_engine
from app.db.session import make_session_factory
from app.events import communication
from app.events.communication import (
    MAX_BODY_BYTES,
    MAX_HEADERS_INPUT,
    MAX_MASK_INPUT,
    CommunicationRecorder,
    Message,
    truncate_utf8,
)
from app.models.communication_entry import CommunicationEntry
from tests.conftest import DEAD_DATABASE_URL

INSTANCE = uuid.UUID("00000000-0000-4000-8000-0000000000c1")
# Obviously fake values, readable text only.
SECRET = "fake-access-code-0001"
OTHER = "zz-fake-value-0002"

recorder = CommunicationRecorder()


async def _record(session: AsyncSession, **overrides: Any) -> CommunicationEntry:
    arguments: dict[str, Any] = {
        "instance_id": INSTANCE,
        "method": "GET",
        "target": "https://printer.example.com/status",
        "status": 200,
        "duration_ms": 12,
        "request": Message(),
        "response": Message(),
    }
    arguments.update(overrides)
    await recorder.record(session, **arguments)
    await session.flush()
    return (await session.scalars(select(CommunicationEntry))).one()


async def _count(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as session:
        return int(await session.scalar(select(func.count()).select_from(CommunicationEntry)) or 0)


async def test_record_stores_a_masked_entry(db_session: AsyncSession):
    entry = await _record(
        db_session,
        method="POST",
        target=f"https://printer.example.com/v1/{SECRET}/print?access_token=abc123&page=2",
        status=201,
        duration_ms=345,
        request=Message(
            headers={
                "AUTHORIZATION": "Bearer abc.def",
                "x-bambubridge-KEY": "bb_x",
                "Content-Type": "application/json",
                "X-Trace": f"id {SECRET}",
            },
            body=json.dumps({"connection": {"access_code": "1234", "serial": "0001"}}),
        ),
        response=Message(
            headers=[("Set-Cookie", "a=1"), ("Set-Cookie", "b=2"), ("X-A", "1"), ("X-A", "2")],
            body=json.dumps({"ok": True, "echo": SECRET}).encode(),
        ),
        error=f"upstream said: token={OTHER} for https://user:hunter2@printer.example.com",
        secret_paths=["connection.access_code"],
        known_secrets=[SECRET, OTHER],
    )

    assert entry.instance_id == INSTANCE
    assert entry.direction == "outbound"
    assert (entry.method, entry.status, entry.duration_ms) == ("POST", 201, 345)
    assert entry.target == "https://printer.example.com/v1/***/print?access_token=***&page=2"
    assert entry.request_headers == {
        "AUTHORIZATION": "***",
        "x-bambubridge-KEY": "***",
        "Content-Type": "application/json",
        "X-Trace": "id ***",
    }
    assert entry.request_body == '{"connection":{"access_code":"***","serial":"0001"}}'
    assert entry.response_headers == {"Set-Cookie": "***", "X-A": ["1", "2"]}
    assert entry.response_body == '{"ok":true,"echo":"***"}'
    assert entry.error == "upstream said: token=*** for https://user:***@printer.example.com"
    assert entry.truncated is False
    assert entry.occurred_at is not None and entry.id is not None
    stored = json.dumps(
        [
            entry.target,
            entry.request_headers,
            entry.request_body,
            entry.response_headers,
            entry.response_body,
            entry.error,
        ]
    )
    for value in (SECRET, OTHER, "hunter2", "abc123", "abc.def", "bb_x", "1234", "a=1", "b=2"):
        assert value not in stored


async def test_body_truncated_after_masking(db_session: AsyncSession):
    # The secret starts 7 bytes before the limit: cutting first would keep its first 7
    # characters, which no rule recognises as a secret any more.
    lead = "x" * (MAX_BODY_BYTES - 7)
    assert len(lead) == 8185
    text_body = lead + SECRET + " tail" * 50
    json_body = json.dumps({"note": lead[:-9] + SECRET + " tail" * 50}, separators=(",", ":"))
    assert json_body.index(SECRET) == 8185

    entry = await _record(
        db_session,
        request=Message(body=text_body),
        response=Message(body=json_body.encode()),
        known_secrets=[SECRET],
    )

    assert entry.truncated is True
    assert entry.request_body == lead + "***" + " tai"
    assert entry.response_body == json_body[:8185] + "***" + " tai"
    for body in (entry.request_body, entry.response_body):
        assert body is not None
        assert len(body.encode()) == MAX_BODY_BYTES
        assert SECRET[:4] not in body


async def test_binary_body_replaced(db_session: AsyncSession):
    image = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 40
    with_nul = b"text \x00 with a NUL byte " + SECRET.encode()

    entry = await _record(
        db_session,
        request=Message(body=image),
        response=Message(body=with_nul),
        known_secrets=[SECRET],
    )

    assert entry.request_body == f"<binary {len(image)} bytes>"
    assert entry.response_body == f"<binary {len(with_nul)} bytes>"
    assert entry.truncated is False


async def test_text_bytes_are_stored_as_text_and_a_missing_side_as_null(db_session: AsyncSession):
    entry = await _record(
        db_session,
        direction="inbound",
        method="PUBLISH",
        target="device/0001/report",
        status=None,
        request=Message(body=bytearray("gr\u00fc\u00dfe".encode())),
        response=None,
    )

    assert entry.direction == "inbound"
    assert entry.status is None
    assert entry.request_body == "gr\u00fc\u00dfe"
    assert entry.request_headers == {}
    assert entry.response_headers == {}
    assert entry.response_body is None
    assert entry.error is None


async def test_no_request_at_all(db_session: AsyncSession):
    entry = await _record(db_session, request=None, response=Message(body=memoryview(b"ok")))

    assert entry.request_body is None and entry.request_headers == {}
    assert entry.response_body == "ok"


async def test_a_body_is_never_cut_inside_a_character(db_session: AsyncSession):
    body = "a" + "\u00e9" * 5000  # 1 + 10000 bytes: the limit falls inside a character

    entry = await _record(db_session, request=Message(body=body))

    assert entry.request_body == "a" + "\u00e9" * 4095
    assert entry.truncated is True


def test_truncate_utf8():
    assert truncate_utf8("abc", 3) == ("abc", False)
    assert truncate_utf8("abcd", 3) == ("abc", True)
    assert truncate_utf8("a\U0001f600", 4) == ("a", True)
    assert truncate_utf8("", 0) == ("", False)


async def test_characters_postgres_cannot_store_are_taken_out_before_masking(
    db_session: AsyncSession,
):
    half = len(SECRET) // 2
    broken = SECRET[:half] + "\x00" + SECRET[half:]  # the secret once the NUL is gone

    entry = await _record(
        db_session,
        method="GE\x00T",
        target=f"/a\x00b/{broken}?x=\ud800",
        request=Message(headers={"X-\x00N": f"v\x00 {broken}"}, body=f"body \ud83d {broken}"),
        error=f"failed\x00: {broken}",
        known_secrets=[SECRET],
    )

    assert entry.method == "GET"
    assert entry.target == "/ab/***?x=\ufffd"
    assert entry.request_headers == {"X-N": "v ***"}
    assert entry.request_body == "body \ufffd ***"
    assert entry.error == "failed: ***"


async def test_a_text_body_given_as_bytes_that_ends_inside_a_character_is_binary(
    db_session: AsyncSession,
):
    body = ("\u00e9" * 10).encode()[:-1]  # ends with half a character

    entry = await _record(db_session, response=Message(body=body))

    assert entry.response_body == f"<binary {len(body)} bytes>"


@pytest.mark.parametrize("as_bytes", [False, True], ids=["text", "bytes"])
async def test_an_oversized_body_is_stored_as_a_placeholder(
    db_session: AsyncSession, as_bytes: bool
):
    # No part of it is kept: a raw cut could leave half a secret behind.
    text = "password=" + "A" * MAX_MASK_INPUT + "&x=" + SECRET
    body: bytes | str = text.encode() if as_bytes else text

    entry = await _record(db_session, request=Message(body=body), known_secrets=[SECRET])

    assert entry.request_body == f"<omitted: {len(text.encode())} bytes>"
    assert entry.truncated is True


async def test_an_oversized_binary_body_is_omitted_as_well(db_session: AsyncSession):
    body = b"\xff" * (MAX_MASK_INPUT + 1)
    entry = await _record(db_session, request=Message(body=body))
    assert entry.request_body == f"<omitted: {len(body)} bytes>"


async def test_an_oversized_error_and_target_are_stored_as_placeholders(
    db_session: AsyncSession,
):
    huge = "x" * MAX_MASK_INPUT + "\u00e9"
    entry = await _record(db_session, error=huge, target="/" + huge)

    assert entry.error == f"<omitted: {len(huge.encode())} bytes>"
    assert entry.target == f"<omitted: {len(huge.encode()) + 1} bytes>"
    assert entry.truncated is True


async def test_a_part_at_the_bound_is_masked_whole(db_session: AsyncSession):
    body = "A" * (MAX_MASK_INPUT - len(SECRET) - 1) + " " + SECRET
    assert len(body.encode()) == MAX_MASK_INPUT

    entry = await _record(db_session, response=Message(body=body), known_secrets=[SECRET])

    assert entry.response_body == "A" * MAX_BODY_BYTES
    assert entry.truncated is True


async def test_an_encoded_secret_near_the_stored_size_is_masked(db_session: AsyncSession):
    from urllib.parse import quote, unquote

    spelled = "".join(f"%{ord(c):02X}" for c in SECRET)  # every character escaped
    body = "n" * (MAX_BODY_BYTES - 20) + " " + spelled + " " + "z" * 500
    assert quote(SECRET, safe="") != spelled

    entry = await _record(db_session, response=Message(body=body), known_secrets=[SECRET])

    stored = unquote(entry.response_body or "")
    assert not any(SECRET[i : i + 6] in stored for i in range(len(SECRET) - 5))
    assert entry.response_body is not None and " *** z" in entry.response_body


async def test_a_cut_never_ends_inside_a_mask(db_session: AsyncSession):
    body = "a" * (MAX_BODY_BYTES - 2) + SECRET  # the mask would start two bytes before the end

    entry = await _record(db_session, response=Message(body=body), known_secrets=[SECRET])

    assert entry.response_body == "a" * (MAX_BODY_BYTES - 2)
    assert entry.truncated is True


async def test_header_limits(db_session: AsyncSession):
    many = [(f"X-H{i}", "v") for i in range(150)]
    long_value = {"X-Long": "v" * 5000, "N" * 500: "x"}

    entry = await _record(
        db_session, request=Message(headers=many), response=Message(headers=long_value)
    )

    assert list(entry.request_headers) == [f"X-H{i}" for i in range(100)]
    assert entry.response_headers == {"X-Long": "v" * 2048, "N" * 200: "x"}
    assert entry.truncated is True


async def test_header_names_and_values_given_as_bytes(db_session: AsyncSession):
    entry = await _record(
        db_session,
        request=Message(headers=[(b"X-Caf\xe9", b"cr\xe8me"), (b"Authorization", b"Basic abc")]),  # type: ignore[list-item]
        response=Message(headers={"Content-Length": 5}),  # type: ignore[dict-item]
    )

    assert entry.request_headers == {"X-Caf\u00e9": "cr\u00e8me", "Authorization": "***"}
    assert entry.response_headers == {"Content-Length": "5"}


async def test_long_target_method_and_error_are_cut(db_session: AsyncSession):
    entry = await _record(db_session, method="M" * 100, target="/" + "p" * 5000, error="e" * 5000)

    assert entry.method == "M" * 32
    assert entry.target == "/" + "p" * 2047
    assert entry.error == "e" * 2000
    assert entry.truncated is True


async def test_record_does_not_commit(
    db_session: AsyncSession, sessions: async_sessionmaker[AsyncSession]
):
    await recorder.record(
        db_session,
        instance_id=INSTANCE,
        method="GET",
        target="/",
        status=200,
        duration_ms=1,
        request=None,
        response=None,
    )
    assert await _count(sessions) == 0

    await db_session.rollback()
    assert await _count(sessions) == 0

    await _record(db_session)
    await db_session.commit()
    assert await _count(sessions) == 1


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("instance_id", str(INSTANCE)),
        ("instance_id", None),
        ("direction", "sideways"),
        ("direction", None),
        ("method", ""),
        ("method", 5),
        ("target", None),
        ("status", "200"),
        ("status", True),
        ("status", 2**31),
        ("duration_ms", -1),
        ("duration_ms", 1.5),
        ("duration_ms", False),
        ("duration_ms", 2**31),
        ("error", 5),
        ("request", {"body": "x"}),
        ("response", "body"),
        ("request", Message(body=5)),  # type: ignore[arg-type]
        ("response", Message(body={"a": 1})),  # type: ignore[arg-type]
    ],
)
async def test_record_refuses_arguments_of_the_wrong_kind(
    argument: str,
    value: object,
    db_session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
):
    with pytest.raises(ValueError) as exc:
        await _record(db_session, **{argument: value})

    assert argument.split("_")[0] in str(exc.value)
    if isinstance(value, str) and value:
        assert value not in str(exc.value)
    # Nothing was sent: the transaction is still usable.
    await _record(db_session)


async def test_record_logs_nothing(db_session: AsyncSession, caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.DEBUG):
        await _record(
            db_session,
            target=f"/x?token={SECRET}",
            request=Message(headers={"Authorization": f"Bearer {SECRET}"}, body=SECRET),
            error=SECRET,
            known_secrets=[SECRET],
        )

    assert not [r for r in caplog.records if r.name.startswith("app.")]
    assert not any(SECRET in r.getMessage() for r in caplog.records)


def test_the_stored_sizes():
    assert communication.MAX_BODY_BYTES == 8192
    assert communication.MAX_MASK_INPUT == 65_536
    assert communication.MAX_HEADERS_INPUT == 65_536
    assert communication.MAX_MASK_INPUT > 4 * communication.MAX_BODY_BYTES


# --- fix round 1: header input, header bytes, record_isolated ------------------------------


async def test_a_header_past_the_budget_never_keeps_part_of_a_known_secret(
    db_session: AsyncSession,
):
    first = "a" * (MAX_HEADERS_INPUT - 4 - 10)  # "X-A" + value; 11 bytes left after it
    entry = await _record(
        db_session,
        request=Message(headers=[("X-A", first), ("X-B", SECRET + " tail")]),
        known_secrets=[SECRET],
    )

    assert "fake-acc" not in json.dumps(entry.request_headers)
    assert entry.request_headers["X-B"] == f"<omitted: {len(SECRET) + 5} bytes>"
    assert entry.truncated is True


async def test_header_bytes_are_read_as_utf_8_when_they_are(db_session: AsyncSession):
    secret = "kn\u00f6wn-v\u00e4lue-3"
    entry = await _record(
        db_session,
        request=Message(
            headers=[(b"X-Debug", f"echo {secret}".encode()), (b"X-Name", "caf\u00e9".encode())]  # type: ignore[list-item]
        ),
        known_secrets=[secret],
    )

    assert entry.request_headers == {"X-Debug": "echo ***", "X-Name": "caf\u00e9"}


def _arguments(**overrides: Any) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "instance_id": INSTANCE,
        "method": "GET",
        "target": f"https://printer.example.com/status?token={SECRET}",
        "status": 200,
        "duration_ms": 12,
        "request": Message(headers={"Authorization": f"Bearer {SECRET}"}),
        "response": Message(body=f"echo {SECRET}"),
        "known_secrets": [SECRET],
    }
    arguments.update(overrides)
    return arguments


async def test_record_isolated_commits_an_entry_of_its_own(
    sessions: async_sessionmaker[AsyncSession], db_session: AsyncSession
):
    # The caller is in the middle of other work: that transaction is not touched.
    await db_session.execute(select(1))

    assert await recorder.record_isolated(sessions, **_arguments()) is True

    assert await _count(sessions) == 1
    async with sessions() as session:
        entry = (await session.scalars(select(CommunicationEntry))).one()
    assert SECRET not in json.dumps(
        [entry.target, entry.request_headers, entry.response_body], ensure_ascii=False
    )
    assert db_session.in_transaction()


async def test_record_isolated_swallows_a_database_error_and_logs_its_class_only(
    caplog: pytest.LogCaptureFixture,
):
    engine = make_engine(DEAD_DATABASE_URL)
    try:
        with caplog.at_level(logging.DEBUG, logger="app.events.communication"):
            ok = await recorder.record_isolated(make_session_factory(engine), **_arguments())
    finally:
        await engine.dispose()

    assert ok is False
    messages = [r.getMessage() for r in caplog.records if r.name == "app.events.communication"]
    assert len(messages) == 1
    assert messages[0].startswith("communication log entry not recorded (")
    assert not any(part in messages[0] for part in (SECRET, "127.0.0.1", "://", "printer"))


async def test_record_isolated_swallows_a_missing_partition(
    sessions: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
):
    from sqlalchemy import text

    async with sessions() as session:
        names = (
            await session.scalars(
                text(
                    "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                    "WHERE i.inhparent = 'communication_log'::regclass"
                )
            )
        ).all()
        for name in names:
            await session.execute(text(f'DROP TABLE "{name}"'))
        await session.commit()

    with caplog.at_level(logging.WARNING, logger="app.events.communication"):
        assert await recorder.record_isolated(sessions, **_arguments()) is False

    assert [r.getMessage() for r in caplog.records] == [
        "communication log entry not recorded (IntegrityError, SQLSTATE 23514)"
    ]


async def test_record_isolated_still_refuses_wrong_arguments(
    sessions: async_sessionmaker[AsyncSession],
):
    with pytest.raises(ValueError, match="duration_ms"):
        await recorder.record_isolated(sessions, **_arguments(duration_ms=-1))
    assert await _count(sessions) == 0


# --- fix round 2 ---------------------------------------------------------------------------


async def test_header_names_that_collide_after_shortening_are_numbered(db_session: AsyncSession):
    long = "X-" + "a" * 300
    entry = await _record(
        db_session,
        request=Message(headers=[(long + "1", "one"), (long + "2", "two"), (long + "3", "three")]),
    )

    names = list(entry.request_headers)
    assert len(names) == 3
    assert all(len(name) <= 200 for name in names)
    # jsonb orders the keys itself.
    assert sorted(name[-2:] for name in names if "#" in name) == ["#2", "#3"]
    assert sorted(entry.request_headers.values()) == ["one", "three", "two"]


async def test_record_isolated_masks_off_the_event_loop(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
):
    import threading

    threads: list[threading.Thread] = []
    real = communication.Masker

    def watched(**kwargs: Any) -> communication.Masker:
        threads.append(threading.current_thread())
        return real(**kwargs)

    monkeypatch.setattr(communication, "Masker", watched)

    assert await recorder.record_isolated(sessions, **_arguments()) is True

    assert len(threads) == 1
    assert threads[0] is not threading.main_thread()


async def test_headers_beyond_the_budget_become_placeholders(db_session: AsyncSession):
    import time

    huge = [(f"X-H{i}", f"v{i}-" + "y" * 60_000) for i in range(100)]
    started = time.monotonic()

    entry = await _record(db_session, request=Message(headers=huge), known_secrets=[SECRET])

    assert time.monotonic() - started < 10
    headers = entry.request_headers
    assert len(headers) == 100
    # The first fits the 65,536 bytes of the side and is masked, then cut to 2048.
    assert headers["X-H0"].startswith("v0-") and len(headers["X-H0"]) == 2048
    # Every later value no longer fits what is left: a placeholder, not a cut.
    assert headers["X-H1"] == "<omitted: 60003 bytes>"
    assert headers["X-H99"] == "<omitted: 60004 bytes>"
    assert entry.truncated is True
