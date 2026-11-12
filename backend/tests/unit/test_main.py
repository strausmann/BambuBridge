from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

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


def test_module_attribute_app_is_built_once(monkeypatch: pytest.MonkeyPatch):
    from app.config import get_settings

    get_settings.cache_clear()
    main_module._default_app.cache_clear()
    monkeypatch.setenv("BAMBUBRIDGE_DATABASE_URL", "postgresql+asyncpg://x/y")
    monkeypatch.setenv(
        "BAMBUBRIDGE_SECRET_KEY",
        base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode(),
    )
    monkeypatch.setenv("BAMBUBRIDGE_PUBLIC_URL", "https://bb.example.com")
    try:
        assert main_module.app is main_module.app  # type: ignore[attr-defined]
    finally:
        get_settings.cache_clear()
        main_module._default_app.cache_clear()


def test_module_attribute_app_without_environment_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.config import get_settings

    get_settings.cache_clear()
    main_module._default_app.cache_clear()
    for name in ("DATABASE_URL", "SECRET_KEY", "PUBLIC_URL"):
        monkeypatch.delenv(f"BAMBUBRIDGE_{name}", raising=False)
    try:
        with pytest.raises(ValidationError):
            main_module.app  # type: ignore[attr-defined]  # noqa: B018
    finally:
        get_settings.cache_clear()
        main_module._default_app.cache_clear()


async def test_lifespan_disposes_the_engine():
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://u:p@db.example.invalid/bb",  # type: ignore[arg-type]
        secret_key=base64.urlsafe_b64encode(b"test-secret-key-0123456789abcdef").decode(),  # type: ignore[arg-type]
        public_url="https://bb.example.com",  # type: ignore[arg-type]
    )
    application = create_app(settings)
    disposed: list[bool] = []
    real_engine = application.state.engine

    class FakeEngine:
        async def dispose(self) -> None:
            disposed.append(True)

    application.state.engine = FakeEngine()
    async with application.router.lifespan_context(application):
        assert disposed == []
    assert disposed == [True]
    await real_engine.dispose()
