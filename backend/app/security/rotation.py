"""Re-encrypt every stored secret under a new key, in one transaction.

``rotate_secrets`` knows nothing about tables: it runs the given steps (one per table that
holds sealed secrets) inside a single transaction. A step receives a box that opens
tokens sealed with either the old or the new key and seals with the new one, so the run
can be repeated safely after an interruption, and it returns how many secrets it rewrote.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import make_session_factory
from app.security.secret_box import SecretBox, key_id_for

ReencryptStep = Callable[[AsyncSession, SecretBox], Awaitable[int]]


class RotationError(Exception):
    """A secret could not be opened with either key; nothing was changed."""


async def rotate_secrets(
    engine: AsyncEngine, steps: Sequence[ReencryptStep], *, old_key: bytes, new_key: bytes
) -> int:
    """Run all steps in one transaction; return the number of re-encrypted secrets."""
    old_id, new_id = key_id_for(old_key), key_id_for(new_key)
    box = SecretBox({old_id: old_key, new_id: new_key}, new_id)
    total = 0
    async with make_session_factory(engine)() as session, session.begin():
        for step in steps:
            total += await step(session, box)
    return total
