"""app_settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column(
            "value", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
        sa.Column("secret_token", sa.Text(), nullable=True),
        sa.Column("secret_key_id", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(secret_token IS NULL) = (secret_key_id IS NULL)",
            name=op.f("ck_app_settings_secret_pair"),
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
