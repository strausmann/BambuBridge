"""Strict decoding of the 32-byte secret key given as base64url text."""

from __future__ import annotations

import base64
import re

_KEY_BYTES = 32
# 32 bytes are exactly 43 base64url characters; one optional "=" makes 44. Nothing else is
# the key's canonical form. ``base64.urlsafe_b64decode`` alone silently drops foreign
# characters (including ``+`` and ``/``) and ignores surplus padding and non-zero padding
# bits, so the shape is checked first and the decoded bytes are re-encoded and compared.
_KEY_SHAPE = re.compile(r"[A-Za-z0-9_-]{43}=?")

KEY_HELP = "generate with: python3 -c 'import secrets;print(secrets.token_urlsafe(32))'"


def decode_secret_key(text: str, *, name: str) -> bytes:
    """Decode ``text`` (base64url, 32 bytes). Raise ``ValueError`` naming ``name`` only.

    The message never contains the offending text, so a mistyped key does not end up in
    logs or tracebacks.
    """
    candidate = text.strip()
    message = f"{name} must be 32 bytes as base64url text, 43 characters ({KEY_HELP})"
    if not _KEY_SHAPE.fullmatch(candidate):
        raise ValueError(message)
    # The shape check guarantees 43 URL-safe characters, which always decode.
    raw = base64.urlsafe_b64decode(candidate.rstrip("=") + "=")
    if len(raw) != _KEY_BYTES or base64.urlsafe_b64encode(raw).rstrip(b"=") != candidate.rstrip(
        "="
    ).encode("ascii"):
        raise ValueError(message)
    return raw
