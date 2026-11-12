"""event store hardening: dedup index, delivery lease, claim index

- ``events``: partial index for the duplicate lookup (source, type, key, time).
- ``event_deliveries``: lease columns ``claimed_by`` / ``claimed_until``, and the index that
  hands deliveries out in order replaces the one on ``available_at``.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # On the partitioned table: PostgreSQL creates the index on every existing partition
    # and on each one created later.
    op.create_index(
        "ix_events_dedup",
        "events",
        ["source_instance_id", "type", "dedup_key", "occurred_at"],
        unique=False,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
    op.add_column("event_deliveries", sa.Column("claimed_by", sa.Text(), nullable=True))
    op.add_column(
        "event_deliveries", sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_event_deliveries_lease"),
        "event_deliveries",
        "(claimed_by IS NULL) = (claimed_until IS NULL)",
    )
    op.drop_index(
        "ix_event_deliveries_subscriber_status_available_at", table_name="event_deliveries"
    )
    op.create_index(
        "ix_event_deliveries_claim",
        "event_deliveries",
        ["subscriber", "status", "event_occurred_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_event_deliveries_claim", table_name="event_deliveries")
    op.create_index(
        "ix_event_deliveries_subscriber_status_available_at",
        "event_deliveries",
        ["subscriber", "status", "available_at"],
        unique=False,
    )
    op.drop_constraint(op.f("ck_event_deliveries_lease"), "event_deliveries", type_="check")
    op.drop_column("event_deliveries", "claimed_until")
    op.drop_column("event_deliveries", "claimed_by")
    op.drop_index("ix_events_dedup", table_name="events")
