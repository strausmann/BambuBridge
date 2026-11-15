"""event deliveries: index by event

The event API filters and labels events by the state of their deliveries; this index finds
the deliveries of one event.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_event_deliveries_event",
        "event_deliveries",
        ["event_id", "event_occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_event_deliveries_event", table_name="event_deliveries")
