"""Emitting events.

:meth:`EventService.emit` writes the event and one delivery per registered subscriber into
the caller's transaction (transactional outbox): both are there after the caller's commit,
or neither. It never commits itself.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.validation import check_subscriber, is_storable
from app.repositories import events as events_repo
from app.settings_store.store import SettingsStore

EVENT_TYPE_PATTERN = re.compile(
    r"^(account|inventory|integration|display)\.[a-z0-9_]+\.[a-z0-9_]+$", re.ASCII
)

# Limits of what ``emit`` takes. The payload is measured as compact JSON text in UTF-8.
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_PAYLOAD_DEPTH = 32
MAX_DEDUP_KEY_LENGTH = 200
MAX_EVENT_TYPE_LENGTH = 200
# ``events.schema_version`` is an ``integer`` column.
MAX_SCHEMA_VERSION = 2**31 - 1

# How long ``emit`` waits for the lock of its source before it gives up.
SOURCE_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_NOT_AVAILABLE = "55P03"

# Every emitted event gets one delivery per name in this list. ``sse`` (the live stream of
# the web UI) is the base subscriber; later parts add their own with ``register_subscriber``.
_SUBSCRIBERS: list[str] = ["sse"]


class InvalidEventTypeError(ValueError):
    """The event type name does not match ``<domain>.<subject>.<action>``."""


class SourceBusyError(RuntimeError):
    """Another transaction kept the lock of the source for longer than ``emit`` waits.

    The database has aborted the statement, and with it the caller's transaction: roll it
    back before the session is used again.
    """


def register_subscriber(name: str) -> None:
    """Add a subscriber: from now on every emitted event gets a delivery for it.

    Call it at import or startup time, before events are emitted. Registering a name twice
    changes nothing.
    """
    check_subscriber(name)
    if name not in _SUBSCRIBERS:
        _SUBSCRIBERS.append(name)


def subscribers() -> tuple[str, ...]:
    """The registered subscriber names, in registration order."""
    return tuple(_SUBSCRIBERS)


def _check_payload(payload: object) -> None:
    """Refuse what PostgreSQL ``jsonb`` would refuse, and anything beyond the limits.

    The messages name the rule only: a payload can hold secrets, and an error text ends up
    in logs.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    pending: list[tuple[object, int]] = [(payload, 1)]
    while pending:
        value, depth = pending.pop()
        if isinstance(value, str):
            if not is_storable(value):
                raise ValueError("payload strings must not contain NUL or surrogate characters")
        elif value is None or isinstance(value, bool | int):
            pass
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("payload numbers must be finite (no NaN, no Infinity)")
        elif isinstance(value, dict | list | tuple):
            if depth > MAX_PAYLOAD_DEPTH:
                raise ValueError(f"payload must not be nested deeper than {MAX_PAYLOAD_DEPTH}")
            if isinstance(value, dict):
                for key in value:
                    if not isinstance(key, str):
                        raise ValueError("payload keys must be strings")
                    if not is_storable(key):
                        raise ValueError(
                            "payload strings must not contain NUL or surrogate characters"
                        )
                children: Any = value.values()
            else:
                children = value
            pending.extend((child, depth + 1) for child in children)
        else:
            raise ValueError(
                "payload values must be JSON: dict, list, str, int, float, bool or None"
            )
    try:
        size = len(
            json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        )
    except ValueError, TypeError, RecursionError:
        # For example an integer too long to be written out. No cause attached: the
        # original message may quote the value.
        raise ValueError("payload cannot be written as JSON") from None
    if size > MAX_PAYLOAD_BYTES:
        raise ValueError(f"payload must not be larger than {MAX_PAYLOAD_BYTES} bytes of JSON")


def _check_dedup_key(dedup_key: object) -> None:
    if (
        not isinstance(dedup_key, str)
        or not 1 <= len(dedup_key) <= MAX_DEDUP_KEY_LENGTH
        or not is_storable(dedup_key)
    ):
        raise ValueError(
            f"dedup_key must be None or a string of 1 to {MAX_DEDUP_KEY_LENGTH} characters "
            "without NUL or surrogate characters"
        )


class EventService:
    def __init__(self, settings: SettingsStore) -> None:
        self._settings = settings

    async def emit(
        self,
        session: AsyncSession,
        *,
        type: str,  # noqa: A002  # part of the public interface
        source_instance_id: UUID | None,
        payload: dict[str, Any],
        schema_version: int,
        dedup_key: str | None = None,
        correlation_id: UUID | None = None,
    ) -> UUID | None:
        """Write an event and its deliveries; return the event id, or ``None`` for a duplicate.

        A duplicate is an event of the same source and the same type with the same
        ``dedup_key`` written within the last ``events.dedup_window_seconds`` (a runtime
        setting, read on every call; 0 switches deduplication off). Events without a
        ``dedup_key`` are never duplicates. The window is counted from the time of the earlier
        event to the moment this call got the lock of the source. So when the transaction of
        the earlier event stays open for longer than the window, a duplicate that waited for
        it (or arrives afterwards) is written: commit soon after ``emit``.

        Order per source: an advisory lock on the source is held from here until the
        caller's transaction ends, and the event time is read from the database clock under
        that lock. So the events of one source carry increasing times in commit order, and a
        consumer never sees a later event of a source before an earlier one. The price: a
        second ``emit`` for the same source waits until the first caller commits or rolls
        back. So emit late in the transaction and commit soon after. The wait is bounded:
        after ``SOURCE_LOCK_TIMEOUT_SECONDS`` :class:`SourceBusyError` is raised, and the
        caller's transaction has to be rolled back (the database aborted it). All events
        without a source (``source_instance_id=None``) share one lock and wait for each other
        in the same way. A transaction that emits for several sources should do so in a fixed
        order (two transactions taking the same two sources in opposite order deadlock, and
        PostgreSQL aborts one of them).

        Everything is checked before the first statement is sent, so a refused call leaves
        the caller's transaction as it was. Raises :class:`InvalidEventTypeError` for a type
        name outside the naming scheme or longer than ``MAX_EVENT_TYPE_LENGTH`` (200)
        characters, and ``ValueError`` for

        - a ``source_instance_id`` or ``correlation_id`` that is neither a ``UUID`` nor
          ``None`` (the text form of a UUID is not taken: it would be a different source for
          the lock);
        - a ``payload`` that is not a dict of JSON values with string keys, that holds a NUL
          or surrogate character in a string, a NaN or an infinite number, that is nested
          deeper than ``MAX_PAYLOAD_DEPTH`` or larger than ``MAX_PAYLOAD_BYTES`` (64 KiB) as
          JSON text;
        - a ``dedup_key`` that is empty, longer than ``MAX_DEDUP_KEY_LENGTH`` (200)
          characters or holds a NUL or surrogate character;
        - a ``schema_version`` that is not an integer from 1 to 2147483647.

        The messages never quote a value. A missing partition for the current month is a
        database error (there is no default partition); see :mod:`app.events.partitions`.
        """
        if (
            not isinstance(type, str)
            or len(type) > MAX_EVENT_TYPE_LENGTH
            or not EVENT_TYPE_PATTERN.fullmatch(type)
        ):
            raise InvalidEventTypeError(
                "event type must match (account|inventory|integration|display)"
                f".<subject>.<action> in lower case, {MAX_EVENT_TYPE_LENGTH} characters at most"
            )
        if source_instance_id is not None and not isinstance(source_instance_id, UUID):
            raise ValueError("source_instance_id must be a UUID or None")
        if correlation_id is not None and not isinstance(correlation_id, UUID):
            raise ValueError("correlation_id must be a UUID or None")
        _check_payload(payload)
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or not 1 <= schema_version <= MAX_SCHEMA_VERSION
        ):
            raise ValueError(f"schema_version must be an integer from 1 to {MAX_SCHEMA_VERSION}")
        if dedup_key is not None:
            _check_dedup_key(dedup_key)
        try:
            await events_repo.lock_source(
                session, source_instance_id, timeout_seconds=SOURCE_LOCK_TIMEOUT_SECONDS
            )
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
                raise
            raise SourceBusyError(
                "the event lock of the source is held by another transaction; "
                "roll back and try again"
            ) from exc
        if dedup_key is not None:
            window = int(self._settings.get("events.dedup_window_seconds"))
            if window > 0 and await events_repo.duplicate_exists(
                session,
                source_instance_id=source_instance_id,
                type=type,
                dedup_key=dedup_key,
                window_seconds=window,
            ):
                return None
        event_id, occurred_at = await events_repo.insert_event(
            session,
            type=type,
            source_instance_id=source_instance_id,
            payload=payload,
            schema_version=schema_version,
            dedup_key=dedup_key,
            correlation_id=correlation_id,
        )
        await events_repo.insert_deliveries(
            session, event_id=event_id, event_occurred_at=occurred_at, subscribers=subscribers()
        )
        return event_id
