"""API token format, hashing and verification.

Format: ``bb_pat_`` followed by 40 base62 characters (about 238 bits of entropy). The
first 16 characters (``bb_pat_`` plus nine body characters) are stored as the lookup
prefix; the full token is stored only as a bcrypt hash (cost 12). The plaintext exists
in memory only while a token is created or checked and is shown to the user once.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import re
import secrets
import string
import weakref
from collections.abc import Callable

import bcrypt
from cachetools import TTLCache

TOKEN_PREFIX = "bb_pat_"  # noqa: S105 - the public token type marker, not a secret
BODY_LENGTH = 40
PREFIX_LENGTH = 16
BCRYPT_ROUNDS = 12
# At most this many bcrypt computations run at once (per event loop); the rest wait.
BCRYPT_CONCURRENCY = 4
_ALPHABET = string.digits + string.ascii_letters
_FORMAT = re.compile(rf"^{TOKEN_PREFIX}[0-9A-Za-z]{{{BODY_LENGTH}}}$")

# Successful verifications only, so wrong guesses cannot fill the cache. The key holds a
# SHA-256 digest of the token, never the token itself. A hit only skips bcrypt; whether
# the token is enabled, unexpired and owned by an enabled user is checked on every request.
_verify_cache: TTLCache[tuple[bytes, str], bool] = TTLCache(maxsize=1024, ttl=300)


# One semaphore per event loop: asyncio primitives bind to the loop they are first used in.
_bcrypt_slots: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    weakref.WeakKeyDictionary()
)


async def _run_bcrypt[T](func: Callable[..., T], *args: str) -> T:
    """Run bcrypt work in a worker thread, at most ``BCRYPT_CONCURRENCY`` at a time."""
    loop = asyncio.get_running_loop()
    slots = _bcrypt_slots.get(loop)
    if slots is None:
        slots = _bcrypt_slots[loop] = asyncio.Semaphore(BCRYPT_CONCURRENCY)
    async with slots:
        return await asyncio.to_thread(func, *args)


def generate_token() -> tuple[str, str]:
    """Return a new ``(plaintext, prefix)`` pair."""
    body = "".join(secrets.choice(_ALPHABET) for _ in range(BODY_LENGTH))
    plaintext = TOKEN_PREFIX + body
    return plaintext, token_prefix(plaintext)


def token_prefix(plaintext: str) -> str:
    """Return the lookup prefix (first 16 characters) of a token."""
    return plaintext[:PREFIX_LENGTH]


def looks_like_token(value: str) -> bool:
    """Whether ``value`` has the token format (cheap check before any database access)."""
    return _FORMAT.fullmatch(value) is not None


def hash_token(plaintext: str) -> str:
    """bcrypt hash of a token (cost 12)."""
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


async def hash_token_async(plaintext: str) -> str:
    """``hash_token`` in a worker thread, so bcrypt does not block the event loop."""
    return await _run_bcrypt(hash_token, plaintext)


def _checkpw(plaintext: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except ValueError:  # not a bcrypt hash
        return False


def _cache_key(plaintext: str, hashed: str) -> tuple[bytes, str]:
    return hashlib.sha256(plaintext.encode()).digest(), hashed


def is_cached(plaintext: str, hashed: str) -> bool:
    """Whether this token was verified against this hash recently (no bcrypt work)."""
    return bool(_verify_cache.get(_cache_key(plaintext, hashed)))


async def verify_token(plaintext: str, hashed: str) -> bool:
    """Whether ``plaintext`` matches ``hashed``; bcrypt runs in a worker thread."""
    if is_cached(plaintext, hashed):
        return True
    ok = await _run_bcrypt(_checkpw, plaintext, hashed)
    if ok:
        _verify_cache[_cache_key(plaintext, hashed)] = True
    return ok


@functools.cache
def _dummy_hash() -> str:
    # A hash of a random value nobody knows; computed once, on first use.
    return hash_token(generate_token()[0])


def _dummy_check(plaintext: str) -> bool:
    _checkpw(plaintext, _dummy_hash())
    return False


async def dummy_verify(plaintext: str) -> bool:
    """Spend the same bcrypt work as ``verify_token`` and return ``False``.

    Used for an unknown prefix, so the response time does not reveal whether a prefix
    exists. Never cached.
    """
    return await _run_bcrypt(_dummy_check, plaintext)


def clear_verify_cache() -> None:
    """Forget all cached verifications (tests)."""
    _verify_cache.clear()
