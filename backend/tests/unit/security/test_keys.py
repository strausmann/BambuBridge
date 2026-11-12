from __future__ import annotations

import base64

import pytest

from app.security.keys import decode_secret_key

RAW = b"test-secret-key-0123456789abcdef"
GOOD = base64.urlsafe_b64encode(RAW).decode()  # 44 characters, one padding character


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


def test_error_message_never_contains_the_input():
    secretish = "SUPER-SECRET-LOOKING-VALUE!!"
    with pytest.raises(ValueError) as e:
        decode_secret_key(secretish, name="K")
    assert secretish not in str(e.value)
