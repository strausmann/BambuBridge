from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_check_has_no_pending_changes(alembic_config: Config):
    command.check(alembic_config)


def test_single_head_is_the_latest_revision(alembic_config: Config):
    script = ScriptDirectory.from_config(alembic_config)
    assert len(script.get_heads()) == 1
    assert script.get_revision("0001").down_revision is None


def test_app_settings_migration_round_trips(alembic_config: Config):
    script = ScriptDirectory.from_config(alembic_config)
    assert script.get_revision("0002").down_revision == "0001"
    command.downgrade(alembic_config, "0001")
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)
