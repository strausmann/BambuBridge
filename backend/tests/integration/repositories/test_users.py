from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.session import make_session_factory
from app.models.user import User
from app.models.user_identity import UserIdentity
from app.repositories import users as users_repo


async def _user_count(engine: AsyncEngine) -> int:
    async with make_session_factory(engine)() as session:
        return int(await session.scalar(select(func.count()).select_from(User)) or 0)


async def test_get_or_create_admin_is_idempotent(engine: AsyncEngine):
    factory = make_session_factory(engine)
    async with factory() as session:
        first = await users_repo.get_or_create_admin(session)
        await session.commit()
    async with factory() as session:
        second = await users_repo.get_or_create_admin(session)
        await session.commit()
    assert first.id == second.id
    assert (second.display_name, second.role, second.enabled) == ("admin", "admin", True)
    assert second.created_at is not None
    assert second.updated_at is not None
    assert await _user_count(engine) == 1


async def test_get_or_create_admin_concurrently_creates_one(engine: AsyncEngine):
    factory = make_session_factory(engine)

    async def once() -> object:
        async with factory() as session:
            user = await users_repo.get_or_create_admin(session)
            await session.commit()
            return user.id

    ids = await asyncio.gather(*(once() for _ in range(5)))
    assert len(set(ids)) == 1
    assert await _user_count(engine) == 1


async def test_user_can_link_many_identities_across_providers(engine: AsyncEngine):
    factory = make_session_factory(engine)
    async with factory() as session:
        admin = await users_repo.get_or_create_admin(session)
        other = User(display_name="other", role="read")
        session.add(other)
        await session.flush()
        identities = [
            ("pangolin_header", "alice"),
            ("pangolin_header", "alice@work"),
            ("oidc", "sub-1"),
            ("oidc", "sub-2"),
        ]
        for provider, subject in identities:
            await users_repo.link_identity(session, admin.id, provider, subject)
        await session.commit()
        admin_id, other_id = admin.id, other.id

    async with factory() as session:
        for provider, subject in identities:
            user = await users_repo.resolve_identity(session, provider, subject)
            assert user is not None
            assert user.id == admin_id
        assert await users_repo.resolve_identity(session, "oidc", "unknown") is None
        assert await users_repo.resolve_identity(session, "other", "alice") is None

    async with factory() as session:
        with pytest.raises(IntegrityError):
            await users_repo.link_identity(session, other_id, "oidc", "sub-1")
        await session.rollback()

    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(UserIdentity))
    assert count == 4


async def test_identities_are_deleted_with_their_user(engine: AsyncEngine):
    factory = make_session_factory(engine)
    async with factory() as session:
        user = User(display_name="temp", role="operate")
        session.add(user)
        await session.flush()
        await users_repo.link_identity(session, user.id, "oidc", "temp")
        await session.commit()
        await session.delete(user)
        await session.commit()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(UserIdentity)) == 0


async def test_role_check_constraint(db_session: AsyncSession):
    db_session.add(User(display_name="bad", role="root"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_get_or_create_admin_finds_admin_by_name_after_role_change(engine: AsyncEngine):
    factory = make_session_factory(engine)
    async with factory() as session:
        first = await users_repo.get_or_create_admin(session)
        first.role = "read"
        await session.commit()
    async with factory() as session:
        again = await users_repo.get_or_create_admin(session)
        await session.commit()
    assert again.id == first.id
    assert again.role == "read"  # not repaired silently, not duplicated
    async with factory() as session:
        names = (await session.scalars(select(User.display_name))).all()
    assert names == ["admin"]
