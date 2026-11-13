"""Turning a form (what the API receives) into a plain configuration and secret changes.

A form is one object with the fields of the provider's ``config_schema``, secret fields
included. Plain fields go to ``provider_instances.config``; secret fields are sealed one by
one into ``provider_instances.secrets`` and never come back.

Rules for a secret field in a form: a non-empty string sets it; ``""`` or leaving it out
keeps the stored secret (a form never shows a secret, so it cannot send it back); ``null``
clears it. A required secret must be set after the change. For a plain field in an update,
``null`` resets it to its default; fields left out keep their stored value.

A stored secret is bound to the fields marked ``"x-binds-secrets": true``: when one of them
changes, every secret that would be kept must be entered again
(:class:`SecretRebindError`), so a stored secret is never sent to a place it was not
entered for. Clearing a secret is always allowed.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.providers.schema import (
    ValidationError,
    binding_fields,
    required_fields,
    secret_fields,
    validate,
)


class SecretRebindError(ValueError):
    """A field the stored secrets are bound to changed; ``fields`` must be entered again."""

    def __init__(self, fields: tuple[str, ...]) -> None:
        super().__init__(
            "enter these secrets again, a field they are bound to changed: " + ", ".join(fields)
        )
        self.fields = fields


@dataclass(frozen=True)
class ConfigPlan:
    """The validated plain configuration and what happens to each secret field."""

    config: dict[str, Any]
    set_secrets: dict[str, str] = field(repr=False)
    clear_secrets: frozenset[str] = frozenset()
    keep_secrets: frozenset[str] = frozenset()


def _secret_value(schema: Mapping[str, Any], name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError(name, "must be a string")
    validate({**schema, "required": []}, {name: value})
    return value


def _secret_changes(
    schema: Mapping[str, Any], form: Mapping[str, Any], stored: Collection[str]
) -> tuple[dict[str, str], frozenset[str], frozenset[str]]:
    to_set: dict[str, str] = {}
    to_clear: set[str] = set()
    to_keep: set[str] = set()
    for name in secret_fields(schema):
        value = form.get(name, "")
        if value is None:
            to_clear.add(name)
        elif value == "":
            if name in stored:
                to_keep.add(name)
        else:
            to_set[name] = _secret_value(schema, name, value)
    for name in required_fields(schema) & set(secret_fields(schema)):
        if name not in to_set and name not in to_keep:
            raise ValidationError(name, "is required")
    return to_set, frozenset(to_clear), frozenset(to_keep)


def plan_create(schema: Mapping[str, Any], form: Mapping[str, Any]) -> ConfigPlan:
    """A new instance: nothing is stored yet."""
    secrets = frozenset(secret_fields(schema))
    config = validate(schema, form, skip=secrets)
    to_set, _, _ = _secret_changes(schema, form, ())
    return ConfigPlan(config, to_set)


def plan_update(
    schema: Mapping[str, Any],
    *,
    stored_config: Mapping[str, Any],
    stored_secrets: Collection[str],
    form: Mapping[str, Any],
) -> ConfigPlan:
    """``form`` merged over the stored instance (see the module text for the rules)."""
    secrets = frozenset(secret_fields(schema))
    known = set(schema.get("properties", {}))
    for name in form:
        if name not in known:
            raise ValidationError(str(name), "is not a known field")
    # Stored fields the schema no longer has are dropped, not reported.
    merged = {k: v for k, v in stored_config.items() if k in known and k not in secrets}
    for name, value in form.items():
        if name in secrets:
            continue
        if value is None:
            merged.pop(name, None)
        else:
            merged[name] = value
    config = validate(schema, merged, skip=secrets)
    to_set, to_clear, to_keep = _secret_changes(schema, form, stored_secrets)
    old = validate_stored(schema, stored_config)
    moved = [name for name in binding_fields(schema) if old.get(name) != config.get(name)]
    if moved and to_keep:
        raise SecretRebindError(tuple(sorted(to_keep)))
    return ConfigPlan(config, to_set, to_clear, to_keep)


def validate_stored(schema: Mapping[str, Any], stored: Mapping[str, Any]) -> dict[str, Any]:
    """The stored plain configuration with defaults, as it was valid when it was saved.

    A field that no longer validates (the provider's schema changed) is left out, so it
    compares as changed.
    """
    secrets = frozenset(secret_fields(schema))
    props = schema.get("properties", {})
    out: dict[str, Any] = {}
    for name, prop in props.items():
        if name in secrets:
            continue
        try:
            out.update(
                validate(
                    {"type": "object", "properties": {name: prop}, "additionalProperties": False},
                    {name: stored[name]} if name in stored else {},
                )
            )
        except ValidationError:
            continue
    return out
