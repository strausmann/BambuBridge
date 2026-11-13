"""Merging a form into a stored instance configuration: plain fields and secret fields."""

from __future__ import annotations

from typing import Any

import pytest

from app.providers.config import SecretRebindError, plan_create, plan_update
from app.providers.schema import ValidationError

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "host": {"type": "string", "default": "a.example", "x-binds-secrets": True},
        "label": {"type": "string", "default": "demo"},
        "token": {"type": "string", "x-secret": True, "minLength": 8},
        "extra": {"type": "string", "x-secret": True, "minLength": 8},
    },
    "required": ["token"],
    "additionalProperties": False,
}


def test_create_splits_plain_and_secret_fields():
    plan = plan_create(SCHEMA, {"label": "x", "token": "tok-123456", "extra": ""})
    assert plan.config == {"host": "a.example", "label": "x"}
    assert plan.set_secrets == {"token": "tok-123456"}
    assert plan.clear_secrets == frozenset()


def test_create_requires_a_required_secret():
    with pytest.raises(ValidationError) as caught:
        plan_create(SCHEMA, {"label": "x", "token": ""})
    assert caught.value.field == "token"


def test_create_rejects_a_non_string_secret():
    with pytest.raises(ValidationError) as caught:
        plan_create(SCHEMA, {"token": 12345678})
    assert caught.value.field == "token"


def test_update_merges_over_the_stored_config_and_keeps_empty_secrets():
    plan = plan_update(
        SCHEMA,
        stored_config={"host": "a.example", "label": "old"},
        stored_secrets={"token"},
        form={"label": "new", "token": ""},
    )
    assert plan.config == {"host": "a.example", "label": "new"}
    assert plan.set_secrets == {}
    assert plan.keep_secrets == frozenset({"token"})


def test_update_absent_secret_is_kept():
    plan = plan_update(
        SCHEMA, stored_config={"label": "old"}, stored_secrets={"token"}, form={"label": "n"}
    )
    assert plan.keep_secrets == frozenset({"token"})


def test_update_null_resets_a_plain_field_and_clears_a_secret():
    plan = plan_update(
        SCHEMA,
        stored_config={"label": "old"},
        stored_secrets={"token", "extra"},
        form={"label": None, "extra": None},
    )
    assert plan.config["label"] == "demo"
    assert plan.clear_secrets == frozenset({"extra"})
    assert plan.keep_secrets == frozenset({"token"})


def test_update_cannot_clear_a_required_secret():
    with pytest.raises(ValidationError) as caught:
        plan_update(SCHEMA, stored_config={}, stored_secrets={"token"}, form={"token": None})
    assert caught.value.field == "token"


def test_update_new_secret_replaces_the_stored_one():
    plan = plan_update(SCHEMA, stored_config={}, stored_secrets={"token"}, form={"token": "n" * 9})
    assert plan.set_secrets == {"token": "n" * 9}
    assert "token" not in plan.keep_secrets


def test_changing_a_binding_field_needs_the_secret_again():
    # Otherwise the stored secret would be sent to a host it was never entered for.
    with pytest.raises(SecretRebindError) as caught:
        plan_update(
            SCHEMA,
            stored_config={"host": "a.example"},
            stored_secrets={"token"},
            form={"host": "evil.example"},
        )
    assert caught.value.fields == ("token",)


def test_changing_a_binding_field_with_new_secrets_is_fine():
    plan = plan_update(
        SCHEMA,
        stored_config={"host": "a.example"},
        stored_secrets={"token"},
        form={"host": "b.example", "token": "t" * 10},
    )
    assert plan.config["host"] == "b.example"


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError) as caught:
        plan_update(SCHEMA, stored_config={}, stored_secrets={"token"}, form={"nope": 1})
    assert caught.value.field == "nope"


def test_stored_fields_no_longer_in_the_schema_are_dropped():
    plan = plan_update(
        SCHEMA, stored_config={"gone": 1, "label": "x"}, stored_secrets={"token"}, form={}
    )
    assert "gone" not in plan.config
