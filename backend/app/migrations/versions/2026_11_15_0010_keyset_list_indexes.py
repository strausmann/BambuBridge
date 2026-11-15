"""keyset list indexes: events and communication_log by (occurred_at, id)

The event and communication APIs list newest first by ``(occurred_at, id)``; the primary
keys are ``(id, occurred_at)`` and cannot serve that order, so an unfiltered page would sort
the whole table. Created on the partitioned parents: PostgreSQL creates the index on every
existing partition and on each one created later.

Locking: building the index takes a SHARE lock on the parent and on each partition while it
is built, which blocks writes (events, communication log) for that time. ``CREATE INDEX
CONCURRENTLY`` is not possible on a partitioned parent. On a large installation run the
upgrade at a quiet moment.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_events_occurred_at_id", "events", ["occurred_at", "id"], unique=False)
    op.create_index(
        "ix_communication_log_occurred_at_id",
        "communication_log",
        ["occurred_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_communication_log_occurred_at_id", table_name="communication_log")
    op.drop_index("ix_events_occurred_at_id", table_name="events")
