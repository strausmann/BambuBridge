"""Recording what a provider instance sent and received (the communication log).

:meth:`CommunicationRecorder.record` is the only way into ``communication_log``. For every
part of an exchange it works in this order:

1. **Make it storable.** PostgreSQL text cannot hold a NUL character or a surrogate code
   point. They are not refused but taken out (NUL removed, surrogates replaced by U+FFFD):
   what a peer sends must never make the log, and with it the caller's transaction, fail.
   This comes first, so that a removed character cannot join the two halves of a secret
   after the search for it. A body given as bytes that is not UTF-8 text, or holds a NUL
   byte, is binary and stored as ``<binary N bytes>``.
2. **Mask** (:mod:`app.security.masking`).
3. **Cut** to the stored size: ``MAX_BODY_BYTES`` of UTF-8 per body, and the limits below
   for the other parts. A cut sets ``truncated``.

Masking before cutting matters: a secret that straddles the cut would otherwise be stored
as a fragment that no rule recognises any more.

To bound the work, at most ``MAX_MASK_INPUT`` characters of a text are masked, and at most
``MAX_HEADERS_INPUT`` characters of the headers of one side (names and values together;
headers after that are left out). That first cut is made by
:meth:`app.security.masking.Masker.safe_prefix`, which never cuts through a known secret.

Arguments the caller controls (ids, numbers, direction, types) are checked instead, with a
``ValueError`` that names the argument and never a value, before a statement is sent.

:meth:`CommunicationRecorder.record` neither logs nor commits: the entry joins the caller's
transaction. :meth:`CommunicationRecorder.record_isolated` writes it in a short transaction
of its own and swallows a database error (one log line, the error class and SQLSTATE only)
- that is the one provider code uses, so that a failed log entry never fails the work it
describes.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import func, insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events.daily import describe_error
from app.events.validation import make_storable
from app.models.communication_entry import CommunicationEntry
from app.security.masking import Masker

# Stored sizes. Bodies are measured in bytes of UTF-8, everything else in characters.
MAX_BODY_BYTES = 8192
MAX_TARGET_LENGTH = 2048
MAX_METHOD_LENGTH = 32
MAX_ERROR_LENGTH = 2000
MAX_HEADERS = 100
MAX_HEADER_NAME_LENGTH = 200
MAX_HEADER_VALUE_LENGTH = 2048
# How much of one text is looked at (masked) at all, and of all headers of one side.
MAX_MASK_INPUT = 65_536
MAX_HEADERS_INPUT = 65_536

_log = logging.getLogger(__name__)

DIRECTIONS = ("outbound", "inbound")
# ``status`` and ``duration_ms`` are ``integer`` columns.
_MAX_INT = 2**31 - 1

Headers = Mapping[str, str] | Iterable[tuple[str, str]]


@dataclass(frozen=True)
class Message:
    """One side of an exchange: its headers and its body (``None``: there was none)."""

    headers: Headers = field(default_factory=dict)
    body: bytes | str | None = None


def truncate_utf8(text: str, max_bytes: int) -> tuple[str, bool]:
    """``text`` cut to at most ``max_bytes`` of UTF-8, never inside a character."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", "ignore"), True


def _is_int(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


class _Exchange:
    """Cleans the parts of one exchange with one :class:`Masker`; remembers any cut."""

    def __init__(self, masker: Masker) -> None:
        self._masker = masker
        self.truncated = False

    def _visible(self, text: str, *, complete: bool = True, limit: int = MAX_MASK_INPUT) -> str:
        """The storable beginning of ``text`` that is masked at all (at most ``limit``)."""
        # A little more than the limit, so that a secret straddling it is seen whole.
        window = limit + self._masker.longest_secret
        complete = complete and len(text) <= window
        prefix, cut = self._masker.safe_prefix(
            make_storable(text[:window]), complete=complete, limit=limit
        )
        self.truncated |= cut
        return prefix

    def _shorten(self, text: str, max_length: int) -> str:
        if len(text) > max_length:
            self.truncated = True
            return text[:max_length]
        return text

    def line(self, text: str, max_length: int) -> str:
        """Free text (method, error): storable, masked, cut."""
        return self._shorten(self._masker.text(self._visible(text)), max_length)

    def target(self, text: str) -> str:
        return self._shorten(self._masker.target(self._visible(text)), MAX_TARGET_LENGTH)

    def headers(self, headers: Headers) -> dict[str, Any]:
        """Masked headers; a name that occurs more than once gets a list of its values."""
        pairs = headers.items() if isinstance(headers, Mapping) else headers
        collected: dict[str, list[str]] = {}
        budget = MAX_HEADERS_INPUT
        for count, (name, value) in enumerate(pairs):
            if count >= MAX_HEADERS or budget <= 0:
                self.truncated = True
                break
            visible_name = self._visible(_text(name), limit=min(MAX_MASK_INPUT, budget))
            budget -= len(visible_name)
            visible_value = self._visible(_text(value), limit=max(0, min(MAX_MASK_INPUT, budget)))
            budget -= len(visible_value)
            collected.setdefault(visible_name, []).append(visible_value)
        masked = self._masker.value(
            {name: values[0] if len(values) == 1 else values for name, values in collected.items()}
        )
        out: dict[str, Any] = {}
        for name, value in masked.items():
            short = (
                [self._shorten(item, MAX_HEADER_VALUE_LENGTH) for item in value]
                if isinstance(value, list)
                else self._shorten(value, MAX_HEADER_VALUE_LENGTH)
            )
            out[self._shorten(name, MAX_HEADER_NAME_LENGTH)] = short
        return out

    def body(self, body: bytes | str | None) -> str | None:
        if body is None:
            return None
        complete = True
        if isinstance(body, str):
            text = body
        else:
            # Enough bytes for the window of ``_visible`` whatever the characters are.
            window = 4 * (MAX_MASK_INPUT + self._masker.longest_secret)
            head = bytes(body[:window])
            complete = len(body) <= window
            decoded = _decode(head, complete=complete)
            if decoded is None or "\x00" in decoded:
                return f"<binary {len(body)} bytes>"
            text = decoded
        masked = self._masker.body(self._visible(text, complete=complete))
        stored, cut = truncate_utf8(masked, MAX_BODY_BYTES)
        self.truncated |= cut
        return stored


def _text(value: object) -> str:
    """Header names and values as text; bytes as UTF-8 if they are, otherwise as the wire
    has them (ISO 8859-1)."""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1")
    return value if isinstance(value, str) else str(value)


def _decode(data: bytes, *, complete: bool) -> str | None:
    """UTF-8 text, or ``None`` for anything else.

    ``data`` that is only the beginning of a body may end inside a character; those last
    bytes are left out.
    """
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if complete or exc.start < len(data) - 3:
            return None
        # Everything before the first error is valid UTF-8.
        return data[: exc.start].decode("utf-8")


class CommunicationRecorder:
    """Writes masked, size-bounded entries of the communication log."""

    async def record(
        self,
        session: AsyncSession,
        *,
        instance_id: uuid.UUID,
        method: str,
        target: str,
        status: int | None,
        duration_ms: int,
        request: Message | None,
        response: Message | None,
        error: str | None = None,
        direction: Literal["outbound", "inbound"] = "outbound",
        secret_paths: Collection[str] = (),
        known_secrets: Collection[str] = (),
    ) -> None:
        """Add one entry to the caller's transaction; never commits.

        ``method`` and ``target`` say what was done (``GET`` and a URL, ``PUBLISH`` and a
        topic); ``status`` is the answer's status code or ``None`` when there was no answer;
        ``error`` is a short reason for a failure. ``request`` and ``response`` carry headers
        and body; pass ``None`` for a side that does not exist.

        ``secret_paths`` (see :func:`app.security.masking.secret_paths_from_schema`) and
        ``known_secrets`` (the plaintext secrets of the instance) are what masking knows
        beyond names. Every stored part is masked, the error text included: pass all the
        secrets the instance holds.

        Raises ``ValueError`` for an argument of the wrong type or range before anything is
        sent to the database. A database error (for example no partition for the current
        month) is raised as it comes and aborts the caller's transaction: use this only
        when the entry has to be atomic with other work, and :meth:`record_isolated`
        otherwise.
        """
        if not isinstance(instance_id, uuid.UUID):
            raise ValueError("instance_id must be a UUID")
        if direction not in DIRECTIONS:
            raise ValueError("direction must be 'outbound' or 'inbound'")
        if not isinstance(method, str) or not method:
            raise ValueError("method must be a non-empty string")
        if not isinstance(target, str):
            raise ValueError("target must be a string")
        if status is not None and not _is_int(status, -_MAX_INT, _MAX_INT):
            raise ValueError("status must be None or an integer that fits the column")
        if not _is_int(duration_ms, 0, _MAX_INT):
            raise ValueError("duration_ms must be a non-negative integer that fits the column")
        if error is not None and not isinstance(error, str):
            raise ValueError("error must be None or a string")
        for name, message in (("request", request), ("response", response)):
            if message is not None and not isinstance(message, Message):
                raise ValueError(f"{name} must be None or a Message")
            if message is not None and not isinstance(
                message.body, bytes | bytearray | memoryview | str | None
            ):
                raise ValueError(f"the body of {name} must be bytes, a string or None")

        exchange = _Exchange(Masker(secret_paths=secret_paths, known_secrets=known_secrets))
        values: dict[str, Any] = {
            "occurred_at": func.clock_timestamp(),
            "instance_id": instance_id,
            "direction": direction,
            "method": exchange.line(method, MAX_METHOD_LENGTH),
            "target": exchange.target(target),
            "status": status,
            "duration_ms": duration_ms,
            "request_headers": exchange.headers(request.headers) if request else {},
            "request_body": exchange.body(request.body) if request else None,
            "response_headers": exchange.headers(response.headers) if response else {},
            "response_body": exchange.body(response.body) if response else None,
            "error": None if error is None else exchange.line(error, MAX_ERROR_LENGTH),
        }
        # Last: every part above may have set it.
        values["truncated"] = exchange.truncated
        await session.execute(insert(CommunicationEntry).values(**values))

    async def record_isolated(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        instance_id: uuid.UUID,
        method: str,
        target: str,
        status: int | None,
        duration_ms: int,
        request: Message | None,
        response: Message | None,
        error: str | None = None,
        direction: Literal["outbound", "inbound"] = "outbound",
        secret_paths: Collection[str] = (),
        known_secrets: Collection[str] = (),
    ) -> bool:
        """:meth:`record` in a short transaction of its own, committed at once.

        **Provider code records with this** (Task 11): the log entry is a side note of the
        work, and a database error must not fail that work. Such an error (no partition,
        database away) is swallowed and logged once, by class and SQLSTATE, never with a
        value; the result is then ``False``. An argument of the wrong kind still raises
        ``ValueError``: that is a bug in the caller, not a state of the database.
        Use :meth:`record` instead when the entry has to be atomic with other work.
        """
        try:
            async with sessions() as session, session.begin():
                await self.record(
                    session,
                    instance_id=instance_id,
                    method=method,
                    target=target,
                    status=status,
                    duration_ms=duration_ms,
                    request=request,
                    response=response,
                    error=error,
                    direction=direction,
                    secret_paths=secret_paths,
                    known_secrets=known_secrets,
                )
        except (SQLAlchemyError, OSError) as exc:
            _log.warning("communication log entry not recorded (%s)", describe_error(exc))
            return False
        return True
