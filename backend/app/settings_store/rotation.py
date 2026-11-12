"""Rotation step for ``app_settings``."""

from __future__ import annotations

import json

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.security.rotation import RotationError
from app.security.secret_box import SealedSecret, SecretBox, UndecryptableSecretError
from app.settings_store.store import CHANNEL


async def reencrypt_app_settings(session: AsyncSession, box: SecretBox) -> int:
    """Re-seal every ``app_settings.secret_token`` with the box's active key."""
    stmt = select(AppSetting).where(AppSetting.secret_token.is_not(None)).with_for_update()
    rotated: list[str] = []
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
        rotated.append(row.key)
    if rotated:
        # Delivered on commit, never when a later step rolls the transaction back. Servers
        # that are still running should have been stopped before rotating (their key is
        # stale); this makes any that were not reload and report the secrets undecryptable
        # instead of silently holding plaintext sealed under a key that no longer exists.
        await session.execute(
            text("select pg_notify(:channel, :payload)"),
            {"channel": CHANNEL, "payload": json.dumps(sorted(rotated))},
        )
    return len(rotated)
