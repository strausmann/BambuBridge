"""Seeded fuzzing of the masker: random mixes of quotes, separators, names and secrets.

Two things must never survive, whatever stands around them: a known secret value (in any
of the spellings the masker searches for) and the value of a secret-named pair or field
(a unique marker here).
"""

from __future__ import annotations

import base64
import json
import random
from urllib.parse import quote, quote_plus

import pytest

from app.security.masking import Masker

SECRETS = ["zq-known-value-0001", "Zq/known value+2&=?", "zqzqzqzqzq", "kn\u00f6wn-v\u00e4lue-3"]
SOUP = [
    '"',
    "'",
    "=",
    "&",
    ";",
    ",",
    "#",
    " ",
    "\\",
    ":",
    "{",
    "}",
    "[",
    "]",
    "<",
    ">",
    "?",
    "/",
    "@",
    "://",
    "%",
    "\n",
    "a",
    "b",
    "x=",
    "n=1",
    '"k":',
    "user",
    "Bearer ",
    "basic ",
]
PLAIN = ["a", "b", "note", "user", "x", "q"]
SENSITIVE = ["password", "TOKEN", "api_key", "client-secret", "Authorization", "pass%77ord"]
# Seeded per test; not a source of secrets.
rnd = random.Random(0)  # noqa: S311


def spell(secret: str) -> str:
    kind = rnd.randrange(6)
    if kind == 0:
        return quote(secret, safe="")
    if kind == 1:
        return base64.b64encode(secret.encode()).decode()
    if kind == 2:
        return json.dumps(secret)[1:-1]
    return secret


def soup(n: int) -> str:
    return "".join(rnd.choice(SOUP) for _ in range(rnd.randrange(n)))


def fragments(secret: str) -> set[str]:
    """Every part of ``secret`` at most two characters shorter: showing one of them shows
    the secret all but for two characters."""
    size = len(secret) - 2
    return {secret[i : i + size] for i in range(len(secret) - size + 1)}


def marker(i: int) -> str:
    return f"MRK{i:07d}K"


def pair(i: int) -> str:
    """A secret-named pair or JSON field whose value is the marker."""
    name, value = rnd.choice(SENSITIVE), marker(i)
    kind = rnd.randrange(5)
    if kind == 0:
        return f'"{name}"{rnd.choice([":", ": ", " : "])}"{value}"'
    if kind == 1:
        return f'"{name}":{rnd.choice(["{", "["])}"{rnd.choice(PLAIN)}":"{value}"'
    if kind == 2:
        return f"{name}=Bearer {value}"
    q = rnd.choice(["", '"', "'"])
    return f"{name}={q}{value}{q}"


def wrap(inner: str) -> str:
    """Put text inside the (quoted or bare) value of plain names, possibly nested."""
    for _ in range(rnd.randrange(4)):
        q = rnd.choice(['"', "'", ""])
        sep = rnd.choice([" ", ";", ",", "&", ""])
        inner = f"{rnd.choice(PLAIN)}={q}{soup(4)}{sep}{inner}{q}"
    return inner


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_known_secret_and_no_secret_value_survives(seed: int):
    global rnd
    rnd = random.Random(seed)  # noqa: S311
    masker = Masker(known_secrets=SECRETS, secret_paths=["conn.code"])
    for i in range(1500):
        parts = [soup(8)]
        for _ in range(rnd.randrange(1, 4)):
            choice = rnd.randrange(3)
            if choice == 0:
                parts.append(wrap(pair(i)))
            elif choice == 1:
                parts.append(wrap(spell(rnd.choice(SECRETS))))
            else:
                parts.append(spell(rnd.choice(SECRETS)) + spell(rnd.choice(SECRETS)))
            parts.append(soup(8))
        text = "".join(parts)
        outputs = {
            "text": masker.text(text),
            "body": masker.body(text),
            "body-json": masker.body(json.dumps({"a": [text, {"conn": {"code": marker(i)}}]})),
            "target": masker.target(text),
            "value": json.dumps(masker.value({"k": text, text: 1}), ensure_ascii=False),
        }
        for kind, out in outputs.items():
            # The input is synthetic, so it may be shown when the assertion fails.
            assert marker(i) not in out, (kind, text, out)
            for secret in SECRETS:
                for fragment in fragments(secret):
                    assert fragment not in out, (kind, text, out)


# Secrets that start with hex digits: a "%", "%2" or "%25" in front of them forms a percent
# escape with their first characters once the text is decoded as a whole.
HEX_SECRETS = ["34567890", "C0FFEE12ab", "abcdef12%4", "2Bad-c0de-77"]
HEX_PREFIXES = ["%", "%2", "%25", "%%", "%2%", "%25%2"]
# Pairs that only show decoded: they make a decoded round the one stored.
ENCODED_PAIRS = [
    "token%3D{m}",
    "password+%3D+{m}",
    "secret%253D{m}",
    "pw%3A{m}",
    "x=%2Fp%3Ftoken%3D{m}",
]


def hex_spell(secret: str) -> str:
    kind = rnd.randrange(6)
    if kind == 0:
        return quote(secret, safe="")
    if kind == 1:
        return quote_plus(secret)
    if kind == 2:
        return quote(quote(secret, safe=""), safe="")
    if kind == 3:
        return "".join(f"%25{byte:02X}" for byte in secret.encode())
    return secret


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_a_prefix_before_a_known_secret_reveals_no_fragment_of_it(seed: int):
    global rnd
    rnd = random.Random(seed)  # noqa: S311
    maskers = {secret: Masker(known_secrets=[secret]) for secret in HEX_SECRETS}
    for i in range(1000):
        secret = rnd.choice(HEX_SECRETS)
        parts = []
        for _ in range(rnd.randrange(1, 4)):
            parts.append(soup(3))
            parts.append(
                rnd.choice(["", *HEX_PREFIXES]) + hex_spell(secret) + rnd.choice(["", "1", "%41"])
            )
        parts.insert(rnd.randrange(len(parts) + 1), rnd.choice(ENCODED_PAIRS).format(m=marker(i)))
        text = rnd.choice(["", " ", "&"]).join(parts)
        masker = maskers[secret]
        outputs = {
            "text": masker.text(text),
            "body": masker.body(text),
            "body-json": json.loads(masker.body(json.dumps({"r": text})))["r"],
            "target": masker.target(text),
        }
        for kind, out in outputs.items():
            assert marker(i) not in out, (kind, text, out)
            for fragment in fragments(secret):
                assert fragment not in out, (kind, text, out)
