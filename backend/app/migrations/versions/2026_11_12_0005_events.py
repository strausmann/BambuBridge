"""events (partitioned by month) and event_deliveries (outbox)

Written by hand: autogenerate does not know ``PARTITION BY``. The monthly partitions
``events_yYYYYmMM`` are not created here but by ``app.events.partitions`` at startup and
once a day, so the schema does not depend on the day the migration ran.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("source_instance_id", sa.UUID(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("dedup_key", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", "occurred_at", name=op.f("pk_events")),
        postgresql_partition_by="RANGE (occurred_at)",
    )
    op.create_index(
        "ix_events_source_instance_id_occurred_at",
        "events",
        ["source_instance_id", "occurred_at"],
        unique=False,
    )
    op.create_index("ix_events_type_occurred_at", "events", ["type", "occurred_at"], unique=False)
    op.create_table(
        "event_deliveries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("event_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subscriber", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'done', 'failed')", name=op.f("ck_event_deliveries_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_deliveries")),
    )
    op.create_index(
        "ix_event_deliveries_subscriber_status_available_at",
        "event_deliveries",
        ["subscriber", "status", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_deliveries_subscriber_status_available_at", table_name="event_deliveries"
    )
    op.drop_table("event_deliveries")
    # Dropping the partitioned table drops its partitions and their indexes with it.
    op.drop_table("events")
