"""Recording what a provider instance sent and received (the communication log).

:meth:`CommunicationRecorder.record` is the only way into ``communication_log``. For every
part of an exchange it works in this order:

1. **Make it storable.** PostgreSQL text cannot hold a NUL character or a surrogate code
   point. They are not refused but taken out (NUL removed, surrogates replaced by U+FFFD):
   what a peer sends must never make the log, and with it the caller's transaction, fail.
   This comes first, so that a removed character cannot join the two halves of a secret
   after the search for it. A body given as bytes that is not UTF-8 text, or holds a NUL
   byte, is binary and stored as ``<binary N bytes>``.
2. **Mask** (:mod:`app.security.masking`) the whole part. A part larger than
   ``MAX_MASK_INPUT`` bytes of UTF-8 is not masked and not kept in part: it is stored as
   ``<omitted: N bytes>`` (and ``truncated`` is set), as binary bodies are. The headers of
   one side share ``MAX_HEADERS_INPUT`` bytes; a name or value that does not fit what is
   left becomes the placeholder too.
3. **Cut** the masked text to the stored size: ``MAX_BODY_BYTES`` of UTF-8 per body (never
   inside a character), and the limits below for the other parts; never inside a ``***``.
   A cut sets ``truncated``.

Only masked text is ever cut. Every secret the masker finds is ``***`` by then, and one it
does not find is not affected by where the cut falls: no cut can leave half a secret
behind, because there is no cut before masking.

Arguments the caller controls (ids, numbers, direction, types) are checked instead, with a
``ValueError`` that names the argument and never a value, before a statement is sent.

:meth:`CommunicationRecorder.record` neither logs nor commits: the entry joins the caller's
transaction. :meth:`CommunicationRecorder.record_isolated` writes it in a short transaction
of its own and swallows a database error (one log line, the error class and SQLSTATE only)
- that is the one provider code uses, so that a failed log entry never fails the work it
describes.
"""

from __future__ import annotations

import asyncio
import functools
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
from app.security.masking import MASK, Masker

# Stored sizes. Bodies are measured in bytes of UTF-8, everything else in characters.
MAX_BODY_BYTES = 8192
MAX_TARGET_LENGTH = 2048
MAX_METHOD_LENGTH = 32
MAX_ERROR_LENGTH = 2000
MAX_HEADERS = 100
MAX_HEADER_NAME_LENGTH = 200
MAX_HEADER_VALUE_LENGTH = 2048
# The largest part that is masked (larger ones are omitted), and the bytes all headers of
# one side share, both in bytes of UTF-8.
MAX_MASK_INPUT = 65_536
MAX_HEADERS_INPUT = 65_536

# How many maskers (one per set of known secrets and secret paths) are kept for reuse.
MASKER_CACHE_SIZE = 32

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


def omitted(size: int) -> str:
    """The placeholder for a part too large to be masked (``size``: its UTF-8 bytes)."""
    return f"<omitted: {size} bytes>"


def _utf8_size(text: str) -> int:
    return len(text.encode("utf-8", "surrogatepass"))


def _cut_masked(text: str, cut: int) -> str:
    """``text[:cut]``, but never ending inside a mask: a ``*`` or ``**`` left of ``***``
    would read like part of the value."""
    for back in (1, 2):
        if text[cut - back : cut - back + len(MASK)] == MASK and cut - back + len(MASK) > cut:
            return text[: cut - back]
    return text[:cut]


class _Exchange:
    """Cleans the parts of one exchange with one :class:`Masker`; remembers any cut.

    A part is masked whole or not at all: one larger than ``MAX_MASK_INPUT`` bytes of
    UTF-8 is stored as ``<omitted: N bytes>``. Only the masked text is ever cut, so no cut
    can leave half a secret behind.
    """

    def __init__(self, masker: Masker) -> None:
        self._masker = masker
        self.truncated = False

    def _bounded(self, text: str, limit: int = MAX_MASK_INPUT) -> str | None:
        """``text`` made storable, or ``None`` (and ``truncated``) when it is too large."""
        if len(text) > limit or _utf8_size(text) > limit:
            self.truncated = True
            return None
        return make_storable(text)

    def _shorten(self, text: str, max_length: int) -> str:
        if len(text) > max_length:
            self.truncated = True
            return _cut_masked(text, max_length)
        return text

    def line(self, text: str, max_length: int) -> str:
        """Free text (method, error): storable, masked whole, then cut."""
        bounded = self._bounded(text)
        if bounded is None:
            return omitted(_utf8_size(text))
        return self._shorten(self._masker.text(bounded), max_length)

    def target(self, text: str) -> str:
        bounded = self._bounded(text)
        if bounded is None:
            return omitted(_utf8_size(text))
        return self._shorten(self._masker.target(bounded), MAX_TARGET_LENGTH)

    def headers(self, headers: Headers) -> dict[str, Any]:
        """Masked headers; a name that occurs more than once gets a list of its values.

        All headers of one side share ``MAX_HEADERS_INPUT`` bytes; a name or value that
        does not fit what is left is stored as the placeholder, never cut. When the name is
        the placeholder, so is its value: masking by name is no longer possible.
        """
        pairs = headers.items() if isinstance(headers, Mapping) else headers
        collected: dict[str, list[str]] = {}
        budget = MAX_HEADERS_INPUT
        for count, (raw_name, raw_value) in enumerate(pairs):
            if count >= MAX_HEADERS:
                self.truncated = True
                break
            name_text, value_text = _text(raw_name), _text(raw_value)
            name = self._bounded(name_text, min(MAX_MASK_INPUT, budget))
            if name is None:
                # Fail closed: a placeholder no longer says the name is a credential, so the
                # value cannot be masked by its name and goes as well, whatever its size.
                name = omitted(_utf8_size(name_text))
                value = omitted(_utf8_size(value_text))
            else:
                budget -= _utf8_size(name)
                bounded_value = self._bounded(value_text, min(MAX_MASK_INPUT, budget))
                if bounded_value is None:
                    value = omitted(_utf8_size(value_text))
                else:
                    budget -= _utf8_size(bounded_value)
                    value = bounded_value
            collected.setdefault(name, []).append(value)
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
            short_name = self._shorten(name, MAX_HEADER_NAME_LENGTH)
            if short_name in out:
                # Two names that are the same once shortened (or masked): numbered.
                number = 2
                while (numbered := _numbered(short_name, number)) in out:
                    number += 1
                short_name = numbered
            out[short_name] = short
        return out

    def body(self, body: bytes | str | None) -> str | None:
        if body is None:
            return None
        if isinstance(body, str):
            text = body
        else:
            if len(body) > MAX_MASK_INPUT:
                self.truncated = True
                return omitted(len(body))
            decoded = _decode(bytes(body))
            if decoded is None or "\x00" in decoded:
                return f"<binary {len(body)} bytes>"
            text = decoded
        bounded = self._bounded(text)
        if bounded is None:
            return omitted(_utf8_size(text))
        masked = self._masker.body(bounded)
        stored, cut = truncate_utf8(masked, MAX_BODY_BYTES)
        if cut:
            self.truncated = True
            stored = _cut_masked(masked, len(stored))
        return stored


def _numbered(name: str, number: int) -> str:
    """``name#number``, still within ``MAX_HEADER_NAME_LENGTH`` and not cut inside a mask."""
    suffix = f"#{number}"
    return _cut_masked(name, MAX_HEADER_NAME_LENGTH - len(suffix)) + suffix


def _text(value: object) -> str:
    """Header names and values as text; bytes as UTF-8 if they are, otherwise as the wire
    has them (ISO 8859-1)."""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1")
    return value if isinstance(value, str) else str(value)


def _decode(data: bytes) -> str | None:
    """UTF-8 text, or ``None`` for anything else."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


@functools.lru_cache(maxsize=MASKER_CACHE_SIZE)
def _cached_masker(secret_paths: frozenset[Any], known_secrets: frozenset[Any]) -> Masker:
    return Masker(secret_paths=tuple(secret_paths), known_secrets=tuple(known_secrets))


def masker_for(secret_paths: Collection[str], known_secrets: Collection[str]) -> Masker:
    """The :class:`Masker` for this set of secret paths and known secrets, built once.

    Building one compiles a pattern per secret and can take seconds for long secrets; a
    provider passes the same set with every record. The cache lives in process memory only
    (``MASKER_CACHE_SIZE`` sets, least recently used out). Order does not matter. A set that
    cannot be a key (an entry that is not hashable) is built without the cache, so that its
    error is raised as usual.
    """
    try:
        key = (frozenset(_entries(secret_paths)), frozenset(_entries(known_secrets)))
    except TypeError:
        return Masker(secret_paths=secret_paths, known_secrets=known_secrets)
    return _cached_masker(*key)


masker_for.cache_info = _cached_masker.cache_info  # type: ignore[attr-defined]
masker_for.cache_clear = _cached_masker.cache_clear  # type: ignore[attr-defined]


def _entries(values: Collection[Any]) -> Collection[Any]:
    """A single string (or bytes) is one entry, as for :class:`Masker`."""
    return (values,) if isinstance(values, str | bytes) else values


def _entry_values(
    *,
    instance_id: uuid.UUID,
    method: str,
    target: str,
    status: int | None,
    duration_ms: int,
    request: Message | None,
    response: Message | None,
    error: str | None,
    direction: str,
    secret_paths: Collection[str],
    known_secrets: Collection[str],
) -> dict[str, Any]:
    """The checked, masked and cut column values of one entry (CPU work, no I/O)."""
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

    exchange = _Exchange(masker_for(secret_paths, known_secrets))
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
    return values


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

        Masking runs here, on the event loop: CPU work of up to seconds for large parts
        and many or long secrets (the masker itself is cached per secret set, see
        :func:`masker_for`). **Provider code uses** :meth:`record_isolated`, which masks in
        a worker thread.
        """
        values = _entry_values(
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
        # Masking is CPU work (up to seconds for large parts and many secrets): it runs in
        # a worker thread so the event loop stays free.
        values = await asyncio.to_thread(
            _entry_values,
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
        try:
            async with sessions() as session, session.begin():
                await session.execute(insert(CommunicationEntry).values(**values))
        except (SQLAlchemyError, OSError) as exc:
            _log.warning("communication log entry not recorded (%s)", describe_error(exc))
            return False
        return True
