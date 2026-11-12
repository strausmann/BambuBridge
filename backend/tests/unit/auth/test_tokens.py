from __future__ import annotations

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


def test_hash_uses_bcrypt_cost_12_and_verifies():
    plaintext, _ = generate_token()
    hashed = hash_token(plaintext)
    assert hashed.startswith("$2b$12$")
    assert plaintext not in hashed
    assert bcrypt.checkpw(plaintext.encode(), hashed.encode())


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
    import asyncio

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
