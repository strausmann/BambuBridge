from __future__ import annotations

import asyncio
import re
import string

import bcrypt
import pytest

from app.auth import tokens
from app.auth.tokens import (
    PREFIX_LENGTH,
    TOKEN_PREFIX,
    generate_token,
    hash_token,
    looks_like_token,
    token_prefix,
    verify_token,
)

_FORMAT = re.compile(r"^bb_pat_[0-9A-Za-z]{40}$")


def test_generate_token_format_and_prefix():
    plaintext, prefix = generate_token()
    assert _FORMAT.fullmatch(plaintext)
    assert prefix == plaintext[:16]
    assert PREFIX_LENGTH == 16
    assert prefix.startswith(TOKEN_PREFIX)


def test_generated_tokens_are_unique_and_use_base62():
    seen = {generate_token()[0] for _ in range(200)}
    assert len(seen) == 200
    alphabet = set(string.digits + string.ascii_letters)
    for value in seen:
        assert set(value.removeprefix(TOKEN_PREFIX)) <= alphabet


@pytest.mark.production_bcrypt_cost
def test_hash_uses_bcrypt_cost_12_and_verifies():
    """Pins the shipped cost: the suite lowers it everywhere else (``cheap_bcrypt``)."""
    assert tokens.BCRYPT_ROUNDS == 12
    plaintext, _ = generate_token()
    hashed = hash_token(plaintext)
    assert hashed.startswith("$2b$12$")
    assert plaintext not in hashed
    assert bcrypt.checkpw(plaintext.encode(), hashed.encode())


@pytest.mark.production_bcrypt_cost
def test_dummy_hash_uses_bcrypt_cost_12():
    """The dummy check for an unknown prefix must cost as much as a real one."""
    assert tokens._dummy_hash().startswith("$2b$12$")


def test_suite_lowers_bcrypt_cost_outside_marked_tests():
    assert hash_token(generate_token()[0]).startswith("$2b$04$")


async def test_verify_token_accepts_match_and_rejects_other():
    plaintext, _ = generate_token()
    other, _ = generate_token()
    hashed = hash_token(plaintext)
    assert await verify_token(plaintext, hashed) is True
    assert await verify_token(other, hashed) is False


async def test_verify_cache_never_holds_plaintext():
    tokens.clear_verify_cache()
    plaintext, _ = generate_token()
    hashed = hash_token(plaintext)
    assert await verify_token(plaintext, hashed) is True
    assert await verify_token(plaintext, hashed) is True  # second call served from the cache
    for key in tokens._verify_cache:
        assert plaintext not in repr(key)


async def test_verify_cache_hit_skips_bcrypt(monkeypatch: pytest.MonkeyPatch):
    tokens.clear_verify_cache()
    plaintext, _ = generate_token()
    hashed = hash_token(plaintext)
    assert await verify_token(plaintext, hashed) is True

    def boom(*_args: object) -> bool:
        raise AssertionError("bcrypt must not run on a cache hit")

    monkeypatch.setattr(tokens.bcrypt, "checkpw", boom)
    assert await verify_token(plaintext, hashed) is True


def test_verify_handles_garbage_hash():
    plaintext, _ = generate_token()

    assert asyncio.run(verify_token(plaintext, "not-a-bcrypt-hash")) is False


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        ("bb_pat_" + "a" * 40, True),
        ("bb_pat_" + "a" * 39, False),
        ("bb_pat_" + "a" * 41, False),
        ("bb_pat_" + "a" * 39 + "-", False),
        ("xx_pat_" + "a" * 40, False),
        ("", False),
    ],
)
def test_looks_like_token(value: str, ok: bool):
    assert looks_like_token(value) is ok


def test_token_prefix_is_first_16_characters():
    plaintext, prefix = generate_token()
    assert token_prefix(plaintext) == prefix


async def test_bcrypt_work_is_limited_by_a_semaphore(monkeypatch: pytest.MonkeyPatch):
    import threading
    import time

    tokens.clear_verify_cache()
    lock = threading.Lock()
    state = {"current": 0, "peak": 0}

    def slow_check(_password: bytes, _hashed: bytes) -> bool:
        with lock:
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
        time.sleep(0.05)
        with lock:
            state["current"] -= 1
        return False

    monkeypatch.setattr(tokens.bcrypt, "checkpw", slow_check)
    hashed = "$2b$12$" + "a" * 53
    work = [verify_token(generate_token()[0], hashed) for _ in range(6)]
    work += [tokens.dummy_verify(generate_token()[0]) for _ in range(6)]
    tokens._dummy_hash()  # computed outside the measured section
    await asyncio.gather(*work)
    assert state["peak"] == tokens.BCRYPT_CONCURRENCY == 4


def test_is_cached_reports_only_successful_verifications():
    tokens.clear_verify_cache()
    plaintext, _ = generate_token()
    hashed = hash_token(plaintext)
    assert tokens.is_cached(plaintext, hashed) is False
    assert asyncio.run(verify_token(plaintext, hashed)) is True
    assert tokens.is_cached(plaintext, hashed) is True
    assert tokens.is_cached(generate_token()[0], hashed) is False
