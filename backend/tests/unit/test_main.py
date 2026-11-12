from __future__ import annotations

import base64

import pytest

import app.main as main_module


def test_module_attribute_app_builds_from_environment(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("BAMBUBRIDGE_DATABASE_URL", "postgresql+asyncpg://x/y")
    monkeypatch.setenv(
        "BAMBUBRIDGE_SECRET_KEY",
        base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode(),
    )
    monkeypatch.setenv("BAMBUBRIDGE_PUBLIC_URL", "https://bb.example.com")
    try:
        assert main_module.app.title == "BambuBridge"  # type: ignore[attr-defined]
    finally:
        get_settings.cache_clear()


def test_unknown_module_attribute_raises():
    with pytest.raises(AttributeError):
        main_module.nonexistent  # type: ignore[attr-defined]  # noqa: B018
