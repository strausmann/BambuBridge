from __future__ import annotations

import base64
import hashlib

import pytest

from app.config import Settings
from app.security.secret_box import (
    SealedSecret,
    SecretBox,
    UndecryptableSecretError,
    key_id_for,
    secret_box_from_settings,
)

KEY_A = b"A" * 32
KEY_B = b"B" * 32
ID_A = key_id_for(KEY_A)
ID_B = key_id_for(KEY_B)


def _box(*keys: bytes, active: bytes | None = None) -> SecretBox:
    return SecretBox({key_id_for(k): k for k in keys}, key_id_for(active or keys[0]))


def test_key_id_is_first_16_hex_characters_of_sha256():
    assert key_id_for(KEY_A) == hashlib.sha256(KEY_A).hexdigest()[:16]
    assert len(ID_A) == 16
    assert ID_A != ID_B


def test_seal_records_key_id_and_roundtrips():
    box = _box(KEY_A)
    sealed = box.seal("hunter2-but-longer", aad="sso.trust_token")
    assert sealed.key_id == ID_A
    assert "hunter2" not in sealed.token
    assert box.open(sealed, aad="sso.trust_token") == "hunter2-but-longer"


def test_seal_uses_a_fresh_12_byte_nonce_every_time():
    box = _box(KEY_A)
    first = box.seal("same", aad="k")
    second = box.seal("same", aad="k")
    assert first.token != second.token
    version, nonce, _ct = first.token.split(".")
    assert version == "v1"
    assert len(base64.urlsafe_b64decode(nonce + "=" * (-len(nonce) % 4))) == 12


def test_unicode_and_empty_plaintext_roundtrip():
    box = _box(KEY_A)
    for text in ("", "größe ✓ 日本語"):
        assert box.open(box.seal(text, aad="k"), aad="k") == text


def test_open_with_wrong_aad_raises():
    box = _box(KEY_A)
    sealed = box.seal("value", aad="sso.trust_token")
    with pytest.raises(UndecryptableSecretError):
        box.open(sealed, aad="some.other.key")


def test_open_with_unknown_key_id_raises_undecryptable():
    sealed = _box(KEY_A).seal("value", aad="k")
    with pytest.raises(UndecryptableSecretError):
        _box(KEY_B).open(sealed, aad="k")


@pytest.mark.parametrize(
    "token",
    ["", "v1", "v1.only", "v2.AAAA.AAAA", "v1.AAAA.AAAA.AAAA", "v1.!!!.???", "v1.AAAA.AAAA"],
)
def test_malformed_or_damaged_token_raises(token: str):
    with pytest.raises(UndecryptableSecretError):
        _box(KEY_A).open(SealedSecret(key_id=ID_A, token=token), aad="k")


def test_tampered_ciphertext_raises():
    box = _box(KEY_A)
    sealed = box.seal("value", aad="k")
    version, nonce, ct = sealed.token.split(".")
    flipped = ("B" if ct[0] != "B" else "C") + ct[1:]
    with pytest.raises(UndecryptableSecretError):
        box.open(SealedSecret(sealed.key_id, f"{version}.{nonce}.{flipped}"), aad="k")


def test_box_with_several_keys_opens_old_and_seals_with_active():
    old = _box(KEY_A).seal("legacy", aad="k")
    box = SecretBox({ID_A: KEY_A, ID_B: KEY_B}, ID_B)
    assert box.open(old, aad="k") == "legacy"
    assert box.seal("fresh", aad="k").key_id == ID_B


def test_error_message_does_not_reveal_plaintext_or_key():
    sealed = _box(KEY_A).seal("plain-value-xyz", aad="k")
    with pytest.raises(UndecryptableSecretError) as e:
        _box(KEY_B).open(sealed, aad="k")
    assert "plain-value-xyz" not in str(e.value)
    assert KEY_A.decode() not in str(e.value)


def test_constructor_rejects_wrong_key_length_and_unknown_active_id():
    with pytest.raises(ValueError, match="32 bytes"):
        SecretBox({"x": b"short"}, "x")
    with pytest.raises(ValueError, match="active"):
        SecretBox({ID_A: KEY_A}, ID_B)


def test_constructor_rejects_key_id_that_does_not_match_the_key():
    with pytest.raises(ValueError, match="key id"):
        SecretBox({ID_B: KEY_A}, ID_B)


def test_from_settings_uses_the_configured_key(settings: Settings):
    box = secret_box_from_settings(settings)
    raw = base64.urlsafe_b64decode(settings.secret_key.get_secret_value())
    assert box.active_key_id == key_id_for(raw)
    assert box.open(box.seal("v", aad="k"), aad="k") == "v"
