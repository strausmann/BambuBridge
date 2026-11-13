"""``provider_instances``: reads, writes and the change notification.

Every write of the configuration (create, update, delete) sends
``NOTIFY bambubridge_providers, '<instance id>'`` in the writing transaction, so the
provider manager of every server process applies it after the commit (see
:mod:`app.providers.listener`). Status updates do not notify: they are what the manager
itself reports.

Secrets are sealed per field with ``provider_instances:<id>:<field>`` as associated data:
a sealed value copied to another instance or another field does not open.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_instance import ProviderInstance
from app.security.secret_box import SealedSecret, SecretBox, UndecryptableSecretError

PROVIDERS_CHANNEL = "bambubridge_providers"

_log = logging.getLogger(__name__)


def secret_aad(instance_id: uuid.UUID, field: str) -> str:
    return f"provider_instances:{instance_id}:{field}"


def seal(box: SecretBox, instance_id: uuid.UUID, field: str, plaintext: str) -> dict[str, str]:
    sealed = box.seal(plaintext, aad=secret_aad(instance_id, field))
    return {"key_id": sealed.key_id, "token": sealed.token}


def open_secrets(box: SecretBox, row: ProviderInstance) -> tuple[dict[str, str], set[str]]:
    """``(plaintexts, undecryptable field names)`` of the stored secrets; never raises."""
    opened: dict[str, str] = {}
    undecryptable: set[str] = set()
    for field, sealed in (row.secrets or {}).items():
        try:
            if not isinstance(sealed, Mapping):
                raise UndecryptableSecretError("malformed")
            opened[field] = box.open(
                SealedSecret(str(sealed.get("key_id")), str(sealed.get("token"))),
                aad=secret_aad(row.id, field),
            )
        except UndecryptableSecretError:
            undecryptable.add(field)
    if undecryptable:
        _log.warning(
            "provider instance %s: %d stored secrets cannot be decrypted",
            row.id,
            len(undecryptable),
        )
    return opened, undecryptable


async def notify(session: AsyncSession, instance_id: uuid.UUID) -> None:
    """Queue the change notification; delivered when the caller's transaction commits."""
    await session.execute(
        text("select pg_notify(:channel, :payload)"),
        {"channel": PROVIDERS_CHANNEL, "payload": str(instance_id)},
    )


async def create(
    session: AsyncSession,
    box: SecretBox,
    *,
    kind: str,
    type_name: str,
    name: str,
    enabled: bool,
    config: dict[str, Any],
    secrets: Mapping[str, str],
    user_id: uuid.UUID | None,
) -> ProviderInstance:
    """Insert and notify in the caller's transaction (never commits)."""
    instance_id = uuid.uuid4()
    row = ProviderInstance(
        id=instance_id,
        kind=kind,
        type_name=type_name,
        name=name,
        enabled=enabled,
        config=config,
        secrets={f: seal(box, instance_id, f, value) for f, value in secrets.items()},
        status="stopped",
        status_message=None,
        created_by=user_id,
        updated_by=user_id,
        updated_at=func.clock_timestamp(),
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await notify(session, instance_id)
    return row


async def get(
    session: AsyncSession, instance_id: uuid.UUID, *, for_update: bool = False
) -> ProviderInstance | None:
    stmt = (
        select(ProviderInstance)
        .where(ProviderInstance.id == instance_id)
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[ProviderInstance]:
    stmt = select(ProviderInstance).order_by(ProviderInstance.name)
    return list((await session.execute(stmt.execution_options(populate_existing=True))).scalars())


async def versions(session: AsyncSession) -> dict[uuid.UUID, datetime]:
    """``updated_at`` of every instance: what changes with every configuration write."""
    rows = await session.execute(select(ProviderInstance.id, ProviderInstance.updated_at))
    return dict(rows.tuples().all())


async def update_instance(
    session: AsyncSession,
    box: SecretBox,
    row: ProviderInstance,
    *,
    name: str | None,
    enabled: bool | None,
    config: dict[str, Any],
    set_secrets: Mapping[str, str],
    clear_secrets: Collection[str],
    user_id: uuid.UUID | None,
) -> ProviderInstance:
    """Write the change and notify in the caller's transaction (never commits)."""
    secrets = {f: v for f, v in (row.secrets or {}).items() if f not in clear_secrets}
    for field, value in set_secrets.items():
        secrets[field] = seal(box, row.id, field, value)
    values: dict[str, Any] = {
        "config": config,
        "secrets": secrets,
        "updated_by": user_id,
        "updated_at": func.clock_timestamp(),
    }
    if name is not None:
        values["name"] = name
    if enabled is not None:
        values["enabled"] = enabled
    await session.execute(
        update(ProviderInstance).where(ProviderInstance.id == row.id).values(**values)
    )
    await notify(session, row.id)
    refreshed = await get(session, row.id)
    if refreshed is None:  # pragma: no cover - the caller holds the row lock
        raise LookupError("the provider instance vanished while locked")
    return refreshed


async def delete(session: AsyncSession, instance_id: uuid.UUID) -> bool:
    """Delete and notify in the caller's transaction; ``False`` if there was no row."""
    result = await session.execute(
        sql_delete(ProviderInstance)
        .where(ProviderInstance.id == instance_id)
        .returning(ProviderInstance.id)
    )
    if result.scalar_one_or_none() is None:
        return False
    await notify(session, instance_id)
    return True


async def set_status(
    session: AsyncSession, instance_id: uuid.UUID, state: str, message: str | None
) -> None:
    """Record the reported state; touches neither ``updated_at`` nor the notification."""
    await session.execute(
        update(ProviderInstance)
        .where(ProviderInstance.id == instance_id)
        .values(status=state, status_message=message)
    )
