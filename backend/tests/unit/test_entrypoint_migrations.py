from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import app.entrypoint as entrypoint


def test_run_upgrades_database_before_serving(monkeypatch: pytest.MonkeyPatch):
    calls = MagicMock()
    monkeypatch.setattr(entrypoint.command, "upgrade", calls.upgrade)
    monkeypatch.setattr(entrypoint.uvicorn, "run", calls.serve)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.1.2.3")

    entrypoint.run()

    names = [c[0] for c in calls.mock_calls]
    assert names == ["upgrade", "serve"]
    config, revision = calls.upgrade.call_args.args
    assert revision == "head"
    assert Path(config.config_file_name).name == "alembic.ini"
    assert Path(config.config_file_name).is_file()
    assert calls.serve.call_args.kwargs["forwarded_allow_ips"] == "10.1.2.3"


def test_run_does_not_serve_when_migration_fails(monkeypatch: pytest.MonkeyPatch):
    serve = MagicMock()
    monkeypatch.setattr(entrypoint.command, "upgrade", MagicMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(entrypoint.uvicorn, "run", serve)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.1.2.3")

    with pytest.raises(RuntimeError, match="boom"):
        entrypoint.run()

    serve.assert_not_called()


def test_run_refuses_bad_proxy_setting_before_migrating(monkeypatch: pytest.MonkeyPatch):
    upgrade = MagicMock()
    monkeypatch.setattr(entrypoint.command, "upgrade", upgrade)
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")

    with pytest.raises(SystemExit):
        entrypoint.run()

    upgrade.assert_not_called()
