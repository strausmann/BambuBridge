"""Rotation step for ``provider_instances.secrets``."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_instance import ProviderInstance
from app.repositories import provider_instances as repo
from app.security.rotation import RotationError
from app.security.secret_box import SealedSecret, SecretBox, UndecryptableSecretError


async def reencrypt_provider_instances(session: AsyncSession, box: SecretBox) -> int:
    """Re-seal every secret of every instance with the box's active key."""
    stmt = select(ProviderInstance).order_by(ProviderInstance.id).with_for_update()
    total = 0
    for row in (await session.execute(stmt)).scalars():
        if not row.secrets:
            continue
        resealed: dict[str, dict[str, str]] = {}
        for field, sealed in row.secrets.items():
            try:
                if not isinstance(sealed, Mapping):
                    raise UndecryptableSecretError("malformed")
                plaintext = box.open(
                    SealedSecret(str(sealed.get("key_id")), str(sealed.get("token"))),
                    aad=repo.secret_aad(row.id, field),
                )
            except UndecryptableSecretError:
                raise RotationError(
                    f"a secret of provider instance {row.id} cannot be decrypted with the old "
                    "or the new key"
                ) from None
            resealed[field] = repo.seal(box, row.id, field, plaintext)
        row.secrets = resealed
        total += len(resealed)
        # Delivered on commit only: a running server re-reads the instance (and reports
        # needs_secret if its own key is the old one) instead of using stale plaintext.
        await repo.notify(session, row.id)
    return total
