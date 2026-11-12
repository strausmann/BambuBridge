from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import TOKEN_PREFIX
from app.repositories import api_keys as api_keys_repo
from app.repositories import users as users_repo


async def test_create_for_unknown_owner_raises_integrity_error(db_session: AsyncSession):
    # Only a prefix collision is retried; any other constraint violation surfaces.
    with pytest.raises(IntegrityError):
        await api_keys_repo.create(
            db_session, owner_user_id=uuid.uuid4(), name="orphan", scope="read"
        )


async def test_create_gives_up_after_repeated_prefix_collisions(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    owner = await users_repo.get_or_create_admin(db_session)
    fixed = TOKEN_PREFIX + "C" * 40
    monkeypatch.setattr(api_keys_repo, "generate_token", lambda: (fixed, fixed[:16]))
    await api_keys_repo.create(db_session, owner_user_id=owner.id, name="first", scope="read")
    with pytest.raises(api_keys_repo.PrefixCollisionError):
        await api_keys_repo.create(db_session, owner_user_id=owner.id, name="second", scope="read")


async def test_delete_unknown_returns_false(db_session: AsyncSession):
    assert await api_keys_repo.delete(db_session, uuid.uuid4()) is False
