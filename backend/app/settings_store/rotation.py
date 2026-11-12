"""Rotation step for ``app_settings``."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.security.rotation import RotationError
from app.security.secret_box import SealedSecret, SecretBox, UndecryptableSecretError


async def reencrypt_app_settings(session: AsyncSession, box: SecretBox) -> int:
    """Re-seal every ``app_settings.secret_token`` with the box's active key."""
    stmt = select(AppSetting).where(AppSetting.secret_token.is_not(None)).with_for_update()
    count = 0
    for row in (await session.execute(stmt)).scalars():
        if row.secret_token is None or row.secret_key_id is None:
            continue
        try:
            plaintext = box.open(SealedSecret(row.secret_key_id, row.secret_token), aad=row.key)
        except UndecryptableSecretError:
            raise RotationError(
                f"setting {row.key} cannot be decrypted with the old or the new key"
            ) from None
        sealed = box.seal(plaintext, aad=row.key)
        row.secret_token, row.secret_key_id = sealed.token, sealed.key_id
        count += 1
    return count
