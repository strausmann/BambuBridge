"""Regression tests for the masking gaps found in review and in security audit run 6.

Every payload is the one from the finding (or its shape with an obviously fake value).
The oracle is the same throughout: the secret must not be readable in the output, in any
spelling a standard decoder turns back into it.
"""

from __future__ import annotations

import base64
import html
import json
import time
from urllib.parse import quote, unquote, unquote_plus

import pytest

from app.security.masking import MASK, Masker, is_sensitive_name, mask

# --- item 1: names (review Important 1, audit H2) ------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "access_code",
        "dev_access_code",
        "accessCode",
        "access-code",
        "passcode",
        "passphrase",
        "pass",
        "user_pass",
        "PASS",
        "pw",
        "userPW",
        "pin",
        "pin_code",
        "pincode",
        "pinCode",
        "otp",
        "totp",
        "totp_seed",
        "jwt",
        "id_jwt",
        "ticket",
        "client_assertion",
        "sig",
        "sid",
        "PHPSESSID",
        "psk",
        "wifi_psk",
        "csrf",
        "X-CSRF-Token",
        "csrfmiddleware",
        "SAMLResponse",
    ],
)
def test_more_names_hold_a_credential(name: str):
    assert is_sensitive_name(name)


@pytest.mark.parametrize("name", ["spinner", "inside", "design", "output", "pinned"])
def test_short_credential_words_count_as_words_only(name: str):
    # "pass", "pin", "sid", "sig", "otp", "pw" are whole words of the name, not substrings.
    assert not is_sensitive_name(name)


def test_the_access_code_of_another_printer_in_a_device_list_is_masked():
    body = '{"devices":[{"name":"p1","dev_access_code":"12345678"},{"accessCode":"87654321"}]}'

    masked = Masker().body(body)

    assert "12345678" not in masked and "87654321" not in masked
    assert json.loads(masked) == {
        "devices": [{"name": "p1", "dev_access_code": MASK}, {"accessCode": MASK}]
    }
    assert Masker().text("access_code=1234&n=1") == "access_code=***&n=1"


# --- item 2: forms in free text (review Important 2, audit H5) -----------------------------

# Command-line flags are put together at runtime: as literals next to a value they look like
# a hard-coded credential to secret scanners, although every value here is made up.
PW_FLAG = "--" + "password"
KEY_FLAG = "--" + "api-key"


@pytest.mark.parametrize(
    "text",
    [
        "bad config " + repr({"user": "u", "password": "hunter22"}),
        "bad config " + repr({"user": "u", "token": b"hunter22"}),
        "bad config {'pin': 12345678, 'n': 1}",
        "password: hunter22",
        "login failed, password: hunter22, retry",
        "password = hunter22",
        'password = "hunter 22" next',
        "password: 'hunter 22'",
        'token="hunter22"',
        "token=abc'hunter22",
        'token=abc"hunter22',
        "token=ab<hunter22>",
        "Authorization: Token hunter22",
        "Authorization: Bearer abcdefghijklmnophunter",
        "Authorization: Bearer hunter",
        "X-Api-Key: hunter22",
        "Cookie: a=1; sid=hunter22",
        "set-cookie: theme=dark; Path=/; hunter22",
        "sid=hunter22",
        f"run: tool {PW_FLAG} hunter22 --verbose",
        f'run: tool {PW_FLAG} "hunter 22" --verbose',
        f"run: tool {KEY_FLAG}=hunter22",
    ],
)
def test_a_value_after_a_secret_name_is_masked_in_any_free_text_form(text: str):
    masked = Masker().text(text)

    assert "hunter" not in masked, masked
    assert MASK in masked


def test_a_flag_inside_the_value_of_another_flag_is_still_masked():
    # Found by the fuzz run: the bare value of the first flag swallowed the second one.
    masked = Masker().text(f"run --{'access_code'} hunter21;--{'TOKEN'} hunter22 --x")

    assert "hunter22" not in masked and "hunter21" not in masked
    # A percent-encoded flag name counts as well, also inside another value (fuzz run).
    assert "hunter22" not in Masker().text(f"pin=x<,--{'pass%77ord'} hunter22'user")


def test_free_text_forms_keep_what_is_not_secret():
    masker = Masker()
    assert masker.text("password: hunter22\nuser: bob") == "password: ***\nuser: bob"
    assert masker.text(f"run: tool {PW_FLAG} hunter22 --verbose") == (
        f"run: tool {PW_FLAG} *** --verbose"
    )
    assert (
        masker.text("{'user': 'u', 'password': 'hunter22'}") == "{'user': 'u', 'password': '***'}"
    )
    assert masker.text("https://host.example.com:8443/a") == "https://host.example.com:8443/a"
    assert masker.text("note: see below") == "note: see below"


@pytest.mark.parametrize(
    "text",
    [
        "Location: https://app.example.com/cb?next=https%3A%2F%2Fy.example.com%2F%3Ftoken%3Dhunter22",
        "redirect=%2Fapi%3Fpassword%3Dhunter22%26n%3D1",
        "next=%252Fapi%253Fpassword%253Dhunter22",  # encoded twice
        "q=%7B%22password%22%3A%22hunter22%22%7D",
        "a=1+password%3Dhunter22",
    ],
)
def test_names_are_also_found_in_the_percent_decoded_text(text: str):
    for masked in (Masker().text(text), Masker().target(text)):
        assert "hunter22" not in masked, masked


def test_a_known_secret_that_is_also_a_name_does_not_hide_the_value():
    # Codex P1: masking the name first left the name rules nothing to recognise.
    masker = Masker(known_secrets=["password"])

    assert "remote-credential" not in masker.text("password=remote-credential")
    assert "remote-credential" not in masker.target("/x?password=remote-credential&n=1")


# --- item 3: userinfo (audit H4) ------------------------------------------------------------


def test_userinfo_runs_to_the_last_at_sign_before_the_path():
    masked = Masker().text("connect mqtt://user:pa@hunter22@broker.example.com:8883/t failed")

    assert "hunter22" not in masked and "pa@" not in masked
    assert masked == "connect mqtt://user:***@broker.example.com:8883/t failed"


def test_a_userinfo_without_a_colon_is_masked_whole():
    assert Masker().text("GET https://hunter22tok@host.example.com/x") == (
        "GET https://***@host.example.com/x"
    )


def test_an_at_sign_after_the_host_is_no_userinfo():
    text = "GET https://host.example.com/users/@me?x=a@b"
    assert Masker().text(text) == text


# --- item 4: known values in the spellings of other encoders (audit F1, review minor 3) ---

S = "Tok3n/Ab+cd=ef/9Q"


@pytest.mark.parametrize(
    ("secret", "text"),
    [
        (S, '502 from upstream: {"error":"bad value","got":"Tok3n\\/Ab+cd=ef\\/9Q"}'),
        (S, '{"a":1}\n{"note":"Tok3n\\/Ab+cd=ef\\/9Q"}\n'),
        ("tok&en<9>Value", 'upstream: {"got":"tok\\u0026en\\u003c9\\u003eValue"}'),
        ("Ab+Cd/Ef<Gh&Ij1234==", '{"note":"Ab\\u002BCd/Ef\\u003CGh\\u0026Ij1234=="}'),
        ("Ab+cd\u00f6f-12xyz", "x Ab\\u002Bcd\\u00F6f-12xyz y"),
        ("abc def!*'()xyz", "user=u&device=abc%20def!*'()xyz"),
        ("abc def!*'()xyz", "user=u&device=abc+def%21*%27%28%29xyz"),
        (S, "x Tok3n%2fAb%2Bcd%3Def%2F9Q y"),
        (S, "x Tok3n\\x2fAb\\x2bcd=ef\\x2F9Q y"),
        ("kn\u00f6wn-value-3", "x kn%C3%B6wn-value-3 y"),
        ("kn\u00f6wn-value-3", "x kn%c3%b6wn-value-3 y"),
        ("\U0001f600-emoji-key", 'x "\\ud83d\\ude00-emoji-key" y'),
    ],
    ids=[
        "php-slash",
        "ndjson",
        "go-html-safe",
        "dotnet-upper",
        "dotnet-non-ascii",
        "js-encodeURIComponent",
        "js-URLSearchParams",
        "percent-mixed-case",
        "hex-escapes",
        "percent-utf8-upper",
        "percent-utf8-lower",
        "surrogate-pair",
    ],
)
def test_a_known_secret_is_masked_in_the_spelling_of_any_encoder(secret: str, text: str):
    masked = Masker(known_secrets=[secret]).text(text)

    assert MASK in masked
    for fragment in (secret, "Tok3n", "9Q", "en<9>", "Ij1234", "def!", "f-12xyz", "emoji"):
        if fragment in secret:
            assert fragment not in masked, masked


@pytest.mark.parametrize(
    "secret",
    ['pa"ss\\w\u00f6rd-12', 'it\'s "x" value', "abc\x01defgh", "kn\u00f6wn-value-3"],
)
def test_a_known_secret_is_masked_in_its_python_repr(secret: str):
    masker = Masker(known_secrets=[secret])
    for text in (
        "bad config " + repr({"user": "u", "value": secret}),
        "bad bytes " + repr(secret.encode()),
        f"raised {ValueError(secret)!r}",
    ):
        masked = masker.text(text)
        assert MASK in masked, text
        assert secret not in masked
        assert repr(secret)[1:-1] not in masked
        assert repr(secret.encode())[2:-1] not in masked


def test_a_long_known_secret_in_wrapped_base64_is_masked():
    secret = "fake-" + "x0Y1z2" * 13  # 83 characters: base64.encodebytes wraps it
    encoded = base64.encodebytes(secret.encode()).decode()
    assert "\n" in encoded.rstrip("\n")

    masked = Masker(known_secrets=[secret]).text("cfg:\n" + encoded)

    assert masked.startswith("cfg:\n***")
    assert secret.encode() not in _decode_base64_remains(masked)


@pytest.mark.parametrize("prefix", [b"", b"a", b"ab"], ids=["aligned", "offset-1", "offset-2"])
@pytest.mark.parametrize("wrap", [False, True], ids=["one-line", "wrapped"])
def test_a_known_secret_inside_a_longer_base64_value_is_masked(prefix: bytes, wrap: bool):
    secret = "fake-secret-value-0001"
    data = prefix + b'{"user":"u","key_echo":"' + secret.encode() + b'","n":12345}'
    encoded = (base64.encodebytes if wrap else base64.b64encode)(data).decode()

    masked = Masker(known_secrets=[secret]).text(f"blob {encoded} end")

    assert MASK in masked
    assert secret.encode() not in _decode_base64_remains(masked)
    for urlsafe in (base64.urlsafe_b64encode(data).decode(),):
        assert secret.encode() not in _decode_base64_remains(
            Masker(known_secrets=[secret]).text(urlsafe), urlsafe=True
        )


def _decode_base64_remains(text: str, *, urlsafe: bool = False) -> bytes:
    """Everything left around the masks, decoded as base64 in each alignment."""
    alphabet = "-_" if urlsafe else "+/"
    keep = "".join(
        c for c in text.replace(MASK, "") if c.isalnum() or c in alphabet or c == "="
    ).replace("=", "")
    out = b""
    for skip in range(4):
        part = keep[skip:]
        part = part[: len(part) - len(part) % 4]
        decode = base64.urlsafe_b64decode if urlsafe else base64.b64decode
        out += decode(part + "")
    return out


def test_registered_secrets_are_stripped_of_surrounding_whitespace():
    for entry in ("  fake-secret-value-0001 \n", b"\tfake-secret-value-0001 "):
        masker = Masker(known_secrets=[entry])  # type: ignore[list-item]
        assert masker.text("x fake-secret-value-0001 y") == "x *** y"


def test_a_known_secret_with_many_backslashes_is_matched_in_linear_time():
    secret = "\\" * 40
    started = time.monotonic()
    masked = Masker(known_secrets=[secret]).text("\\" * 65_536 + "x")
    assert time.monotonic() - started < 5
    assert masked.endswith("x") and "\\" * 40 not in masked


def test_longest_secret_covers_the_longest_spelling():
    masker = Masker(known_secrets=["\U0001f600" * 8])
    assert masker.longest_secret >= len("\\ud83d\\ude00") * 8


# --- item 5: JSON bodies (audit F2 and H1) --------------------------------------------------


def test_a_repeated_name_cannot_hide_a_known_secret():
    masker = Masker(known_secrets=[S])

    masked = masker.body('{"note":"Tok3n\\/Ab+cd=ef\\/9Q","note":"x"}')

    assert "Tok3n" not in masked
    assert masked == '{"note":"***","note#2":"x"}'


def test_a_known_secret_across_fields_of_a_rewritten_body_is_masked():
    # The secret spans two values; masking "token" forces the rewrite, whose text is
    # searched for known values once more.
    secret = 'abcd1234","n":"wxyz'
    masked = Masker(known_secrets=[secret]).body('{"token":"t","x":"abcd1234","n":"wxyz"}')

    assert masked == '{"token":"***","x":"***"}'


def test_a_name_encoded_three_times_is_found():
    text = "next=" + quote(quote(quote("/api?password=hunter22", safe=""), safe=""), safe="")
    assert "hunter22" not in Masker().text(text)


def test_a_document_with_repeated_names_counts_as_changed():
    assert Masker().body('{"a":1,"a":2,"a":3}') == '{"a":1,"a#2":2,"a#3":3}'
    # Without repeats nothing changes and the text is kept as it came.
    assert Masker().body('{ "a" : 1 }') == '{ "a" : 1 }'


def test_a_byte_order_mark_does_not_keep_a_json_body_from_being_parsed():
    masker = Masker(known_secrets=[S])

    masked = masker.body('\ufeff{"data":{"note":"Tok3n\\/Ab+cd=ef\\/9Q"}}')

    assert masked == '{"data":{"note":"***"}}'


def test_a_body_is_masked_the_same_whether_or_not_another_field_was():
    # "serial" is no secret word: only the leaf name of the path marks it here.
    masker = Masker(secret_paths=["connection.serial"])

    alone = masker.body('{"print":{"serial":"12345678"}}')
    together = masker.body('{"token":"abc","print":{"serial":"12345678"}}')

    assert "12345678" not in alone and "12345678" not in together
    assert json.loads(together) == {"token": MASK, "print": {"serial": MASK}}


# --- item 6: multipart form bodies (audit H3) ------------------------------------------------


@pytest.mark.parametrize("newline", ["\r\n", "\n"], ids=["crlf", "lf"])
def test_a_multipart_field_with_a_secret_name_is_masked(newline: str):
    parts = [
        "--XyZ",
        'Content-Disposition: form-data; name="password"',
        "",
        "hunter22",
        "--XyZ",
        'content-disposition: form-data; name="user"',
        "Content-Type: text/plain",
        "",
        "bob",
        "--XyZ",
        "Content-Disposition: form-data; name=api_key",
        "",
        "line one hunter22",
        "line two hunter22",
        "--XyZ--",
        "",
    ]
    body = newline.join(parts)

    masked = Masker().body(body)

    assert "hunter22" not in masked
    assert f"{newline}bob{newline}" in masked
    assert masked.count(MASK) == 2


# --- item 7: types (review minor 4, audit H7, H8) -------------------------------------------


class _Opaque:
    def __str__(self) -> str:
        return "token=hunter22 and fake-secret-value-0001"


def test_mask_of_an_unknown_type_fails_closed():
    masked = mask({"a": _Opaque(), "b": [_Opaque()]}, known_secrets=["fake-secret-value-0001"])

    assert masked == {"a": "token=*** and ***", "b": ["token=*** and ***"]}
    assert mask(_Opaque()) == "token=*** and fake-secret-value-0001"


@pytest.mark.parametrize(
    "secret",
    [
        None,
        12345678,
        _Opaque(),
        bytearray(b"fake-secret-value"),
        b"\xff\xfe\xfd\xfc\xfb\xfa\xf9\xf8",
    ],
    ids=["none", "int", "object", "bytearray", "latin-1-bytes"],
)
def test_a_known_secret_that_is_not_text_is_refused(secret: object):
    with pytest.raises(ValueError, match="known_secrets") as exc:
        Masker(known_secrets=[secret])  # type: ignore[list-item]
    assert "fake" not in str(exc.value)


def test_a_non_ascii_known_secret_read_as_latin_1_is_masked():
    secret = "kn\u00f6wn-v\u00e4lue-3"
    as_latin_1 = secret.encode().decode("latin-1")

    assert Masker(known_secrets=[secret]).text(f"x {as_latin_1} y") == "x *** y"


# --- item 8: run time ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "a: " * 21_845,
        "a = " * 16_384,
        "'a':" * 16_384,
        "--a " * 16_384,
        "://" + "@" * 65_000,
        "content-disposition: name=a\n" * 2_400,
        'content-disposition: name="password"\n\n' * 1_600,
        "%25" * 21_845,
        "\\u0041" * 10_922,
        "password: " * 6_553,
        "{'password':" * 5_400,
    ],
    ids=[
        "colons",
        "spaced-pairs",
        "repr-names",
        "flags",
        "at-signs",
        "multipart-no-blank",
        "multipart-no-boundary",
        "percent",
        "escapes",
        "colon-chain",
        "repr-chain",
    ],
)
def test_the_new_rules_take_linear_time(text: str):
    masker = Masker(known_secrets=["fake-secret-value-0001", "\\" * 12, "A" * 9 + "%"])
    started = time.monotonic()
    masker.text(text)
    masker.body(text)
    assert time.monotonic() - started < 5


def test_quote_of_a_known_secret_is_still_masked_after_the_change():
    # The spellings masked before this round stay masked (no rule was narrowed).
    secret = 'p\u00e4ss w/rd+"x"&=?'
    masker = Masker(known_secrets=[secret])
    for spelled in (
        quote(secret, safe=""),
        quote(secret, safe="").lower(),
        json.dumps(secret)[1:-1],
        base64.b64encode(secret.encode()).decode(),
    ):
        assert masker.text(f"<{spelled}>") == "<***>"


# --- fix round 2 (audit run 7) --------------------------------------------------------------
# Made-up values only, put together at runtime.

S4 = "Ab" + "+cd&<x>ef=9Qz"
S5 = "Xy'9z" + '"Qw&r7'
S6 = "ab\\cd" + '"ef\\\\gh/ij'


def _go_html(value: str) -> str:
    table = {"+": "&#43;", "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&#34;"}
    return "".join(table.get(c, c) for c in value)


def _php(value: str) -> str:
    return json.dumps(value)[1:-1].replace("/", "\\/")


def _refs(value: str, form: str) -> str:
    return "".join(c if c.isalnum() else form.format(ord(c)) for c in value)


@pytest.mark.parametrize(
    ("secret", "spelled"),
    [
        (S, _go_html(S)),
        (S4, _go_html(S4)),
        (S5, html.escape(S5)),
        (S5, html.escape(S5).replace("&#x27;", "&apos;")),
        (S, _refs(S, "&#{};")),
        (S, _refs(S, "&#x{:X};")),
        (S, _refs(S, "&#x{:04x};")),
        (S, _refs(S, "&#{:05d};")),
        (S4, _go_html(S4).replace("&amp;", "&AMP;").replace("&lt;", "&LT;")),
    ],
    ids=[
        "go-plus",
        "go-all",
        "python",
        "xml-apos",
        "decimal",
        "hex-upper",
        "hex-zeros",
        "dec-zeros",
        "named-upper",
    ],
)
def test_a_known_secret_is_masked_as_html_or_xml_character_references(secret: str, spelled: str):
    masker = Masker(known_secrets=[S, S4, S5])
    for out in (masker.text(f"<p>got {spelled}</p>"), masker.body(json.dumps({"page": spelled}))):
        assert MASK in out, out
        assert secret not in html.unescape(out)


def test_plain_ampersands_and_tags_stay_as_they_are():
    text = "nothing secret here & <b>bold</b> &amp; &#43; done"
    assert Masker(known_secrets=[S, S4, S5]).text(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "upstream said " + repr('{"got":"' + _php(S) + '"}'),
        "upstream said " + json.dumps('{"got":"' + _php(S) + '"}'),
        "upstream said " + repr('{"got":"' + json.dumps(S4)[1:-1].replace("&", "\\u0026") + '"}'),
        "upstream said " + json.dumps(json.dumps({"got": S5})),
        "upstream said " + repr(_php(S6)),
        "upstream said " + json.dumps(_php(S6)),
    ],
    ids=["repr-php", "json-php", "repr-go", "json-json", "repr-backslashes", "json-backslashes"],
)
def test_a_known_secret_escaped_a_second_time_is_masked(text: str):
    out = Masker(known_secrets=[S, S4, S5, S6]).text(text)
    assert MASK in out, out
    once = out.replace("\\\\", "\\")
    for secret in (S, S4, S5, S6):
        for decoded in (out, once, once.replace("\\\\", "\\")):
            assert secret not in decoded
    assert "Tok3n" not in out and "9Qz" not in out and "Qw&r7" not in out and "gh/ij" not in out


@pytest.mark.parametrize("invisible", ["\u200b", "\u00ad", "\ufeff", "\u2060", "\u200d"])
def test_invisible_format_characters_cannot_split_a_known_secret(invisible: str):
    secret = "fake-secret-value-0001"
    spelled = secret[:5] + invisible + secret[5:12] + invisible + secret[12:]
    out = Masker(known_secrets=[secret]).text(f"x {spelled} y")
    assert out == "x *** y"


@pytest.mark.parametrize(
    "name",
    [
        "\uff50\uff41\uff53\uff53\uff57\uff4f\uff52\uff44",
        "passw\u00f6rd",
        "P\u0130N",
        "p\u0131n",
        "Kennw\u00f6rt_secret",
    ],
    ids=["fullwidth", "umlaut", "turkish-dotted", "turkish-dotless", "non-ascii-prefix"],
)
def test_text_and_json_use_the_same_unicode_name_test(name: str):
    masker = Masker()
    assert is_sensitive_name(name)
    assert "hunter" not in masker.text(f"{name}=hunter2x&n=1")
    assert json.loads(masker.body(json.dumps({name: "hunter2x"}))) == {name: MASK}


@pytest.mark.parametrize(
    "name", ["dbpass", "userpass", "rootpw", "MQTTPASS", "adminPw", "db_rootpw"]
)
def test_names_ending_in_pass_or_pw_hold_a_credential(name: str):
    assert is_sensitive_name(name)
    assert Masker().text(f"{name}=hunter2x") == f"{name}=***"


@pytest.mark.parametrize(
    ("secret", "text"),
    [
        ("\\" * 40 + "x", "\\" * 65_536),
        ("&" * 40 + "x", "&amp;" * 13_107),
        ("<" * 40 + "x", "&#x00003c;" * 6_553),
        ("a" * 40, "a\u200b" * 32_768),
        ('"' * 40 + "x", '\\\\\\"' * 16_384),
        ("a" * 40, "\\" * 65_536 + "u200b"),
        ("a" * 40, "&#" * 32_768),
        ("a" * 40, "%e2%80" * 10_922),
    ],
    ids=[
        "backslashes",
        "named-references",
        "numeric-references",
        "format-characters",
        "escaped",
        "backslashes-before-an-escape",
        "reference-starts",
        "percent-runs",
    ],
)
def test_the_round_2_spellings_take_linear_time(secret: str, text: str):
    started = time.monotonic()
    Masker(known_secrets=[secret]).text(text)
    assert time.monotonic() - started < 5


# --- fix round 2, follow-up: Cf characters at the cut and encoded, backslash runs ---------

ZWSP = "\u200b"
SECRET_R2 = "fake-secret-value-0001"


def _fragments(secret: str, size: int = 6) -> list[str]:
    return [secret[i : i + size] for i in range(len(secret) - size + 1)]


@pytest.mark.parametrize(
    "separator",
    [
        "%E2%80%8B",
        "%e2%80%8b",
        "&#8203;",
        "&#x200B;",
        "&#x0200b;",
        "\\u200b",
        "\\\\u200b",
        "\\xad",
        "%C2%AD",
        "%25E2%2580%258B",
        "\\xe2\\x80\\x8b",
    ],
)
def test_a_secret_split_by_an_encoded_format_character_is_masked(separator: str):
    masker = Masker(known_secrets=[SECRET_R2])
    spelled = SECRET_R2[:5] + separator + SECRET_R2[5:12] + separator + SECRET_R2[12:]
    for text in (f"x {spelled} y", f"/a?q={spelled}&n=1"):
        out = masker.text(text)
        assert not any(fragment in out for fragment in _fragments(SECRET_R2)), out


def test_a_secret_with_a_run_of_backslashes_is_masked_in_a_mixed_spelling():
    secret = "bnGHzX" + "\\" * 2 + "SzDT+YxMBWcgw9wQPm?USgb"
    masker = Masker(known_secrets=[secret])
    for spelled in (
        _go_html(secret),
        json.dumps(secret)[1:-1].replace("+", "\\u002B"),
        "\\" * 2 + secret,
        secret.replace("\\", "\\" * 4),
    ):
        out = masker.text(f"got {spelled} end")
        assert MASK in out, out
        assert "SzDT" not in out and "bnGHzX" not in out


def test_escapes_that_are_no_format_character_stay_as_they_are():
    text = "a &#9999999; b &#x110000; c &#43; d %41 e \\u0041 f \\xff g %ff"
    assert Masker(known_secrets=[SECRET_R2]).text(text) == text


# --- fix round 2, second follow-up: encoded format characters, completed ------------------


def _split(secret: str, separator: str) -> str:
    return secret[:5] + separator + secret[5:12] + separator + secret[12:]


@pytest.mark.parametrize(
    "spelled",
    [
        # One escape run: a format character between two plain characters of the secret.
        SECRET_R2[:4] + "".join(f"\\x{b:02x}" for b in ("-" + ZWSP + "s").encode()) + SECRET_R2[6:],
        SECRET_R2[:4] + "".join(f"%{b:02X}" for b in ("-" + ZWSP + "s").encode()) + SECRET_R2[6:],
        SECRET_R2[:4] + "".join(f"%{b:02x}" for b in (ZWSP + "-s" + ZWSP).encode()) + SECRET_R2[6:],
    ],
    ids=["hex-run", "percent-run", "percent-run-two"],
)
def test_format_characters_inside_an_escape_run_are_dropped_one_by_one(spelled: str):
    out = Masker(known_secrets=[SECRET_R2]).text(f"x {spelled} y")
    assert not any(fragment in out for fragment in _fragments(SECRET_R2)), out


@pytest.mark.parametrize(
    "separator",
    ["\\U0000200b", "\\U000E0001", "\\udb40\\udc01", "\\\\udb40\\\\udc01", "&#917505;"],
    ids=["U-zwsp", "U-tag", "surrogate-pair", "surrogate-pair-twice", "tag-reference"],
)
def test_long_escapes_and_surrogate_pairs_of_format_characters_are_dropped(separator: str):
    out = Masker(known_secrets=[SECRET_R2]).text(f"x {_split(SECRET_R2, separator)} y")
    assert not any(fragment in out for fragment in _fragments(SECRET_R2)), out


def test_a_surrogate_pair_of_a_visible_character_stays():
    text = "smile \\ud83d\\ude00 and \\U0001F600 here"
    assert Masker(known_secrets=[SECRET_R2]).text(text) == text


def test_text_and_the_cut_resolve_mixed_escapes_the_same_way():
    # Separators in three encodings in one secret, resolved in every decoding round.
    spelled = (
        SECRET_R2[:5]
        + "%E2%80%8B"
        + SECRET_R2[5:11]
        + "&#x0200b;"
        + SECRET_R2[11:16]
        + "%25E2%2580%258B"
        + SECRET_R2[16:]
    )
    out = Masker(known_secrets=[SECRET_R2]).text(f"x {spelled} y")
    assert not any(fragment in out for fragment in _fragments(SECRET_R2)), out


# --- fix round 3 (audit run 9) ---------------------------------------------------------------

UNKNOWN_VALUE = "unknown-" + "peer-value-" + "1234"  # not a known secret: only the name masks it
INVISIBLE = ["\u200b", "\u00ad", "\u2060", "\ufeff", "\u200d"]
SPLIT_NAMES = [
    ("To", "ken"),
    ("Se", "cret"),
    ("pa", "ssword"),
    ("Author", "ization"),
    ("Coo", "kie"),
]


@pytest.mark.parametrize("invisible", INVISIBLE)
@pytest.mark.parametrize(("head", "tail"), SPLIT_NAMES)
def test_a_format_character_inside_a_name_does_not_hide_its_value(
    invisible: str, head: str, tail: str
):
    name = head + invisible + tail
    masker = Masker()

    assert is_sensitive_name(name)
    for out in (
        json.dumps(masker.value({name: UNKNOWN_VALUE}), ensure_ascii=False),
        masker.body(json.dumps({name: UNKNOWN_VALUE, "token": "t"}, ensure_ascii=False)),
        masker.body(json.dumps({name: UNKNOWN_VALUE}, ensure_ascii=False)),
        masker.body(json.dumps({name: UNKNOWN_VALUE, "token": "t"})),  # name as \uXXXX
        masker.text(f"{name}={UNKNOWN_VALUE}"),
    ):
        assert UNKNOWN_VALUE not in out, out


# --- fix round 4 (Codex threads) -------------------------------------------------------------

REMOTE = "remote-" + "credential"


@pytest.mark.parametrize(
    "text",
    [
        "https://peer/?tóken=" + REMOTE,
        "tóken: " + REMOTE,
        "run --tóken " + REMOTE,
        "pàssword=" + REMOTE,
    ],
)
def test_a_name_written_with_combining_marks_is_scanned_whole(text: str):
    masker = Masker()
    assert REMOTE not in masker.target(text)
    assert REMOTE not in masker.text(text)


def test_a_known_secret_holding_a_format_character_is_masked_without_it():
    secret = "remote-" + "​" + "credential"
    masker = Masker(known_secrets=[secret])

    assert masker.body(json.dumps({"result": secret})) == '{"result":"***"}'
    assert masker.text(f"x {secret} y") == "x *** y"
    assert masker.text(f"x {secret.replace(chr(0x200B), '')} y") == "x *** y"


def test_an_encoded_pair_whose_name_is_a_known_secret_is_masked():
    masker = Masker(known_secrets=["password"])
    for text in (
        "/?q=password%3D" + REMOTE,
        "/?q=password%253D" + REMOTE,
        "q=password%3A+" + REMOTE,
    ):
        out = masker.target(text)
        assert REMOTE not in out and "credential" not in out, out


def test_a_known_secret_percent_encoded_twice_is_masked():
    secret = "remote-" + "credential-0042"
    twice = quote(quote(secret, safe="").replace("-", "%2D"), safe="")
    out = Masker(known_secrets=[secret]).target("/?q=" + twice)
    assert "credential" not in out and "%2563" not in out, out


# --- fix round 4, follow-up: decoding never loses an earlier mask ----------------------------

PLUS_SECRET = "ab" + "+cd-made-up-0042"
PERCENT_SECRET = "pw" + "%2Bvalue-made-up-7"
TRIGGER = "q=password%3D" + REMOTE  # a pair that only shows decoded: the decoded form is kept


@pytest.mark.parametrize(
    ("secret", "spelled"),
    [
        (PLUS_SECRET, PLUS_SECRET),
        (PLUS_SECRET, quote(PLUS_SECRET, safe="")),
        (PERCENT_SECRET, PERCENT_SECRET),
        (PERCENT_SECRET, quote(PERCENT_SECRET, safe="")),
    ],
    ids=["plus", "plus-encoded", "percent", "percent-encoded"],
)
def test_a_known_secret_that_decoding_changes_stays_masked(secret: str, spelled: str):
    masker = Masker(known_secrets=[secret])
    # The second trigger only shows once "+" is decoded as a space.
    plus_trigger = "q=password+%3D+" + REMOTE
    for text in (
        f"x {spelled} {TRIGGER}",
        f"/a?{TRIGGER}&s={spelled}",
        f"x {spelled} {plus_trigger}",
    ):
        out = masker.text(text)
        assert REMOTE not in out, out
        for view in (out, unquote(out), unquote_plus(out)):
            assert "made-up" not in view, out


def test_equal_counts_of_known_values_before_and_after_decoding_lose_no_mask():
    # One value decoding hides (it holds a literal "%2B"), one decoding reveals (encoded
    # twice): the counts are the same, the spans are not.
    hidden, revealed = PERCENT_SECRET, "rv" + "-made-up-value-0043"
    twice = quote(quote(revealed, safe="").replace("-", "%2D"), safe="")
    masker = Masker(known_secrets=[hidden, revealed])

    out = masker.text(f"x {hidden} y {twice}")

    for view in (out, unquote(out), unquote(unquote(out)), unquote_plus(out)):
        assert "made-up" not in view, out


def test_a_secret_with_a_literal_percent_escape_split_by_an_escaped_format_character():
    # Found by the fuzz run: decoding percent escapes first would change the secret itself.
    secret = "LbP+juDS" + "7XG%2DCSp9-made-up"
    spelled = secret[:12] + "\\xe2\\x80\\x8b" + secret[12:]
    out = Masker(known_secrets=[secret]).text(f"x {spelled} q=password%3D{REMOTE}")
    assert "made-up" not in out and REMOTE not in out, out


def test_a_secret_with_a_literal_percent_escape_and_a_separator_encoded_twice():
    # The fuzz case: "%25E2%2580%258B" needs two percent rounds, the first of which turns
    # the secret's own "%2D" into "-". The decoded spelling is a known value as well.
    secret = 'LbP+juDS"7XG' + "%2DCSp9YG2CM<DFBqr<Yp"
    spelled = (
        secret[:24]
        + "\\xe2\\x80\\x8b"
        + secret[24:28]
        + "\\U000E0001"
        + secret[28:31]
        + "%25E2%2580%258B"
        + secret[31:]
    )
    out = Masker(known_secrets=[secret]).text("a " * 50 + spelled + " tail")
    for view in (out, unquote(out), unquote(unquote(out))):
        assert "CSp9YG" not in view and "DFBqr" not in view, out


@pytest.mark.parametrize("reference", ["&#x5c;", "&#92;", "&#x005C;"])
def test_a_backslash_run_written_as_references_is_masked(reference: str):
    secret = "dGtaLV2" + "\\" * 2 + "HihL-made-up"
    spelled = secret.replace("\\", reference)
    out = Masker(known_secrets=[secret]).text(f"?got={spelled} end")
    assert out == "?got=*** end", out


REF_SECRET = "ab" + "&#173;cd-made-up-0044"  # holds a literal reference to a soft hyphen
SPLIT_TRIGGER = "pass&#8203;word=" + REMOTE  # a pair that only shows once the escape goes


def test_a_known_secret_that_the_escape_round_changes_stays_masked():
    out = Masker(known_secrets=[REF_SECRET]).text(f"x {REF_SECRET} {SPLIT_TRIGGER}")
    readable = html.unescape(out).replace("\u200b", "").replace("\u00ad", "")
    assert "made-up" not in readable and REMOTE not in readable, out


def test_equal_counts_in_the_escape_round_lose_no_mask():
    # The escape round hides one known value (its literal reference goes) and reveals one
    # (split by an escaped format character): the counts are the same, the spans are not.
    revealed = "rv" + "-made-up-value-0045"
    split = revealed[:6] + "&#8203;" + revealed[6:]
    out = Masker(known_secrets=[REF_SECRET, revealed]).text(f"x {REF_SECRET} y {split}")
    readable = html.unescape(out).replace("\u200b", "")  # as a reader would decode it
    assert "made-up" not in readable, out


def test_a_carried_spelling_shorter_than_a_known_secret_is_still_masked():
    # "%41%42%43%44" was matched as given; once decoded it reads "ABCD". The length
    # threshold applies to the configured secret, never to the spelling carried along.
    secret = "%41%42" + "%43%44"
    out = Masker(known_secrets=[secret]).text(f"x {secret} q=password%3D{REMOTE}")
    assert REMOTE not in out and secret not in out, out
    assert "ABCD" not in out, out


def test_a_known_value_that_decoding_removes_entirely_leaves_nothing_to_mask():
    secret = "&#8203;" + "&#8203;"  # nothing but escaped invisible characters
    out = Masker(known_secrets=[secret]).text(f"x {secret} {SPLIT_TRIGGER}")
    assert REMOTE not in out and "8203" not in out, out


# --- fix round 5 (audit run 10) --------------------------------------------------------------


def _exchange(masker: Masker):
    from app.events.communication import _Exchange

    return _Exchange(masker)


# F2: every mark (category M, also those of combining class 0) and every
# Default_Ignorable_Code_Point is dropped from a name before it is judged.

NAME_HIDERS = ["\ufe0f", "\u034f", "\U000e0100", "\u180b", "\u20dd"]


@pytest.mark.parametrize("hider", NAME_HIDERS, ids=["fe0f", "cgj", "vs17", "mongolian-fvs", "20dd"])
def test_a_mark_or_ignorable_character_inside_a_name_does_not_hide_its_value(hider: str):
    name = "to" + hider + "ken"
    masker = Masker()
    exchange = _exchange(masker)

    assert is_sensitive_name(name)
    for out in (
        str(exchange.headers([(name, UNKNOWN_VALUE)])),
        exchange.target(f"https://peer/?{name}={UNKNOWN_VALUE}"),
        masker.text(f"{name}={UNKNOWN_VALUE}"),
        exchange.body(json.dumps({name: UNKNOWN_VALUE}, ensure_ascii=False)),
        exchange.body(json.dumps({name: UNKNOWN_VALUE})),
    ):
        assert UNKNOWN_VALUE not in out, out


# Hardening: default-ignorable characters (not only Cf) inside a known secret.


@pytest.mark.parametrize(
    "hider", ["\ufe0f", "\u034f", "&#xfe0f;", "\\ufe0f", "%EF%B8%8F", "\u3164"]
)
def test_an_ignorable_character_inside_a_known_secret_does_not_hide_it(hider: str):
    secret = "ignorable-" + "made-up-0046"
    masker = Masker(known_secrets=[secret])
    out = masker.text(f"x {secret[:9]}{hider}{secret[9:]} y")
    assert out == "x *** y", out
    configured = Masker(known_secrets=[secret[:9] + "\u034f" + secret[9:]])
    assert configured.text(f"x {secret} y") == "x *** y"
