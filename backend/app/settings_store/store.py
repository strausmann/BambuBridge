"""Runtime settings store.

The database is the only source: there is no environment override. Plain values are read
into memory by :meth:`SettingsStore.load`; secrets are opened with the :class:`SecretBox`
and are never returned by :meth:`SettingsStore.describe` (only ``set`` and
``undecryptable``). A secret that cannot be opened (another ``BAMBUBRIDGE_SECRET_KEY``,
damaged token) is reported as such and reads as ``None``; it never raises at load time.

:meth:`SettingsStore.set_many` writes and issues ``pg_notify`` in the same transaction, so
other instances (see :mod:`app.settings_store.listener`) reload after the commit.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.security.secret_box import SealedSecret, SecretBox, UndecryptableSecretError
from app.settings_store.registry import (
    SETTINGS,
    InvalidSettingValueError,
    SettingDef,
    SettingsError,
    SettingType,
    UnknownSettingError,
    allowed_choices,
    validate_value,
)

CHANNEL = "bambubridge_settings"

_log = logging.getLogger(__name__)


def _select_settings() -> Select[AppSetting]:
    """``SELECT`` of setting rows that always reflects the database.

    The caller's session may already hold ``AppSetting`` objects (``session.get``); sessions
    are made with ``expire_on_commit=False`` and the upsert in :meth:`SettingsStore.set_many`
    does not touch ORM objects. Without ``populate_existing`` the query would hand back those
    identity-map objects with their old values.
    """
    return select(AppSetting).execution_options(populate_existing=True)


@dataclass(frozen=True)
class SettingView:
    """What the API may show about a setting. ``value`` is always ``None`` for secrets."""

    key: str
    type: SettingType
    section: str
    value: Any
    default: Any
    set: bool
    undecryptable: bool
    min: int | None
    max: int | None
    choices: tuple[str, ...] | None


class SettingsStore:
    def __init__(self, box: SecretBox) -> None:
        self._box = box
        self._values: dict[str, Any] = {}
        self._secrets: dict[str, str] = {}
        self._secret_present: set[str] = set()
        self._undecryptable: set[str] = set()
        self._subscribers: list[Callable[[set[str]], None]] = []
        # Every change of the in-memory state (full reload, post-commit update of a write)
        # happens under this lock, so two of them can never interleave their reads of the
        # database with their writes to the cache. The listener reloads through
        # :meth:`reload_and_notify`; it does not need a lock of its own.
        self._state_lock = asyncio.Lock()

    # -- subscribers --------------------------------------------------------

    def subscribe(self, callback: Callable[[set[str]], None]) -> None:
        """``callback(changed_keys)`` runs after a change, local or loaded from the database."""
        self._subscribers.append(callback)

    def _notify(self, keys: set[str]) -> None:
        for callback in list(self._subscribers):
            try:
                callback(set(keys))
            except Exception as exc:
                # Type name only: a subscriber's message could carry a setting value.
                _log.error("settings subscriber %r failed (%s)", callback, type(exc).__name__)

    # -- reading ------------------------------------------------------------

    @staticmethod
    def _definition(key: str) -> SettingDef:
        d = SETTINGS.get(key)
        if d is None:
            raise UnknownSettingError("unknown setting key", keys=[key])
        return d

    def get(self, key: str) -> Any:
        """Effective value of a plain setting (stored value or default).

        A list value is returned as a copy, so a caller cannot change the cache or the default.
        """
        d = self._definition(key)
        if d.type == "secret":
            raise TypeError(f"{key} is a secret; read it with secret()")
        value = self._values.get(key, d.default)
        return list(value) if isinstance(value, list) else value

    def secret(self, key: str) -> str | None:
        """Plaintext of a secret; ``None`` if unset, empty or undecryptable."""
        d = self._definition(key)
        if d.type != "secret":
            raise TypeError(f"{key} is not a secret; read it with get()")
        return self._secrets.get(key) or None

    def describe(self) -> list[SettingView]:
        views: list[SettingView] = []
        for key, d in SETTINGS.items():
            is_secret = d.type == "secret"
            views.append(
                SettingView(
                    key=key,
                    type=d.type,
                    section=d.section,
                    value=None if is_secret else self.get(key),
                    default=None if is_secret else d.default,
                    set=key in self._secret_present if is_secret else key in self._values,
                    undecryptable=key in self._undecryptable,
                    min=d.min,
                    max=d.max,
                    choices=allowed_choices(d) if d.type in ("choice", "choices") else None,
                )
            )
        return views

    # -- loading ------------------------------------------------------------

    async def load(self, session: AsyncSession) -> None:
        """Replace the in-memory state with the database content."""
        async with self._state_lock:
            await self._load_all(session)

    def _parse_into(
        self,
        rows: Iterable[AppSetting],
        values: dict[str, Any],
        secrets: dict[str, str],
        present: set[str],
        undecryptable: set[str],
    ) -> None:
        for row in rows:
            d = SETTINGS.get(row.key)
            if d is None:
                continue
            if d.type == "secret":
                if row.secret_token is None or row.secret_key_id is None:
                    continue
                present.add(row.key)
                try:
                    sealed = SealedSecret(row.secret_key_id, row.secret_token)
                    secrets[row.key] = self._box.open(sealed, aad=row.key)
                except UndecryptableSecretError:
                    undecryptable.add(row.key)
                    _log.warning("stored secret %s cannot be decrypted", row.key)
                continue
            if row.value is None:
                continue
            raw = row.value
            if d.type == "choices" and isinstance(raw, list):
                # A kind that is no longer registered (a removed provider) is dropped, not
                # the whole list: the remaining choice stays in force instead of the default.
                allowed = set(allowed_choices(d))
                kept = list(dict.fromkeys(v for v in raw if isinstance(v, str) and v in allowed))
                if kept != raw:
                    _log.warning("dropping unregistered entries of stored setting %s", row.key)
                raw = kept
            try:
                values[row.key] = validate_value(d, raw)
            except SettingsError:
                _log.warning("ignoring invalid stored setting %s", row.key)

    async def _load_all(self, session: AsyncSession) -> None:
        """Caller holds ``_state_lock``."""
        values: dict[str, Any] = {}
        secrets: dict[str, str] = {}
        present: set[str] = set()
        undecryptable: set[str] = set()
        rows = (await session.execute(_select_settings())).scalars().all()
        self._parse_into(rows, values, secrets, present, undecryptable)
        self._values, self._secrets = values, secrets
        self._secret_present, self._undecryptable = present, undecryptable

    async def _load_keys(self, session: AsyncSession, keys: Collection[str]) -> None:
        """Re-read only ``keys`` from the database and install what is stored there.

        Caller holds ``_state_lock``. A key without a row is back at its default.
        """
        values: dict[str, Any] = {}
        secrets: dict[str, str] = {}
        present: set[str] = set()
        undecryptable: set[str] = set()
        stmt = _select_settings().where(AppSetting.key.in_(list(keys)))
        self._parse_into(
            (await session.execute(stmt)).scalars().all(), values, secrets, present, undecryptable
        )
        for key in keys:
            self._values.pop(key, None)
            self._secrets.pop(key, None)
            self._secret_present.discard(key)
            self._undecryptable.discard(key)
        self._values.update(values)
        self._secrets.update(secrets)
        self._secret_present |= present
        self._undecryptable |= undecryptable

    def _snapshot(self) -> dict[str, Any]:
        snap: dict[str, Any] = {}
        for key, d in SETTINGS.items():
            if d.type == "secret":
                snap[key] = (
                    key in self._secret_present,
                    key in self._undecryptable,
                    self._secrets.get(key),
                )
            else:
                snap[key] = self.get(key)
        return snap

    async def reload_and_notify(self, session: AsyncSession) -> set[str]:
        """:meth:`load`, then tell subscribers which settings differ from before."""
        async with self._state_lock:
            before = self._snapshot()
            await self._load_all(session)
            changed = self._changed_since(before)
            if changed:
                self._notify(changed)
        return changed

    def _changed_since(
        self, before: dict[str, Any], keys: Collection[str] | None = None
    ) -> set[str]:
        after = self._snapshot()
        return {
            key for key in (keys if keys is not None else SETTINGS) if before[key] != after[key]
        }

    # -- writing ------------------------------------------------------------

    async def set_many(
        self, session: AsyncSession, values: dict[str, Any], *, updated_by: UUID | None = None
    ) -> None:
        """Validate, write and ``pg_notify`` in one transaction, then commit.

        ``updated_by`` (the acting user, if known) is recorded on every written row.

        ``None`` resets a plain setting to its default; ``None`` or ``""`` clears a secret.
        All-or-nothing up to the commit: an invalid value or a database error before it
        changes nothing. Once the commit has succeeded the write is durable and this method
        does not raise because of what follows (see below).

        After the commit the written keys are re-read from the database and installed under
        the store's state lock, which the listener's reload shares. The database is the truth:
        if another writer committed the same key after us, its value is what ends up in the
        cache, never ours. Reads of the cache between the commit and this update may still see
        the previous value (eventual consistency within one process). A change is announced
        to subscribers once per process, by whichever of this call and the listener's reload
        installs it first. If re-reading fails (for example the connection drops right after
        the commit) the error is logged by type and swallowed: the write stands, and the
        listener's reload, triggered by the NOTIFY of the commit, brings the cache in line.
        The session is left without an open transaction either way.
        """
        unknown = sorted(k for k in values if k not in SETTINGS)
        if unknown:
            raise UnknownSettingError("unknown setting key", keys=unknown)
        clean: dict[str, Any] = {}
        for key, value in values.items():
            d = SETTINGS[key]
            clean[key] = None if value is None else validate_value(d, value)
        if not clean:
            return

        now = datetime.now(UTC)
        sealed: dict[str, SealedSecret] = {}
        to_delete: list[str] = []
        rows: list[dict[str, Any]] = []
        for key, value in clean.items():
            d = SETTINGS[key]
            if value is None or (d.type == "secret" and value == ""):
                to_delete.append(key)
            elif d.type == "secret":
                sealed[key] = self._box.seal(value, aad=key)
                rows.append(
                    {
                        "key": key,
                        "value": None,
                        "secret_token": sealed[key].token,
                        "secret_key_id": sealed[key].key_id,
                        "updated_at": now,
                        "updated_by": updated_by,
                    }
                )
            else:
                rows.append(
                    {
                        "key": key,
                        "value": value,
                        "secret_token": None,
                        "secret_key_id": None,
                        "updated_at": now,
                        "updated_by": updated_by,
                    }
                )

        try:
            if to_delete:
                await session.execute(delete(AppSetting).where(AppSetting.key.in_(to_delete)))
            if rows:
                stmt = insert(AppSetting).values(rows)
                await session.execute(
                    stmt.on_conflict_do_update(
                        index_elements=[AppSetting.key],
                        set_={
                            "value": stmt.excluded.value,
                            "secret_token": stmt.excluded.secret_token,
                            "secret_key_id": stmt.excluded.secret_key_id,
                            "updated_at": stmt.excluded.updated_at,
                            "updated_by": stmt.excluded.updated_by,
                        },
                    )
                )
            # pg_notify is NOTIFY with bound parameters; delivered when the transaction commits.
            await session.execute(
                text("select pg_notify(:channel, :payload)"),
                {"channel": CHANNEL, "payload": json.dumps(sorted(clean))},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        # The database, not the values passed in, is the truth: another writer may have
        # committed the same keys after us. Re-read them under the state lock so that this
        # update cannot interleave with a listener reload or another writer's update.
        # The write is durable now, so nothing below may make this call fail.
        try:
            async with self._state_lock:
                before = self._snapshot()
                await self._load_keys(session, clean)
                changed = self._changed_since(before, clean)
                if changed:
                    self._notify(changed)
        except Exception as exc:  # CancelledError is a BaseException and propagates
            _log.warning(
                "settings written but not re-read (%s); the reload will converge",
                type(exc).__name__,
            )
        finally:
            # End the read transaction: do not leave a pooled connection idle in transaction.
            with contextlib.suppress(Exception):
                await session.rollback()


__all__ = [
    "CHANNEL",
    "InvalidSettingValueError",
    "SettingView",
    "SettingsError",
    "SettingsStore",
    "UnknownSettingError",
]
