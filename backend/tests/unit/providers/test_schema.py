"""The JSON-schema subset providers declare their configuration, payloads and parameters in."""

from __future__ import annotations

from typing import Any

import pytest

from app.providers.schema import (
    MAX_STRING_LENGTH,
    SchemaDefinitionError,
    ValidationError,
    binding_fields,
    check_schema,
    secret_fields,
    validate,
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "interval_seconds": {"type": "integer", "minimum": 1, "maximum": 3600, "default": 30},
        "ratio": {"type": "number", "minimum": 0, "maximum": 1},
        "label": {"type": "string", "minLength": 1, "maxLength": 10, "default": "demo"},
        "mode": {"type": "string", "enum": ["a", "b"]},
        "flag": {"type": "boolean"},
        "host": {"type": "string", "x-binds-secrets": True},
        "token": {"type": "string", "x-secret": True, "minLength": 8},
    },
    "required": ["token"],
    "additionalProperties": False,
}


def test_check_schema_accepts_the_subset():
    check_schema(SCHEMA)
    assert secret_fields(SCHEMA) == ("token",)
    assert binding_fields(SCHEMA) == ("host",)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array"},
        {"type": "object", "properties": {"a": {"type": "string"}}},  # additionalProperties
        {
            "type": "object",
            "properties": {"a": {"type": "string", "pattern": ".*"}},
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"a": {"type": "object"}},
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"a": {"type": "integer", "x-secret": True}},
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["b"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"a": {"type": "integer", "default": "x"}},
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "a": {"type": "string", "x-secret": True, "minLength": 8, "default": "x" * 8}
            },
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {
                "a": {"type": "string", "x-secret": True, "minLength": 8, "x-binds-secrets": True}
            },
            "additionalProperties": False,
        },
        {"type": "object", "properties": [], "additionalProperties": False},
        {
            "type": "object",
            "properties": {"a": {"type": "string", "enum": []}},
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {"a": {"type": "string", "maxLength": MAX_STRING_LENGTH + 1}},
            "additionalProperties": False,
        },
    ],
)
def test_check_schema_rejects_everything_else(schema: dict[str, Any]):
    with pytest.raises(SchemaDefinitionError):
        check_schema(schema)


def test_validate_applies_defaults():
    assert validate(SCHEMA, {"token": "12345678"}) == {
        "interval_seconds": 30,
        "label": "demo",
        "token": "12345678",
    }


@pytest.mark.parametrize(
    ("value", "field"),
    [
        ({"token": "12345678", "interval_seconds": 0}, "interval_seconds"),
        ({"token": "12345678", "interval_seconds": 3601}, "interval_seconds"),
        ({"token": "12345678", "interval_seconds": True}, "interval_seconds"),
        ({"token": "12345678", "interval_seconds": 1.5}, "interval_seconds"),
        ({"token": "12345678", "ratio": "1"}, "ratio"),
        ({"token": "12345678", "ratio": 2}, "ratio"),
        ({"token": "12345678", "label": ""}, "label"),
        ({"token": "12345678", "label": "x" * 11}, "label"),
        ({"token": "12345678", "mode": "c"}, "mode"),
        ({"token": "12345678", "flag": 1}, "flag"),
        ({"token": "short"}, "token"),
        ({}, "token"),
        ({"token": "12345678", "unknown": 1}, "unknown"),
    ],
)
def test_validate_rejects_and_names_the_field(value: dict[str, Any], field: str):
    with pytest.raises(ValidationError) as caught:
        validate(SCHEMA, value)
    assert caught.value.field == field
    assert field in str(caught.value)


def test_validation_error_never_quotes_the_value():
    with pytest.raises(ValidationError) as caught:
        validate(SCHEMA, {"token": "s3cr3t!"})
    assert "s3cr3t" not in str(caught.value)


def test_validate_rejects_a_non_object():
    with pytest.raises(ValidationError):
        validate(SCHEMA, ["token"])  # type: ignore[arg-type]


def test_validate_rejects_unstorable_strings():
    with pytest.raises(ValidationError):
        validate(SCHEMA, {"token": "1234\x005678"})


def test_validate_caps_strings_without_max_length():
    with pytest.raises(ValidationError):
        validate(SCHEMA, {"token": "12345678", "host": "h" * (MAX_STRING_LENGTH + 1)})


def test_number_accepts_int():
    assert validate(SCHEMA, {"token": "12345678", "ratio": 1})["ratio"] == 1


@pytest.mark.parametrize("min_length", [None, 0, 7])
def test_a_secret_needs_min_length_of_the_masker(min_length: int | None):
    prop: dict[str, Any] = {"type": "string", "x-secret": True}
    if min_length is not None:
        prop["minLength"] = min_length
    schema = {"type": "object", "properties": {"s": prop}, "additionalProperties": False}
    with pytest.raises(SchemaDefinitionError, match="minLength"):
        check_schema(schema)


@pytest.mark.parametrize("field", ["interval_seconds", "ratio"])
def test_a_huge_integer_is_a_validation_error(field: str):
    with pytest.raises(ValidationError) as caught:
        validate(SCHEMA, {"token": "12345678", field: 10**400})
    assert caught.value.field == field


def test_a_huge_integer_without_bounds_is_fine():
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "additionalProperties": False,
    }
    assert validate(schema, {"n": 10**400}) == {"n": 10**400}


SECRET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"s": {"type": "string", "x-secret": True, "minLength": 8}},
    "additionalProperties": False,
}


@pytest.mark.parametrize(
    "value",
    [
        "  abc1234  ",  # white space around 7 characters
        "​abc1234​",  # zero-width space (Cf)
        "͏abc1234͏",  # combining grapheme joiner (Default_Ignorable, not Cf)
        "﻿abc1234",  # byte order mark in front
        "abc­1234",  # a soft hyphen inside: 7 characters as the masker counts them
    ],
)
def test_a_secret_is_measured_as_the_masker_measures_it(value: str):
    # The masker ignores known secrets shorter than 8 after removing these characters;
    # such a value would be stored in clear in the communication log.
    with pytest.raises(ValidationError) as caught:
        validate(SECRET_SCHEMA, {"s": value})
    assert caught.value.field == "s"
    assert value not in str(caught.value)


def test_a_secret_with_white_space_around_it_is_refused_even_when_long():
    with pytest.raises(ValidationError, match="white space or invisible"):
        validate(SECRET_SCHEMA, {"s": " long-enough-secret "})


def test_a_plain_secret_of_eight_characters_is_fine():
    assert validate(SECRET_SCHEMA, {"s": "abcd1234"}) == {"s": "abcd1234"}


@pytest.mark.parametrize(
    "value",
    [
        "Zq%2F8%3Dxy",  # decodes to "Zq/8=xy": 7 characters
        "+Zq81aud+",  # unquote_plus: " Zq81aud ", 7 without the spaces
        "%20Zq81aud%20",  # unquote: " Zq81aud ", 7 without the spaces
    ],
)
def test_every_form_the_masker_searches_must_be_long_enough(value: str):
    # The masker also searches the percent-decoded forms and drops any shorter than 8;
    # such a form would be stored in clear wherever it appears.
    with pytest.raises(ValidationError) as caught:
        validate(SECRET_SCHEMA, {"s": value})
    assert caught.value.field == "s"
    assert value not in str(caught.value)


def test_a_percent_encoded_secret_with_long_forms_is_fine():
    assert validate(SECRET_SCHEMA, {"s": "pass%2Fword-123"}) == {"s": "pass%2Fword-123"}
