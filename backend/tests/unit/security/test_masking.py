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
        "pin": "not at the path",
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
    assert masker.text("Authorization: Bearer abc.DEF-123") == "Authorization: Bearer ***"
    assert masker.text("sent basic dXNlcjpwYXNz") == "sent basic ***"
    assert masker.text("basic authentication failed") == "basic authentication failed"
    assert masker.text('{"password": "p\\"q", "n": 1') == '{"password": "***", "n": 1'
    assert masker.text('{"apiKey":12345,"n":1') == '{"apiKey":"***","n":1'
    assert masker.text('{"token": null}') == '{"token": null}'
    assert masker.text('{"password": "cut off') == '{"password": "***"'
    assert masker.text("nothing to see: a=b") == "nothing to see: a=b"
    # Broken JSON with an object under a secret name: its end cannot be found, the rest goes.
    assert masker.text('{"a": 1, "secrets": {"x": "y"}, "b": "c"') == '{"a": 1, "secrets": "***"'
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
    assert masker.body(body) == '{"a": "***", "a": "x"}'


def test_body_nested_too_deeply_is_not_recorded():
    masker = Masker(known_secrets=[SECRET])
    body = "[" * 100_000 + json.dumps(SECRET) + "]" * 100_000

    masked = masker.body(body)

    assert SECRET not in masked
    assert len(masked) < 200


def test_safe_prefix_never_cuts_through_a_known_secret():
    masker = Masker(known_secrets=[SECRET])
    text = "x" * 95 + SECRET + "y" * 500

    prefix, cut = masker.safe_prefix(text, complete=True, limit=100)

    assert cut is True
    assert prefix == "x" * 95
    assert masker.safe_prefix("short", complete=True, limit=100) == ("short", False)
    assert masker.safe_prefix("x" * 100, complete=True, limit=100) == ("x" * 100, False)
    assert masker.safe_prefix("x" * 101, complete=True, limit=100) == ("x" * 100, True)


def test_safe_prefix_of_an_incomplete_text_stops_before_a_possible_secret_start():
    masker = Masker(known_secrets=[SECRET])
    # The text was cut by the caller right inside the secret.
    text = "x" * 50 + SECRET[:10]

    prefix, cut = masker.safe_prefix(text, complete=False, limit=1000)

    assert cut is True
    assert SECRET[:5] not in prefix
    assert prefix == "x" * (len(text) - masker.longest_secret)


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


def test_invalid_secret_paths_and_secrets_are_ignored():
    masker = Masker(
        secret_paths=["", "..", 5, "a.b"],  # type: ignore[list-item]
        known_secrets=[None, 12345678, "short", SECRET],  # type: ignore[list-item]
    )
    assert masker.value({"a": {"b": 1}, "t": SECRET}) == {"a": {"b": MASK}, "t": MASK}


def test_two_adjacent_secrets_are_both_replaced():
    assert mask(SECRET + OTHER, known_secrets=[SECRET, OTHER]) == "******"
