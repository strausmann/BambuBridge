"""ui sessions and app_settings.updated_by

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ui_sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("api_key_id", sa.UUID(), nullable=True),
        sa.Column("identity_provider", sa.Text(), nullable=True),
        sa.Column("identity_subject", sa.Text(), nullable=True),
        sa.Column("identity_binding", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "scope IN ('read', 'operate', 'admin')", name=op.f("ck_ui_sessions_scope")
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["api_keys.id"],
            name=op.f("fk_ui_sessions_api_key_id_api_keys"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ui_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ui_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_ui_sessions_token_hash")),
    )
    op.create_index(op.f("ix_ui_sessions_expires_at"), "ui_sessions", ["expires_at"], unique=False)
    op.create_index(op.f("ix_ui_sessions_user_id"), "ui_sessions", ["user_id"], unique=False)
    op.add_column("app_settings", sa.Column("updated_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_app_settings_updated_by_users"),
        "app_settings",
        "users",
        ["updated_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_app_settings_updated_by_users"), "app_settings", type_="foreignkey")
    op.drop_column("app_settings", "updated_by")
    op.drop_index(op.f("ix_ui_sessions_user_id"), table_name="ui_sessions")
    op.drop_index(op.f("ix_ui_sessions_expires_at"), table_name="ui_sessions")
    op.drop_table("ui_sessions")
