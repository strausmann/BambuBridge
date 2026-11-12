"""API tokens: creation (hash only), lookup by prefix, bootstrap state."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete as sql_delete
from sqlalchemy import exists, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.scopes import Scope
from app.auth.tokens import generate_token, hash_token_async
from app.models.api_key import ApiKey
from app.models.user import User

_PREFIX_CONSTRAINT = "uq_api_keys_prefix"
_MAX_ATTEMPTS = 5
# Transaction-scoped advisory lock: one bootstrap at a time ("bb" + 2).
_BOOTSTRAP_LOCK_KEY = 0x6262_0002


class PrefixCollisionError(RuntimeError):
    """No unique prefix after several attempts (practically impossible: 62^9 prefixes)."""


async def create(
    session: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    name: str,
    scope: Scope,
    note: str | None = None,
    expires_at: datetime | None = None,
    rate_limit_per_minute: int = 60,
) -> tuple[ApiKey, str]:
    """Create a token and return ``(row, plaintext)``. The caller commits.

    The plaintext is returned once and never stored; a prefix collision is retried with a
    fresh token inside a savepoint.
    """
    for _ in range(_MAX_ATTEMPTS):
        plaintext, prefix = generate_token()
        key = ApiKey(
            owner_user_id=owner_user_id,
            prefix=prefix,
            hash=await hash_token_async(plaintext),
            name=name,
            note=note,
            scope=scope,
            expires_at=expires_at,
            rate_limit_per_minute=rate_limit_per_minute,
        )
        try:
            async with session.begin_nested():
                session.add(key)
                await session.flush()
        except IntegrityError as exc:
            if _PREFIX_CONSTRAINT not in str(exc.orig):
                raise
            continue
        await session.refresh(key)  # load server defaults (id, created_at, enabled)
        return key, plaintext
    raise PrefixCollisionError("could not generate a unique token prefix")


async def get_by_prefix(session: AsyncSession, prefix: str) -> tuple[ApiKey, User] | None:
    """Return the token with this prefix together with its owner."""
    row = (
        await session.execute(
            select(ApiKey, User)
            .join(User, User.id == ApiKey.owner_user_id)
            .where(ApiKey.prefix == prefix)
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def get(session: AsyncSession, key_id: uuid.UUID) -> ApiKey | None:
    return await session.get(ApiKey, key_id, populate_existing=True)


async def list_all(session: AsyncSession) -> Sequence[ApiKey]:
    return (await session.scalars(select(ApiKey).order_by(ApiKey.created_at, ApiKey.id))).all()


async def delete(session: AsyncSession, key_id: uuid.UUID) -> bool:
    """Delete a token; ``False`` if it did not exist. The caller commits."""
    result = await session.execute(
        sql_delete(ApiKey).where(ApiKey.id == key_id).returning(ApiKey.id)
    )
    return result.first() is not None


# last_used_at is written at most once per this interval per token.
LAST_USED_RESOLUTION_SECONDS = 60


async def touch_last_used(session: AsyncSession, key_id: uuid.UUID) -> bool:
    """Set ``last_used_at`` to now unless it was set within the last minute.

    Returns whether a row was written. The caller commits.
    """
    stale = func.now() - text(f"interval '{LAST_USED_RESOLUTION_SECONDS} seconds'")
    result = await session.execute(
        update(ApiKey)
        .where(ApiKey.id == key_id)
        .where(or_(ApiKey.last_used_at.is_(None), ApiKey.last_used_at < stale))
        .values(last_used_at=func.now())
        .returning(ApiKey.id)
    )
    return result.first() is not None


async def lock_bootstrap(session: AsyncSession) -> None:
    """Serialise bootstrap requests until the end of the transaction."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _BOOTSTRAP_LOCK_KEY})


async def usable_admin_token_exists(session: AsyncSession) -> bool:
    """Whether an enabled, unexpired token with scope ``admin`` exists (bootstrap closed).

    The owner is deliberately not considered: whether a disabled or demoted admin user can
    get a new token is decided by the bootstrap route, which refuses to issue dead tokens.
    """
    query = select(
        exists()
        .where(ApiKey.scope == "admin", ApiKey.enabled.is_(True))
        .where(or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > func.now()))
    )
    return bool(await session.scalar(query))
