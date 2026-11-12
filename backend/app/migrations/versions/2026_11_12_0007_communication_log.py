"""communication_log (partitioned by month)

Written by hand: autogenerate does not know ``PARTITION BY``. As for ``events``, the monthly
partitions ``communication_log_yYYYYmMM`` are created by ``app.events.partitions`` at
startup and once a day, not here.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "communication_log",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("instance_id", sa.UUID(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "request_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("request_body", sa.Text(), nullable=True),
        sa.Column(
            "response_headers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("truncated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "direction IN ('outbound', 'inbound')", name=op.f("ck_communication_log_direction")
        ),
        sa.PrimaryKeyConstraint("id", "occurred_at", name=op.f("pk_communication_log")),
        postgresql_partition_by="RANGE (occurred_at)",
    )
    op.create_index(
        "ix_communication_log_instance_id_occurred_at",
        "communication_log",
        ["instance_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    # Dropping the partitioned table drops its partitions and their indexes with it.
    op.drop_table("communication_log")
