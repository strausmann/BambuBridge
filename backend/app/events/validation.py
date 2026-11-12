"""Checks for text that goes into the event tables.

PostgreSQL refuses a NUL character in ``text`` and ``jsonb`` and has no encoding for a
surrogate code point. Such a value is not turned away by the driver but by the server, as an
error that aborts the caller's transaction. So it is refused here, before a statement is sent.
"""

from __future__ import annotations

import re

MAX_WORKER_ID_LENGTH = 200
# ``event_deliveries.id`` is a ``bigint`` from a sequence.
MAX_DELIVERY_ID = 2**63 - 1

SUBSCRIBER_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}", re.ASCII)

_NUL = re.compile("\x00")
_SURROGATE = re.compile("[\ud800-\udfff]")
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


def is_storable(value: str) -> bool:
    """Whether PostgreSQL takes the string: no NUL and no surrogate code point."""
    return _UNSTORABLE.search(value) is None


def make_storable(value: str) -> str:
    """Remove NUL characters and put U+FFFD in place of every surrogate code point."""
    return _SURROGATE.sub("\ufffd", _NUL.sub("", value))


def check_subscriber(name: object) -> str:
    if not isinstance(name, str) or not SUBSCRIBER_NAME.fullmatch(name):
        raise ValueError("subscriber name must match [a-z][a-z0-9_]{0,63}")
    return name


def check_worker(worker: object) -> str:
    """A worker id names the holder of a lease: any short, storable, non-empty string."""
    if (
        not isinstance(worker, str)
        or not 1 <= len(worker) <= MAX_WORKER_ID_LENGTH
        or not is_storable(worker)
    ):
        raise ValueError(
            f"worker id must be a string of 1 to {MAX_WORKER_ID_LENGTH} characters "
            "without NUL or surrogate characters"
        )
    return worker


def is_delivery_id(value: object) -> bool:
    """A positive integer that fits the ``bigint`` id column; ``bool`` is not an id."""
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_DELIVERY_ID
