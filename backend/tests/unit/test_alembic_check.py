from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_check_has_no_pending_changes(alembic_config: Config):
    command.check(alembic_config)


def test_single_head_is_the_baseline(alembic_config: Config):
    script = ScriptDirectory.from_config(alembic_config)
    assert script.get_heads() == ["0001"]
    assert script.get_revision("0001").down_revision is None
