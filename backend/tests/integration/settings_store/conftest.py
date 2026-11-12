from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import make_session_factory
from app.security.secret_box import SecretBox, key_id_for, secret_box_from_key
from app.settings_store.store import SettingsStore

KEY_A = b"A" * 32
KEY_B = b"B" * 32
TOKEN = "t" * 40  # a valid sso.trust_token value (>= 32 characters), obviously fake


@pytest.fixture
def box_a() -> SecretBox:
    return secret_box_from_key(KEY_A)


@pytest.fixture
def box_b() -> SecretBox:
    return secret_box_from_key(KEY_B)


@pytest.fixture
def store(box_a: SecretBox) -> SettingsStore:
    return SettingsStore(box_a)


@pytest_asyncio.fixture
async def session2(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """A second, independent session (the first one is ``db_session``)."""
    async with make_session_factory(engine)() as session:
        yield session
        await session.rollback()


__all__ = ["KEY_A", "KEY_B", "TOKEN", "key_id_for"]
