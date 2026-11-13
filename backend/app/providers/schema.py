"""The JSON-schema subset of provider configurations, event payloads and action parameters.

A schema is a flat object::

    {"type": "object", "properties": {...}, "required": [...], "additionalProperties": false}

Each property is one of ``string``, ``integer``, ``number`` and ``boolean``, with the
keywords ``title``, ``description``, ``default``, ``enum``, ``minimum``/``maximum`` (numbers)
and ``minLength``/``maxLength`` (strings). Two extensions: ``"x-secret": true`` on a string
marks a secret (it is sealed, never returned, and masked in the communication log; it
must declare ``minLength`` of at least ``MIN_KNOWN_SECRET_LENGTH``, because the masker
cannot find a shorter known value), and
``"x-binds-secrets": true`` marks a field the stored secrets are bound to (a host, an
address): changing it needs the secrets entered again, so a stored secret is never sent
somewhere it was not entered for.

Anything else - nesting, ``pattern``, references - is refused when the provider class is
registered (:func:`check_schema`): what the bridge does not check it does not accept.
:func:`validate` reports the field and the rule, never the value (it may be a secret).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.events.validation import is_storable
from app.security.masking import MIN_KNOWN_SECRET_LENGTH

# A string without its own ``maxLength`` is still bounded by this.
MAX_STRING_LENGTH = 4096

_TYPES = ("string", "integer", "number", "boolean")
_COMMON = frozenset({"type", "title", "description", "default", "enum"})
_EXTRA: dict[str, frozenset[str]] = {
    "string": frozenset({"minLength", "maxLength", "x-secret", "x-binds-secrets"}),
    "integer": frozenset({"minimum", "maximum", "x-binds-secrets"}),
    "number": frozenset({"minimum", "maximum", "x-binds-secrets"}),
    "boolean": frozenset({"x-binds-secrets"}),
}
_TOP = frozenset({"type", "properties", "required", "additionalProperties", "title"})


class SchemaDefinitionError(ValueError):
    """A provider declared a schema outside the supported subset."""


class ValidationError(ValueError):
    """A value does not match its schema. ``field`` names the property (or ``""``)."""

    def __init__(self, field: str, rule: str) -> None:
        super().__init__(f"{field}: {rule}" if field else rule)
        self.field = field
        self.rule = rule


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    # Never through float(): an integer of hundreds of digits overflows it. Python compares
    # int with float exactly, so the limits below need no conversion either.
    return _is_int(value) or (isinstance(value, float) and math.isfinite(value))


def _check_value(prop: Mapping[str, Any], value: object, field: str) -> None:
    """Raise :class:`ValidationError` unless ``value`` fits the property ``prop``."""
    kind = prop["type"]
    if kind == "string":
        if not isinstance(value, str):
            raise ValidationError(field, "must be a string")
        if not is_storable(value):
            raise ValidationError(field, "must not contain NUL or surrogate characters")
        low = prop.get("minLength", 0)
        high = prop.get("maxLength", MAX_STRING_LENGTH)
        if not low <= len(value) <= high:
            raise ValidationError(field, f"must be {low} to {high} characters long")
    elif kind == "integer":
        if not _is_int(value):
            raise ValidationError(field, "must be an integer")
    elif kind == "number":
        if not _is_number(value):
            raise ValidationError(field, "must be a finite number")
    elif not isinstance(value, bool):
        raise ValidationError(field, "must be true or false")
    if kind in ("integer", "number"):
        number: float = value  # type: ignore[assignment]
        if "minimum" in prop and number < prop["minimum"]:
            raise ValidationError(field, f"must be at least {prop['minimum']}")
        if "maximum" in prop and number > prop["maximum"]:
            raise ValidationError(field, f"must be at most {prop['maximum']}")
    if "enum" in prop and value not in prop["enum"]:
        raise ValidationError(field, "must be one of the allowed values")


def check_schema(schema: object) -> None:
    """Raise :class:`SchemaDefinitionError` unless ``schema`` is in the supported subset."""
    if not isinstance(schema, Mapping) or schema.get("type") != "object":
        raise SchemaDefinitionError("a schema must be an object schema")
    if set(schema) - _TOP:
        raise SchemaDefinitionError("unsupported top-level keyword")
    if schema.get("additionalProperties") is not False:
        raise SchemaDefinitionError('a schema must set "additionalProperties": false')
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise SchemaDefinitionError("properties must be an object")
    for name, prop in properties.items():
        _check_property(str(name), prop)
    required = schema.get("required", [])
    if not isinstance(required, list) or any(r not in properties for r in required):
        raise SchemaDefinitionError("required must list declared properties")


def _check_property(name: str, prop: object) -> None:
    def bad(rule: str) -> SchemaDefinitionError:
        return SchemaDefinitionError(f"property {name}: {rule}")

    if not isinstance(prop, Mapping) or prop.get("type") not in _TYPES:
        raise bad("type must be one of " + ", ".join(_TYPES))
    kind = prop["type"]
    unknown = set(prop) - _COMMON - _EXTRA[kind]
    if unknown:
        raise bad("unsupported keyword " + ", ".join(sorted(unknown)))
    for flag in ("x-secret", "x-binds-secrets"):
        if flag in prop and not isinstance(prop[flag], bool):
            raise bad(f"{flag} must be true or false")
    if prop.get("x-secret") and prop.get("x-binds-secrets"):
        raise bad("a secret cannot be a binding field")
    if prop.get("x-secret") and ("default" in prop or "enum" in prop):
        raise bad("a secret has no default and no enum")
    if prop.get("x-secret") and not (
        _is_int(prop.get("minLength")) and prop["minLength"] >= MIN_KNOWN_SECRET_LENGTH
    ):
        # A shorter secret is not masked by value, so it would show in the log as it is.
        raise bad(f"a secret needs minLength of at least {MIN_KNOWN_SECRET_LENGTH}")
    for limit in ("minimum", "maximum"):
        if limit in prop and not _is_number(prop[limit]):
            raise bad(f"{limit} must be a number")
    for limit in ("minLength", "maxLength"):
        if limit in prop and not (_is_int(prop[limit]) and 0 <= prop[limit] <= MAX_STRING_LENGTH):
            raise bad(f"{limit} must be an integer from 0 to {MAX_STRING_LENGTH}")
    if "enum" in prop:
        if not isinstance(prop["enum"], list) or not prop["enum"]:
            raise bad("enum must be a non-empty list")
        for item in prop["enum"]:
            try:
                _check_value({**prop, "enum": [item]}, item, name)
            except ValidationError:
                raise bad("enum values must match the type") from None
    if "default" in prop:
        try:
            _check_value(prop, prop["default"], name)
        except ValidationError:
            raise bad("default must be valid") from None


def _properties(schema: Mapping[str, Any]) -> Mapping[str, Mapping[str, Any]]:
    props: Mapping[str, Mapping[str, Any]] = schema.get("properties", {})
    return props


def secret_fields(schema: Mapping[str, Any]) -> tuple[str, ...]:
    """Names of the properties marked ``"x-secret": true``, in schema order."""
    return tuple(n for n, p in _properties(schema).items() if p.get("x-secret") is True)


def binding_fields(schema: Mapping[str, Any]) -> tuple[str, ...]:
    """Names of the properties marked ``"x-binds-secrets": true``."""
    return tuple(n for n, p in _properties(schema).items() if p.get("x-binds-secrets") is True)


def required_fields(schema: Mapping[str, Any]) -> frozenset[str]:
    required: list[str] = schema.get("required", [])
    return frozenset(required)


def validate(
    schema: Mapping[str, Any], value: Mapping[str, Any], *, skip: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """``value`` checked against ``schema``, with defaults filled in.

    Fields in ``skip`` are neither checked nor required (the caller handles them, as the
    secrets of a configuration).
    """
    if not isinstance(value, Mapping):
        raise ValidationError("", "must be an object")
    props = _properties(schema)
    for name in value:
        if name not in props:
            raise ValidationError(str(name), "is not a known field")
    out: dict[str, Any] = {}
    for name, prop in props.items():
        if name in skip:
            continue
        if name in value:
            _check_value(prop, value[name], name)
            out[name] = value[name]
        elif "default" in prop:
            out[name] = prop["default"]
        elif name in required_fields(schema):
            raise ValidationError(name, "is required")
    return out
