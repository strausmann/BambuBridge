"""AES-256-GCM box for secrets stored in the database.

Token format: ``v1.<b64url nonce>.<b64url ciphertext>`` (12-byte random nonce). The
associated data is chosen by the caller (the setting key, the provider instance id), so a
ciphertext copied to another record does not open. The id of the key that sealed a token
is stored next to it (``SealedSecret.key_id``): the box can hold several keys, which makes
rotation and "this was sealed with another key" detectable instead of a generic failure.

The box holds master keys (``BAMBUBRIDGE_SECRET_KEY``) and their ids; the id identifies the
master key. AES-GCM runs with the master's ``secret-box`` sub-key (``derive_subkey``), never
with the master itself.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.security.keys import decode_secret_key, derive_subkey

if TYPE_CHECKING:
    from app.config import Settings

_VERSION = "v1"
_NONCE_BYTES = 12
_KEY_BYTES = 32
_KEY_ID_HEX_CHARS = 16


class UndecryptableSecretError(Exception):
    """The stored secret cannot be opened (unknown key, wrong AAD, damaged token)."""


@dataclass(frozen=True)
class SealedSecret:
    """A sealed value: the id of the key that sealed it and the opaque token."""

    key_id: str
    token: str


def key_id_for(key: bytes) -> str:
    """Stable, non-reversible id of a key: the first 16 hex characters of its SHA-256."""
    return hashlib.sha256(key).hexdigest()[:_KEY_ID_HEX_CHARS]


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SecretBox:
    """Seals with the active key; opens with any key it holds."""

    def __init__(self, keys: Mapping[str, bytes], active_key_id: str) -> None:
        for key_id, key in keys.items():
            if len(key) != _KEY_BYTES:
                raise ValueError("every secret key must be exactly 32 bytes")
            if key_id_for(key) != key_id:
                raise ValueError("key id does not match its key")
        if active_key_id not in keys:
            raise ValueError("active key id is not among the keys")
        self._aead = {
            key_id: AESGCM(derive_subkey(key, "secret-box")) for key_id, key in keys.items()
        }
        self.active_key_id = active_key_id

    def seal(self, plaintext: str, *, aad: str) -> SealedSecret:
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aead[self.active_key_id].encrypt(
            nonce, plaintext.encode("utf-8"), aad.encode("utf-8")
        )
        return SealedSecret(self.active_key_id, f"{_VERSION}.{_b64e(nonce)}.{_b64e(ciphertext)}")

    def open(self, sealed: SealedSecret, *, aad: str) -> str:
        aead = self._aead.get(sealed.key_id)
        if aead is None:
            raise UndecryptableSecretError(
                "secret was sealed with a key this instance does not have"
            )
        parts = sealed.token.split(".")
        if len(parts) != 3 or parts[0] != _VERSION:
            raise UndecryptableSecretError("unsupported or malformed secret token")
        try:
            nonce = _b64d(parts[1])
            ciphertext = _b64d(parts[2])
            return aead.decrypt(nonce, ciphertext, aad.encode("utf-8")).decode("utf-8")
        except (binascii.Error, ValueError, InvalidTag) as exc:
            raise UndecryptableSecretError("secret cannot be decrypted") from exc


def secret_box_from_key(key: bytes) -> SecretBox:
    """Box holding exactly one key."""
    key_id = key_id_for(key)
    return SecretBox({key_id: key}, key_id)


def secret_box_from_settings(settings: Settings) -> SecretBox:
    key = decode_secret_key(settings.secret_key.get_secret_value(), name="BAMBUBRIDGE_SECRET_KEY")
    return secret_box_from_key(key)
