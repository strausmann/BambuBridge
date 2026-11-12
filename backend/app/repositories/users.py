"""Users and their external identities."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_identity import UserIdentity

ADMIN_DISPLAY_NAME = "admin"
# Transaction-scoped advisory lock: serialises concurrent first-time creation of the admin.
_ADMIN_LOCK_KEY = 0x6262_0001  # "bb" + 1


async def get_or_create_admin(session: AsyncSession) -> User:
    """Return the single user ``admin`` (role ``admin``), creating it on first use.

    Idempotent, also under concurrency (advisory lock until the caller's commit). The
    caller commits.
    """
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ADMIN_LOCK_KEY})
    user = await session.scalar(
        select(User)
        .where(User.display_name == ADMIN_DISPLAY_NAME, User.role == "admin")
        .order_by(User.created_at, User.id)
        .limit(1)
    )
    if user is not None:
        return user
    user = User(display_name=ADMIN_DISPLAY_NAME, role="admin")
    session.add(user)
    await session.flush()
    await session.refresh(user)  # load server defaults (id, timestamps, enabled)
    return user


async def resolve_identity(session: AsyncSession, provider: str, subject: str) -> User | None:
    """Return the user an external identity is linked to, if any."""
    return await session.scalar(
        select(User)
        .join(UserIdentity, UserIdentity.user_id == User.id)
        .where(UserIdentity.provider == provider, UserIdentity.subject == subject)
    )


async def link_identity(
    session: AsyncSession, user_id: uuid.UUID, provider: str, subject: str
) -> UserIdentity:
    """Link an external identity to a user (``IntegrityError`` if it belongs to someone).

    A user may hold any number of identities, also several from one provider. The caller
    commits.
    """
    identity = UserIdentity(user_id=user_id, provider=provider, subject=subject)
    session.add(identity)
    await session.flush()
    return identity
