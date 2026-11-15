"""Indexes for the newest-first keyset lists of events and the communication log."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.session import make_session_factory
from app.events.partitions import ensure_partitions

# Every index of a table with its key columns in order.
INDEX_COLUMNS = text(
    """
    SELECT i.relname AS name,
           array_agg(a.attname ORDER BY k.ord) AS columns
    FROM pg_index x
    JOIN pg_class i ON i.oid = x.indexrelid
    JOIN pg_class t ON t.oid = x.indrelid
    CROSS JOIN LATERAL unnest(x.indkey) WITH ORDINALITY AS k(attnum, ord)
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
    WHERE t.relname = :table
    GROUP BY i.relname
    """
)
PARTITIONS = text(
    """
    SELECT c.relname FROM pg_inherits h
    JOIN pg_class c ON c.oid = h.inhrelid
    JOIN pg_class p ON p.oid = h.inhparent
    WHERE p.relname = :parent
    """
)


@pytest.mark.parametrize(
    ("table", "index"),
    [
        ("events", "ix_events_occurred_at_id"),
        ("communication_log", "ix_communication_log_occurred_at_id"),
    ],
)
async def test_keyset_index_on_parent_and_every_partition(
    engine: AsyncEngine, table: str, index: str
):
    async with make_session_factory(engine)() as session:
        await ensure_partitions(session, datetime.now(UTC))
        await session.commit()
        parent = {
            r.name: list(r.columns) for r in await session.execute(INDEX_COLUMNS, {"table": table})
        }
        assert parent.get(index) == ["occurred_at", "id"], parent
        partitions = list(await session.scalars(PARTITIONS, {"parent": table}))
        assert partitions, "no partitions"
        for partition in partitions:
            found = [
                list(r.columns) for r in await session.execute(INDEX_COLUMNS, {"table": partition})
            ]
            # PostgreSQL creates the partition's own copy of the parent index.
            assert ["occurred_at", "id"] in found, (partition, found)
