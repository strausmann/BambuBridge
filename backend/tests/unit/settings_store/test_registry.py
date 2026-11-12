from __future__ import annotations

import pytest

from app.settings_store.registry import (
    SETTINGS,
    SSO_USER_HEADERS,
    InvalidSettingValueError,
    SettingDef,
    validate_value,
)
from app.settings_store.store import SettingsStore

URL = SettingDef("x.url", "url", "", "x")
BOOL = SettingDef("x.flag", "bool", False, "x")
TEXT = SettingDef("x.text", "str", "", "x")


def test_registry_matches_the_specified_defaults_and_bounds():
    expected = {
        "sso.user_header": ("choice", "Remote-User", None, None),
        "sso.trust_header": ("str", "X-Pangolin-Token", None, None),
        "sso.trust_token": ("secret", "", 32, None),
        "auth.sign_in_limit_per_minute": ("int", 10, 1, 600),
        "retention.events_days": ("int", 90, 1, 3650),
        "retention.communication_days": ("int", 30, 1, 3650),
        "events.dedup_window_seconds": ("int", 600, 0, 86400),
    }
    assert {k: (d.type, d.default, d.min, d.max) for k, d in SETTINGS.items()} == expected
    assert SSO_USER_HEADERS == ("Remote-User", "Remote-User-Id", "Remote-Email")
    assert SETTINGS["sso.user_header"].choices == SSO_USER_HEADERS


def test_every_default_passes_its_own_validation():
    for d in SETTINGS.values():
        assert validate_value(d, d.default) == d.default


def test_bool():
    assert validate_value(BOOL, True) is True
    for bad in (1, "true", None):
        with pytest.raises(InvalidSettingValueError):
            validate_value(BOOL, bad)


def test_text_is_stripped_and_length_limited():
    assert validate_value(TEXT, "  hello \n") == "hello"
    with pytest.raises(InvalidSettingValueError):
        validate_value(TEXT, "x" * 257)


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        ("", ""),
        ("https://a.example.com/", "https://a.example.com"),
        (" http://h:8080/x/ ", "http://h:8080/x"),
    ],
)
def test_url_accepts_http_and_normalises(raw: str, normalised: str):
    assert validate_value(URL, raw) == normalised


@pytest.mark.parametrize(
    "bad",
    [
        "ftp://a.example.com",
        "https://",
        "https://user:pw@a.example.com",
        "https://a.example.com:notaport",
        "https://a b.example.com",
        "https://a.example.com/" + "x" * 2048,
        "not a url",
        5,
    ],
)
def test_url_rejects_other_schemes_credentials_and_junk(bad: object):
    with pytest.raises(InvalidSettingValueError) as e:
        validate_value(URL, bad)
    assert "pw" not in str(e.value)


def test_secret_may_be_empty_and_is_not_stripped():
    secret = SETTINGS["sso.trust_token"]
    assert validate_value(secret, "") == ""
    assert validate_value(secret, " " + "a" * 40) == " " + "a" * 40
    with pytest.raises(InvalidSettingValueError):
        validate_value(secret, "a" * 4097)


def _url_settings_without_binding(settings: dict[str, SettingDef]) -> list[str]:
    """Names of url settings while the store cannot bind secrets to a URL."""
    if hasattr(SettingsStore, "resolve_probe"):  # the binding lives next to the probe
        return []
    return sorted(k for k, d in settings.items() if d.type == "url")


def test_no_url_setting_exists_before_url_bound_secrets_are_implemented():
    offenders = _url_settings_without_binding(SETTINGS)
    assert not offenders, (
        f"{offenders} added a url setting, but URL-bound secrets and resolve_probe were "
        "deferred (issue #45, PR #80): implement them in the same task, so that a secret "
        "is only ever sent to the URL it was saved with"
    )


def test_the_url_binding_guard_does_fire_for_a_url_setting():
    # Counter-check of the guard above: with a url setting present it reports it.
    with_url = {**SETTINGS, "x.url": URL}
    assert _url_settings_without_binding(with_url) == ["x.url"]
