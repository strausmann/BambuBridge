"""Strict decoding of the 32-byte secret key given as base64url text."""

from __future__ import annotations

import base64
import re

_KEY_BYTES = 32
# Strict base64url: the URL-safe alphabet only, at most two trailing padding characters.
# ``base64.urlsafe_b64decode`` alone silently drops foreign characters (including ``+``
# and ``/``), so the alphabet is checked first.
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+={0,2}")

KEY_HELP = "generate with: python3 -c 'import secrets;print(secrets.token_urlsafe(32))'"


def decode_secret_key(text: str, *, name: str) -> bytes:
    """Decode ``text`` (base64url, 32 bytes). Raise ``ValueError`` naming ``name`` only.

    The message never contains the offending text, so a mistyped key does not end up in
    logs or tracebacks.
    """
    candidate = text.strip()
    if not _BASE64URL.fullmatch(candidate):
        raise ValueError(f"{name} must be base64url text (A-Z a-z 0-9 - _)")
    try:
        raw = base64.urlsafe_b64decode(candidate + "=" * (-len(candidate) % 4))
    except ValueError as exc:  # binascii.Error is a ValueError (bad length)
        raise ValueError(f"{name} must be base64url text (A-Z a-z 0-9 - _)") from exc
    if len(raw) != _KEY_BYTES:
        raise ValueError(f"{name} must decode to exactly 32 bytes ({KEY_HELP})")
    return raw
