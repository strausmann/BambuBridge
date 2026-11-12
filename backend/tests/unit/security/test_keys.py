from __future__ import annotations

import base64

import pytest

from app.security.keys import SUBKEY_LABELS, decode_secret_key, derive_subkey

RAW = b"test-secret-key-0123456789abcdef"
GOOD = base64.urlsafe_b64encode(RAW).decode()  # 44 characters, one padding character
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
# Same 43 characters, but the last one carries non-zero padding bits (256 bits = 42*6 + 4).
_LAST = GOOD.rstrip("=")[-1]
NON_CANONICAL = GOOD.rstrip("=")[:-1] + _ALPHABET[_ALPHABET.index(_LAST) | 1]


def test_decodes_padded_and_unpadded_base64url():
    assert decode_secret_key(GOOD, name="K") == RAW
    assert decode_secret_key(GOOD.rstrip("="), name="K") == RAW
    assert decode_secret_key(f"  {GOOD}\n", name="K") == RAW


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(GOOD[:10] + "!!" + GOOD[10:], id="injected-junk"),
        pytest.param(GOOD[:10] + " " + GOOD[10:], id="inner-space"),
        pytest.param(GOOD[:10] + "\n" + GOOD[10:], id="inner-newline"),
        pytest.param(GOOD[:10] + "\x00" + GOOD[10:], id="inner-nul"),
        pytest.param("", id="empty"),
        pytest.param("=" * 4, id="only-padding"),
        pytest.param(GOOD.rstrip("=") + "===", id="too-much-padding"),
        pytest.param(GOOD + "=", id="valid-key-with-double-padding"),
        pytest.param(GOOD.rstrip("=") + "==", id="unpadded-key-with-double-padding"),
        pytest.param(NON_CANONICAL, id="non-zero-padding-bits"),
        pytest.param(NON_CANONICAL.rstrip("=") + "=", id="non-zero-padding-bits-padded"),
        pytest.param("a" * 5, id="impossible-length"),
        pytest.param("c2hvcnQ", id="too-short"),
        pytest.param(base64.urlsafe_b64encode(RAW * 2).decode(), id="too-long"),
    ],
)
def test_rejects_anything_that_is_not_strict_base64url_of_32_bytes(bad: str):
    with pytest.raises(ValueError, match="K must"):
        decode_secret_key(bad, name="K")


def test_rejects_standard_alphabet_characters():
    # Bytes whose standard base64 contains "+" and "/"; urlsafe_b64decode alone would accept it.
    standard = base64.b64encode(bytes([0xFB, 0xFF] * 16)).decode()
    assert "+" in standard and "/" in standard
    with pytest.raises(ValueError, match="base64url"):
        decode_secret_key(standard, name="K")
    # The same bytes in the URL-safe alphabet are fine.
    assert decode_secret_key(base64.urlsafe_b64encode(bytes([0xFB, 0xFF] * 16)).decode(), name="K")


def test_non_canonical_fixture_really_differs_in_the_last_character_only():
    assert GOOD.rstrip("=") != NON_CANONICAL and len(NON_CANONICAL) == 43


@pytest.mark.parametrize("bad", [GOOD + "=", NON_CANONICAL])
def test_error_for_padding_problems_names_only_the_variable(bad: str):
    with pytest.raises(ValueError) as e:
        decode_secret_key(bad, name="MY_VARIABLE")
    assert str(e.value).startswith("MY_VARIABLE must")
    assert bad not in str(e.value) and bad.rstrip("=") not in str(e.value)


def test_error_message_never_contains_the_input():
    secretish = "SUPER-SECRET-LOOKING-VALUE!!"
    with pytest.raises(ValueError) as e:
        decode_secret_key(secretish, name="K")
    assert secretish not in str(e.value)


# --- sub-keys (audit H7) -------------------------------------------------------------------


def test_sub_keys_differ_from_the_master_and_from_each_other():
    master = bytes(range(32))
    keys = {label: derive_subkey(master, label) for label in SUBKEY_LABELS}
    assert len(keys) == 3
    assert all(len(k) == 32 for k in keys.values())
    assert master not in keys.values()
    assert len(set(keys.values())) == len(keys)
    # Deterministic: the same master always gives the same sub-keys.
    assert keys == {label: derive_subkey(master, label) for label in SUBKEY_LABELS}
    # Another master gives other sub-keys.
    other = bytes(range(1, 33))
    assert all(derive_subkey(other, label) != keys[label] for label in SUBKEY_LABELS)


def test_sub_keys_are_hkdf_sha256_with_distinct_labels():
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    master = bytes(range(32))
    for label in SUBKEY_LABELS:
        expected = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=f"bambubridge/{label}/v1".encode()
        ).derive(master)
        assert derive_subkey(master, label) == expected


def test_unknown_sub_key_label_is_refused():
    with pytest.raises(ValueError, match="label"):
        derive_subkey(bytes(32), "other")  # type: ignore[arg-type]
