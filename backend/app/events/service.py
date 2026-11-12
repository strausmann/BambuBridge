"""Emitting events.

:meth:`EventService.emit` writes the event and one delivery per registered subscriber into
the caller's transaction (transactional outbox): both are there after the caller's commit,
or neither. It never commits itself.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import events as events_repo
from app.settings_store.store import SettingsStore

EVENT_TYPE_PATTERN = re.compile(
    r"^(account|inventory|integration|display)\.[a-z0-9_]+\.[a-z0-9_]+$", re.ASCII
)
_SUBSCRIBER_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)

# Every emitted event gets one delivery per name in this list. ``sse`` (the live stream of
# the web UI) is the base subscriber; later parts add their own with ``register_subscriber``.
_SUBSCRIBERS: list[str] = ["sse"]


class InvalidEventTypeError(ValueError):
    """The event type name does not match ``<domain>.<subject>.<action>``."""


def register_subscriber(name: str) -> None:
    """Add a subscriber: from now on every emitted event gets a delivery for it.

    Call it at import or startup time, before events are emitted. Registering a name twice
    changes nothing.
    """
    if not isinstance(name, str) or not _SUBSCRIBER_NAME.fullmatch(name):
        raise ValueError("subscriber name must match [a-z][a-z0-9_]{0,63}")
    if name not in _SUBSCRIBERS:
        _SUBSCRIBERS.append(name)


def subscribers() -> tuple[str, ...]:
    """The registered subscriber names, in registration order."""
    return tuple(_SUBSCRIBERS)


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

        A duplicate is an event of the same source with the same ``dedup_key`` written within
        the last ``events.dedup_window_seconds`` (a runtime setting, read on every call; 0
        switches deduplication off). Events without a ``dedup_key`` are never duplicates.

        Order per source: an advisory lock on the source is held from here until the
        caller's transaction ends, and the event time is read from the database clock under
        that lock. So the events of one source carry increasing times in commit order, and a
        consumer never sees a later event of a source before an earlier one. The price: a
        second ``emit`` for the same source waits until the first caller commits or rolls
        back, so keep the transaction short. A transaction that emits for several sources
        should do so in a fixed order (two transactions taking the same two sources in
        opposite order deadlock, and PostgreSQL aborts one of them).

        Raises :class:`InvalidEventTypeError` for a type name outside the naming scheme. A
        missing partition for the current month is a database error (there is no default
        partition); see :mod:`app.events.partitions`.
        """
        if not isinstance(type, str) or not EVENT_TYPE_PATTERN.fullmatch(type):
            raise InvalidEventTypeError(
                "event type must match (account|inventory|integration|display)"
                ".<subject>.<action> in lower case"
            )
        await events_repo.lock_source(session, source_instance_id)
        if dedup_key is not None:
            window = int(self._settings.get("events.dedup_window_seconds"))
            if window > 0 and await events_repo.duplicate_exists(
                session,
                source_instance_id=source_instance_id,
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
