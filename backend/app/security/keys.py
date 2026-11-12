"""The 32-byte secret key: strict base64url decoding and purpose-bound sub-keys.

``BAMBUBRIDGE_SECRET_KEY`` is a master key and is never used directly. Each use gets its
own sub-key from HKDF-SHA256 with a distinct label (``derive_subkey``): AES-GCM for stored
secrets, HMAC for CSRF tokens, HMAC for session binding material. A sub-key leaking
through one use therefore says nothing about the others or about the master.
"""

from __future__ import annotations

import base64
import re
from typing import Literal, get_args

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

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


SubkeyLabel = Literal["secret-box", "csrf", "session-binding"]
SUBKEY_LABELS: tuple[SubkeyLabel, ...] = get_args(SubkeyLabel)


def derive_subkey(master: bytes, label: SubkeyLabel) -> bytes:
    """32-byte sub-key of ``master`` for one purpose (HKDF-SHA256, info names the label)."""
    if label not in SUBKEY_LABELS:
        raise ValueError("unknown sub-key label")
    info = f"bambubridge/{label}/v1".encode("ascii")
    return HKDF(algorithm=hashes.SHA256(), length=_KEY_BYTES, salt=None, info=info).derive(master)
