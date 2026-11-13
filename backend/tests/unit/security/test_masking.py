from __future__ import annotations

import base64
import json
from urllib.parse import quote, quote_plus

import pytest

from app.security.masking import (
    MASK,
    Masker,
    is_sensitive_name,
    mask,
    secret_paths_from_schema,
)

# Obviously fake values, readable text only.
SECRET = "fake-secret-value-0001"
OTHER = "another-fake-secret-2"


def test_mask_headers_case_insensitive():
    headers = {
        "AUTHORIZATION": "Bearer abc",
        "authorization": "Bearer abc",
        "Cookie": "sid=1",
        "SET-cookie": "sid=1; Path=/",
        "x-BambuBridge-KEY": "bb_x",
        "X-Api-TOKEN": "t",
        "x-client-Secret": "s",
        "X-PASSWORD": "p",
        "Api-Key": "k",
        "Proxy-Authorization": "Basic abc",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }

    masked = mask(headers, secret_paths=(), known_secrets=())

    assert {name for name, value in masked.items() if value == MASK} == set(headers) - {
        "Content-Type",
        "Accept",
    }
    assert masked["Content-Type"] == "application/json"
    assert masked["Accept"] == "*/*"
    assert headers["AUTHORIZATION"] == "Bearer abc"  # the input is not changed


@pytest.mark.parametrize(
    "name",
    [
        "authorization",
        "Authorization",
        "COOKIE",
        "Set-Cookie",
        "X-BambuBridge-Key",
        "x-auth",
        "access_token",
        "refreshToken",
        "client_secret",
        "Passwd",
        "password",
        "api-key",
        "X-Signature",
        "session_id",
        "credentials",
        # Full-width letters fold to the same name.
        "\uff41\uff55\uff54\uff48orization",
    ],
)
def test_sensitive_names(name: str):
    assert is_sensitive_name(name)


@pytest.mark.parametrize(
    "name", ["Content-Type", "Accept", "author", "Authors", "author_name", "user", "id", "Location"]
)
def test_plain_names(name: str):
    assert not is_sensitive_name(name)


def test_mask_known_secret_inside_url_and_body():
    url = f"https://printer.example.com/v1/{SECRET}/files?device={SECRET}&page=2"
    body = {"note": f"before {SECRET} after", "items": [f"x{SECRET}y", 3]}

    masked_url = mask(url, secret_paths=(), known_secrets=[SECRET])
    masked_body = mask(body, secret_paths=(), known_secrets=[SECRET])

    assert SECRET not in masked_url
    assert masked_url == "https://printer.example.com/v1/***/files?device=***&page=2"
    assert SECRET not in json.dumps(masked_body)
    assert masked_body == {"note": "before *** after", "items": ["x***y", 3]}


def test_mask_schema_marked_field_nested():
    schema = {
        "type": "object",
        "properties": {
            "host": {"type": "string"},
            "connection": {
                "type": "object",
                "properties": {
                    "serial": {"type": "string"},
                    "access_code": {"type": "string", "x-secret": True},
                    "mqtt": {"$ref": "#/$defs/Mqtt"},
                },
            },
            "accounts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"pin": {"type": "string", "x-secret": True}},
                },
            },
        },
        "$defs": {
            "Mqtt": {
                "type": "object",
                "properties": {
                    "user": {"type": "string"},
                    "phrase": {"type": "string", "x-secret": True},
                },
            }
        },
    }
    paths = secret_paths_from_schema(schema)
    assert paths == {"connection.access_code", "connection.mqtt.phrase", "accounts.pin"}

    value = {
        "host": "printer.example.com",
        "connection": {
            "serial": "0001",
            "access_code": "1234",
            "mqtt": {"user": "bblp", "phrase": "abcd"},
        },
        "accounts": [{"pin": "1"}, {"pin": "2", "label": "b"}],
        "pin": "not at the path",
    }

    masked = mask(value, secret_paths=paths, known_secrets=())

    assert masked == {
        "host": "printer.example.com",
        "connection": {
            "serial": "0001",
            "access_code": MASK,
            "mqtt": {"user": "bblp", "phrase": MASK},
        },
        "accounts": [{"pin": MASK}, {"pin": MASK, "label": "b"}],
        # The leaf name of a path counts wherever it stands (and "pin" is a secret word).
        "pin": MASK,
    }
    assert value["connection"]["access_code"] == "1234"  # type: ignore[index]  # a copy was masked


def test_a_secret_path_also_matches_deeper_in_a_message():
    # A message that wraps the configured object one level down.
    masked = mask(
        {"print": {"connection": {"access_code": "1234"}}},
        secret_paths=["connection.access_code"],
        known_secrets=(),
    )
    assert masked == {"print": {"connection": {"access_code": MASK}}}


def test_a_secret_path_is_matched_without_regard_to_case():
    assert mask({"Connection": {"ACCESS_CODE": "1"}}, secret_paths=["connection.access_code"]) == {
        "Connection": {"ACCESS_CODE": MASK}
    }


def test_the_value_under_a_secret_path_is_masked_whatever_its_type():
    masked = mask(
        {"a": {"x": {"deep": ["v"]}}, "b": {"x": 12345}, "c": {"x": None}},
        secret_paths=["x"],
        known_secrets=(),
    )
    assert masked == {"a": {"x": MASK}, "b": {"x": MASK}, "c": {"x": None}}


def test_fields_with_a_sensitive_name_are_masked_in_json():
    masked = mask({"user": "u", "Password": "p", "nested": [{"apiKey": "k", "n": 1}]})
    assert masked == {"user": "u", "Password": MASK, "nested": [{"apiKey": MASK, "n": 1}]}


def test_known_secrets_shorter_than_8_characters_are_not_searched():
    assert mask("pin 1234567 end", known_secrets=["1234567"]) == "pin 1234567 end"
    assert mask("pin 12345678 end", known_secrets=["12345678"]) == "pin *** end"


def test_a_known_secret_is_masked_as_a_number_and_as_a_key():
    value = "zz-known-value-0001"  # as a field name it has no sensitive word in it
    masked = mask({"code": 12345678, value: 1, "n": 5}, known_secrets=["12345678", value])
    assert masked == {"code": MASK, MASK: 1, "n": 5}


def test_overlapping_occurrences_leave_no_fragment():
    secret = "abcabcabc"  # overlaps with itself
    text = "x" + "abcabcabcabc" + "y"  # two occurrences, three characters apart
    masked = mask(text, known_secrets=[secret])
    assert masked == "x***y"


def test_the_longer_of_two_secrets_wins():
    short, long = "fake-secret", "fake-secret-with-a-tail"
    assert mask(f"a {long} b", known_secrets=[short, long]) == "a *** b"
    assert mask(f"a {long} b", known_secrets=[long, short]) == "a *** b"


@pytest.mark.parametrize(
    "encode",
    [
        lambda s: quote(s, safe=""),
        lambda s: quote_plus(s),
        lambda s: quote(s, safe="").lower(),
        lambda s: base64.b64encode(s.encode()).decode(),
        lambda s: base64.urlsafe_b64encode(s.encode()).decode().rstrip("="),
        lambda s: json.dumps(s)[1:-1],
        lambda s: json.dumps(s, ensure_ascii=False)[1:-1],
    ],
    ids=["percent", "plus", "percent-lower", "base64", "base64url", "json", "json-utf8"],
)
def test_encoded_forms_of_a_known_secret_are_masked(encode):
    secret = 'p\u00e4ss w/rd+"x"&=?'
    encoded = encode(secret)

    masked = mask(f"<{encoded}>", known_secrets=[secret])

    assert masked == "<***>"


def test_free_text_rules():
    masker = Masker()
    assert (
        masker.text("GET https://user:hunter2@host.example.com/x failed")
        == "GET https://user:***@host.example.com/x failed"
    )
    assert masker.text("a?access_token=abc&page=2#frag") == "a?access_token=***&page=2#frag"
    assert masker.text("pass%77ord=abc&x=1") == "pass%77ord=***&x=1"
    # A header line is masked by its name: everything after the colon goes.
    assert masker.text("Authorization: Bearer abc.DEF-123") == "Authorization: ***"
    assert masker.text("sent basic dXNlcjpwYXNz") == "sent basic ***"
    assert masker.text("basic authentication failed") == "basic authentication failed"
    assert masker.text('{"password": "p\\"q", "n": 1') == '{"password": "***", "n": 1'
    assert masker.text('{"apiKey":12345,"n":1') == '{"apiKey":***,"n":1'
    assert masker.text('{"token": null}') == '{"token": null}'
    assert masker.text('{"password": "cut off') == '{"password": "***'
    assert masker.text("nothing to see: a=b") == "nothing to see: a=b"
    # Broken JSON with an object under a secret name: its end cannot be found, the rest goes.
    assert masker.text('{"a": 1, "secrets": {"x": "y"}, "b": "c"') == '{"a": 1, "secrets": ***'
    assert masker.text('{"a": {"x": "y"}, "b": [1') == '{"a": {"x": "y"}, "b": [1'


def test_free_text_masks_the_last_name_of_a_secret_path():
    masker = Masker(secret_paths=["connection.access_code"])
    assert masker.text('{"access_code": "1234", "x"') == '{"access_code": "***", "x"'
    assert masker.text("access_code=1234&x=1") == "access_code=***&x=1"


def test_target_masks_a_percent_encoded_known_secret_in_any_spelling():
    secret = "fake secret/value"
    masker = Masker(known_secrets=[secret])
    # Every character percent-encoded: no fixed encoded form of the secret matches this.
    spelled = "".join(f"%{ord(c):02x}" for c in secret)

    masked = masker.target(f"/files/{spelled}/list?q=1")

    assert "fake" not in masked and spelled not in masked
    assert masked == "/files/***/list?q=1"


def test_target_keeps_an_ordinary_address_as_it_is():
    masker = Masker(known_secrets=[SECRET])
    target = "https://printer.example.com/a%20b/c?x=1&y=%2F#top"
    assert masker.target(target) == target


def test_body_masks_json_by_structure_and_keeps_other_text():
    masker = Masker(secret_paths=["access_code"], known_secrets=[SECRET])

    assert masker.body('{"access_code": "12\\u0033", "n": 1.0}') == '{"access_code":"***","n":1.0}'
    # An escape inside the JSON text hides the secret from a plain search.
    escaped = json.dumps({"note": SECRET}).replace("fake", "\\u0066ake")
    assert SECRET not in escaped
    assert masker.body(escaped) == '{"note":"***"}'
    # Nothing to mask: the text is stored as it came, spacing included.
    assert masker.body('{ "n" : 1 }') == '{ "n" : 1 }'
    assert masker.body("plain text") == "plain text"
    assert masker.body(f"not json {SECRET}") == "not json ***"
    assert masker.body('{"broken": ') == '{"broken": '


def test_body_with_a_shadowed_duplicate_key_is_still_masked():
    masker = Masker(known_secrets=[SECRET])
    body = '{"a": "' + SECRET + '", "a": "x"}'  # a JSON parser keeps the last "a" only
    # Rewritten from its pairs, the repeat numbered: no parser can pick another value.
    assert masker.body(body) == '{"a":"***","a#2":"x"}'


def test_body_nested_too_deeply_is_not_recorded():
    masker = Masker(known_secrets=[SECRET])
    body = "[" * 100_000 + json.dumps(SECRET) + "]" * 100_000

    masked = masker.body(body)

    assert SECRET not in masked
    assert len(masked) < 200


def test_mask_copies_and_converts_containers():
    source = {"list": [1, (2, 3)], "bytes": b"\x00\x01", "flag": True, "none": None, 5: "five"}
    masked = mask(source)
    assert masked == {
        "list": [1, [2, 3]],
        "bytes": "<binary 2 bytes>",
        "flag": True,
        "none": None,
        "5": "five",
    }


def test_secret_paths_from_schema_handles_combinators_and_cycles():
    schema = {
        "properties": {
            "a": {"anyOf": [{"type": "null"}, {"type": "string", "x-secret": True}]},
            "b": {"allOf": [{"$ref": "#/$defs/Node"}]},
            "c": {"type": "string", "x-secret": False},
            "d": {"$ref": "#/$defs/Missing"},
            "e": {"$ref": "https://example.com/other.json"},
        },
        "$defs": {
            "Node": {
                "properties": {
                    "value": {"type": "string", "x-secret": True},
                    "next": {"$ref": "#/$defs/Node"},
                }
            }
        },
    }
    assert secret_paths_from_schema(schema) == {"a", "b.value"}
    assert secret_paths_from_schema({}) == frozenset()
    assert secret_paths_from_schema({"properties": "not a mapping"}) == frozenset()


def test_invalid_secret_paths_and_short_secrets_are_ignored():
    # Known secrets that are not text raise (test_masking_review.py); short ones are skipped.
    masker = Masker(
        secret_paths=["", "..", 5, "a.b"],  # type: ignore[list-item]
        known_secrets=["short", " short2 ", SECRET],
    )
    assert masker.value({"a": {"b": 1}, "t": SECRET}) == {"a": {"b": MASK}, "t": MASK}


def test_two_adjacent_secrets_are_both_replaced():
    # Touching spans share one mask.
    assert mask(SECRET + OTHER, known_secrets=[SECRET, OTHER]) == "***"


def test_a_quoted_value_and_separators_inside_a_value_are_masked_whole():
    masker = Masker()
    assert (
        masker.text('login failed: password="ab cd" user=u') == "login failed: password=*** user=u"
    )
    assert masker.text("password='ab cd' next") == "password=*** next"
    assert masker.text('password="never closed') == "password=***"
    assert masker.text("x?token=ab;cd#ef&page=2") == "x?token=***&page=2"
    assert masker.text("x?page=2&token=ab,cd") == "x?page=2&token=***"


def test_a_masked_json_body_stays_valid_json():
    masker = Masker(known_secrets=[SECRET])
    # A string that ends in "name=" must not make the text rules eat the following fields.
    body = json.dumps({"a": "see token=", "b": "x", "password": "p", "c": [1, {"d": "e"}]})

    masked = masker.body(body)

    assert json.loads(masked) == {
        "a": "see token=***",
        "b": "x",
        "password": "***",
        "c": [1, {"d": "e"}],
    }


def test_a_json_body_with_a_lone_surrogate_escape_is_storable_after_masking():
    masker = Masker()
    body = '{"a": "\\ud800 \\udc00x", "password": "p"}'
    assert "\\ud800" in body  # the escape sequence, six ASCII characters

    masked = masker.body(body)

    assert masked == '{"a":"\ufffd \ufffdx","password":"***"}'
    masked.encode("utf-8")  # no lone surrogate is left


def test_target_decoded_for_a_secret_holds_no_nul():
    masker = Masker(known_secrets=[SECRET])
    half = len(SECRET) // 2
    spelled = "".join(f"%{ord(c):02x}" for c in SECRET)
    # The second copy is cut in two by an encoded NUL: taking the NUL out later must not
    # put a readable secret together.
    target = f"/a/{spelled}/{SECRET[:half]}%00{SECRET[half:]}/b"

    masked = masker.target(target)

    assert "\x00" not in masked
    assert SECRET not in masked
    assert masked == "/a/***/***/b"


def test_a_single_string_is_one_secret_and_one_path_not_its_characters():
    assert mask(f"a {SECRET} b", known_secrets=SECRET) == "a *** b"
    assert mask({"pin": "1"}, secret_paths="pin") == {"pin": MASK}


def test_known_secrets_given_as_bytes_are_searched_as_text():
    assert mask(f"a {SECRET} b", known_secrets=[SECRET.encode()]) == "a *** b"  # type: ignore[list-item]
    with pytest.raises(ValueError, match="UTF-8"):
        mask("a b", known_secrets=[b"\xff\xfe\xfd\xfc\xfb\xfa\xf9\xf8"])  # type: ignore[list-item]


def test_a_json_field_name_with_a_broken_escape_is_judged_as_written():
    assert Masker().text('{"token\\q": "abc", "n": 1') == '{"token\\q": "***", "n": 1'


def test_secret_paths_from_schema_skips_a_combinator_that_is_not_a_list():
    assert (
        secret_paths_from_schema({"properties": {"a": {"anyOf": {"x-secret": True}}}})
        == frozenset()
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('a="x password=hunter22"', 'a="x password=***'),
        ("a='x password=hunter22'", "a='x password=***"),
        ("a=\"b='c token=hunter22 d' e\" f", "a=\"b='c token=*** d' e\" f"),
        (
            'a="b=\\"c password=hunter22\\""',
            'a="b=\\"c password=***',
        ),  # a bare value ends at white space or "&" only: the quotes go with it
        ("a=1;password=hunter22", "a=1;password=***"),
        ("a=x,token=hunter22&b=2", "a=x,token=***&b=2"),
        ("a=b=c=password=hunter22", "a=b=c=password=***"),
        ('note="see" password="hunter22 x" end', 'note="see" password=*** end'),
    ],
    ids=["double", "single", "nested", "escaped", "semicolon", "comma", "chain", "after-quoted"],
)
def test_a_pair_inside_the_value_of_a_plain_name_is_still_masked(text: str, expected: str):
    masked = Masker().text(text)

    assert "hunter22" not in masked
    assert masked == expected


def test_a_sensitive_name_with_a_quoted_value_is_masked_whole():
    masker = Masker()
    assert masker.text('password="a b=c token=d" x') == "password=*** x"
    assert masker.text("password='a \"b\" c' x") == "password=*** x"
    assert masker.text('a="x" secret="p q" b="y"') == 'a="x" secret=*** b="y"'


def test_a_long_chain_of_pairs_is_scanned_without_recursion():
    text = "a=" * 50_000 + "password=hunter22"
    assert Masker().text(text) == "a=" * 50_000 + "password=***"


def _seconds(masker: Masker, text: str) -> float:
    """The best of three runs: less sensitive to other load than a single one."""
    import time

    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        masker.text(text)
        best = min(best, time.perf_counter() - started)
    return best


@pytest.mark.parametrize(
    ("unit", "count"),
    [("A", 32_768), ("a=", 16_384), ('"', 32_768), ("a:", 16_384), ("a:", 16_383)],
    ids=["one-run", "pairs", "quotes", "colons", "userinfo"],
)
def test_the_text_rules_take_linear_time(unit: str, count: int):
    # Relative, not absolute: twice the input may take about twice the time, whatever the
    # machine and its load. A quadratic scan takes four times as long.
    masker = Masker(known_secrets=[SECRET])
    prefix = "://" if count % 2 else ""
    single = _seconds(masker, prefix + unit * count)
    double = _seconds(masker, prefix + unit * (2 * count))
    assert double / max(single, 1e-3) < 3.0, (single, double)


def _pair_scan_seconds(masker: Masker, text: str) -> float:
    import time

    best = float("inf")
    for _ in range(3):
        started = time.perf_counter()
        list(masker._pair_spans(text))
        best = min(best, time.perf_counter() - started)
    return best


def test_the_pair_scan_alone_takes_linear_time():
    # A direct guard for the pair scan, with sizes at which a cheap per-name pass over the
    # text before it (a ``str.count`` over the prefix runs at C speed) still dominates:
    # many names, far apart, so the scan's own work per name is small. Twice the input
    # takes about twice the time (1.8 measured); such a quadratic pass makes it four.
    masker = Masker()
    unit = "n=" + "v" * 125 + "&"
    single = _pair_scan_seconds(masker, unit * 8_192)
    double = _pair_scan_seconds(masker, unit * 16_384)
    assert double / max(single, 1e-3) < 3.0, (single, double)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The bare value swallows the second name: its quoted value has to go with it.
        ("secret=abc,token='hunter22 x' end", "secret=*** end"),
        ('secret=abc;b="hunter22 x"&n=1', "secret=***&n=1"),
        ("Authorization=Bearer hunter22.x next", "Authorization=*** next"),
        ("basic TOKEN=Bearer hunter22 next", "basic *** next"),
        ('Bearer xAuthorization="hunter22" next', "Bearer *** next"),
        ("token=abc== next", "token=*** next"),
    ],
    ids=[
        "swallowed-single",
        "swallowed-double",
        "scheme-value",
        "scheme-in-scheme",
        "name-after-scheme",
        "padding",
    ],
)
def test_rules_do_not_hide_a_value_from_each_other(text: str, expected: str):
    masked = Masker().text(text)

    assert "hunter22" not in masked
    assert masked == expected


def test_a_dict_key_is_masked_like_any_text():
    assert mask({"see password='hunter22'": 1}) == {"see password=***": MASK}
    assert mask({"q": {"x?token=hunter22&n=1": 1}}) == {"q": {"x?token=***&n=1": MASK}}


def test_a_pair_inside_a_span_that_is_masked_already_is_still_looked_at():
    # The swallowed name takes '&TOKEN=' for its quoted value; TOKEN has a value of its own.
    text = "secret=Bearer abcb='&TOKEN='hunter22''/"
    masked = Masker().text(text)

    assert "hunter22" not in masked
    assert masked == "secret=***'/"


def test_a_chain_of_secret_pairs_is_linear():
    import time

    started = time.monotonic()
    masked = Masker().text("token=" * 100_000 + "x")
    assert time.monotonic() - started < 5
    assert masked == "token=***"


def test_a_name_cannot_percent_decode_its_way_out():
    # "%bA" is a valid escape: decoded, the name no longer reads "authorization".
    assert Masker().text("%bAuthorization='hunter22'") == "%bAuthorization=***"
    assert Masker().text('{"%bAuthorization": "hunter22"') == '{"%bAuthorization": "***"'
