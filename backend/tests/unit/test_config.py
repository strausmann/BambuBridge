from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from app.config import Settings

URL = "postgresql+asyncpg://x/y"
GOOD_KEY = base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode()


def _make(**kw: object) -> Settings:
    base: dict[str, object] = {
        "database_url": URL,
        "secret_key": GOOD_KEY,
        "public_url": "https://bb.example.com",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def test_settings_has_exactly_four_env_fields():
    assert set(Settings.model_fields) == {
        "database_url",
        "secret_key",
        "public_url",
        "bootstrap_admin_key",
    }


def test_secret_key_must_decode_to_32_bytes():
    with pytest.raises(ValidationError) as e:
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            database_url=URL,
            secret_key="c2hvcnQ",  # type: ignore[arg-type]
            public_url="https://bb.example.com",  # type: ignore[arg-type]
        )
    assert [err["loc"] for err in e.value.errors()] == [("secret_key",)]


def test_secret_key_must_be_base64():
    with pytest.raises(ValidationError) as e:
        _make(secret_key="!!!not base64!!!")
    assert [err["loc"] for err in e.value.errors()] == [("secret_key",)]


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(GOOD_KEY[:10] + "!!" + GOOD_KEY[10:], id="injected-junk"),
        pytest.param(GOOD_KEY[:10] + "\n" + GOOD_KEY[10:], id="inner-newline"),
        pytest.param(
            base64.b64encode(bytes([0xFB, 0xFF] * 16)).decode(), id="standard-alphabet-plus-slash"
        ),
    ],
)
def test_secret_key_rejects_non_strict_base64url(bad: str):
    with pytest.raises(ValidationError) as e:
        _make(secret_key=bad)
    assert [err["loc"] for err in e.value.errors()] == [("secret_key",)]
    assert bad not in str(e.value)


def test_bootstrap_key_defaults_to_empty_and_needs_32_chars():
    assert _make().bootstrap_admin_key.get_secret_value() == ""
    with pytest.raises(ValidationError) as e:
        _make(bootstrap_admin_key="x" * 31)
    assert [err["loc"] for err in e.value.errors()] == [("bootstrap_admin_key",)]
    assert _make(bootstrap_admin_key="x" * 32).bootstrap_admin_key.get_secret_value() == "x" * 32


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        _make(server_port=1)


def test_get_settings_reads_prefixed_environment(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("BAMBUBRIDGE_DATABASE_URL", URL)
    monkeypatch.setenv("BAMBUBRIDGE_SECRET_KEY", GOOD_KEY)
    monkeypatch.setenv("BAMBUBRIDGE_PUBLIC_URL", "https://bb.example.com")
    try:
        assert get_settings().database_url.get_secret_value() == URL
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_repr_and_str_show_neither_the_database_password_nor_the_dsn():
    dsn = "postgresql+asyncpg://bb_user:s3cr3t-pw-value@db.example.com:5432/bambubridge"
    settings = _make(database_url=dsn, bootstrap_admin_key="b" * 40)
    for text in (repr(settings), str(settings), repr(settings.model_dump())):
        assert "s3cr3t-pw-value" not in text
        assert dsn not in text
        assert GOOD_KEY not in text and "b" * 40 not in text
    assert settings.database_url.get_secret_value() == dsn
