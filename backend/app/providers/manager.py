"""Running provider instances: start, apply a change, stop - each step bounded in time.

:class:`ProviderManager` keeps one provider object per running instance of this process.
``apply(instance_id)`` re-reads the instance and replaces the running object: ``stop()`` on
the old one, then ``start()`` on a new one with the new configuration. Each step gets
``STEP_TIMEOUT_SECONDS`` (10 s); a step that does not finish in time leaves the instance in
state ``error`` with ``timeout during stop`` or ``timeout during start``, and the hung call
is cancelled and left behind (it cannot block anything else).

Nothing in the API waits for a step: writes notify (``NOTIFY bambubridge_providers``), the
listener of every process calls ``apply`` in the background, and reads take the status from
memory. Applies of one instance run one after another; different instances do not wait for
each other.

States the manager sets itself: ``starting`` (during ``start``), ``stopped`` (disabled or
stopped), ``error`` (unknown type, invalid stored configuration, a failed or timed-out step)
and ``needs_secret`` (a stored secret cannot be decrypted - another
``BAMBUBRIDGE_SECRET_KEY`` - or a required one is missing). While an instance runs, its
state is what the provider reports. Every state the manager sets, and the provider's state
right after a start, is also written to ``provider_instances.status`` (for other processes
and after a restart), without a notification. What a provider reports later (for example
``disconnected``) stays in the memory of this process: the API of this process shows it,
the stored column keeps the state from the start.

An instance that ended in ``error`` - a timed-out ``stop`` or ``start``, a failed start -
stays there until its configuration changes. ``start_all`` (at startup and after the
listener reconnects) applies only instances whose stored version differs from the one
applied last, so it does not retry them: a change, or a restart of the server, does.

Everything provider code hands back is treated as untrusted and masked with the instance's
secrets before it is shown or stored: status messages, probe messages, action results and
event payloads. A message too large to mask (``MAX_MASK_INPUT`` bytes) is replaced by a
placeholder; a masked message is capped at ``MAX_STATUS_MESSAGE_LENGTH`` characters.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Collection, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.events.communication import (
    MAX_MASK_INPUT,
    CommunicationRecorder,
    Message,
    masker_for,
    omitted,
)
from app.events.service import EventService
from app.events.validation import make_storable
from app.models.provider_instance import ProviderInstance
from app.providers.base import (
    ProbeResult,
    Provider,
    ProviderContext,
    ProviderStatus,
    ProviderStatusState,
)
from app.providers.listener import ProviderListener
from app.providers.registry import ProviderRegistry
from app.providers.schema import ValidationError, required_fields, secret_fields, validate
from app.repositories import provider_instances as repo
from app.security.masking import secret_paths_from_schema
from app.security.secret_box import SecretBox

STEP_TIMEOUT_SECONDS = 10.0
# Status messages are shown in the API and stored; longer ones are cut (after masking).
MAX_STATUS_MESSAGE_LENGTH = 500

_log = logging.getLogger(__name__)


class ProviderNotRunningError(RuntimeError):
    """The instance is not running in this process (stopped, failed or restarting)."""


class UnknownActionError(LookupError):
    """The provider declares no action of this name."""


class ActionTimeoutError(TimeoutError):
    """The action did not finish within ``STEP_TIMEOUT_SECONDS``."""


class ActionFailedError(RuntimeError):
    """The action raised; ``error_class`` names the exception class."""

    def __init__(self, error_class: str) -> None:
        super().__init__(f"action failed ({error_class})")
        self.error_class = error_class


class InstanceRecorder:
    """The communication log of one instance, with every secret of it bound for masking.

    Wraps :meth:`CommunicationRecorder.record_isolated` (own transaction, masking in a
    worker thread, a database error swallowed): provider code passes what it did and what
    came back, nothing about masking.
    """

    def __init__(
        self,
        recorder: CommunicationRecorder,
        sessions: async_sessionmaker[AsyncSession],
        *,
        instance_id: uuid.UUID,
        secret_paths: Collection[str],
        known_secrets: Collection[str],
    ) -> None:
        self._recorder = recorder
        self._sessions = sessions
        self._instance_id = instance_id
        self._secret_paths = tuple(secret_paths)
        self._known_secrets = tuple(known_secrets)

    async def record_isolated(
        self,
        *,
        method: str,
        target: str,
        status: int | None,
        duration_ms: int,
        request: Message | None = None,
        response: Message | None = None,
        error: str | None = None,
        direction: Literal["outbound", "inbound"] = "outbound",
    ) -> bool:
        """Record one exchange; ``error`` should be an error class name, never a message."""
        return await self._recorder.record_isolated(
            self._sessions,
            instance_id=self._instance_id,
            method=method,
            target=target,
            status=status,
            duration_ms=duration_ms,
            request=request,
            response=response,
            error=error,
            direction=direction,
            secret_paths=self._secret_paths,
            known_secrets=self._known_secrets,
        )


@dataclass
class _Running:
    provider: Provider
    secrets: tuple[str, ...]
    secret_paths: frozenset[str]


def _now() -> datetime:
    return datetime.now(UTC)


def _clean_text(secret_paths: Collection[str], secrets: Collection[str], raw: object) -> str:
    """Provider text made safe to show and store: masked whole, then capped.

    Never cut before masking (a cut inside a secret leaves a part no rule recognises). A
    text larger than ``MAX_MASK_INPUT`` bytes is replaced by the placeholder (fail closed);
    something that is not a string by its type.
    """
    text = raw if isinstance(raw, str) else f"<{type(raw).__name__}>"
    size = len(text.encode("utf-8", "surrogatepass"))
    if size > MAX_MASK_INPUT:
        return omitted(size)
    return _cap(masker_for(secret_paths, secrets).text(make_storable(text)))


def _cap(message: str) -> str:
    """At most ``MAX_STATUS_MESSAGE_LENGTH`` characters, never ending inside a ``***``."""
    if len(message) <= MAX_STATUS_MESSAGE_LENGTH:
        return message
    cut = MAX_STATUS_MESSAGE_LENGTH - 1  # room for the ellipsis
    for back in (1, 2):
        # A mask that starts left of the cut and ends right of it is dropped whole.
        if message[cut - back : cut - back + 3] == "***":
            cut -= back
            break
    return message[:cut] + "…"


class ProviderManager:
    def __init__(
        self,
        engine: AsyncEngine,
        sessions: async_sessionmaker[AsyncSession],
        box: SecretBox,
        registry: ProviderRegistry,
        events: EventService,
        recorder: CommunicationRecorder | None = None,
    ) -> None:
        self._sessions = sessions
        self._box = box
        self._registry = registry
        self._events = events
        self._recorder = recorder or CommunicationRecorder()
        self.step_timeout = STEP_TIMEOUT_SECONDS
        self._running: dict[uuid.UUID, _Running] = {}
        self._states: dict[uuid.UUID, ProviderStatus] = {}
        # The configuration version (``updated_at``) each instance was last applied with.
        self._applied: dict[uuid.UUID, datetime] = {}
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}
        # Per instance: ((reported status, secrets, secret paths), cleaned status).
        self._status_cache: dict[
            uuid.UUID,
            tuple[tuple[ProviderStatus, tuple[str, ...], frozenset[str]], ProviderStatus],
        ] = {}
        # Calls that timed out: cancelled, kept referenced until they end on their own.
        # Abandoned calls are not per-instance state: they leave the set when they end, and
        # dropping one earlier would let a still-running task be garbage collected.
        self._abandoned: set[asyncio.Task[Any]] = set()
        self.listener = ProviderListener(engine, self)

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Start listening; the listener applies every stored instance once connected."""
        await self.listener.start()

    async def stop(self) -> None:
        """Stop listening and stop every running instance (each bounded in time)."""
        await self.listener.stop()
        await asyncio.gather(*(self._shutdown(iid) for iid in list(self._running)))

    async def start_all(self) -> None:
        """Bring every instance in line with the database (start, restart, stop)."""
        async with self._sessions() as session:
            stored = await repo.versions(session)
        changed = [
            iid
            for iid in set(stored) | set(self._running) | set(self._applied)
            if stored.get(iid) is None or self._applied.get(iid) != stored[iid]
        ]
        await asyncio.gather(*(self.apply(iid) for iid in changed))

    # -- status -------------------------------------------------------------

    def status(self, instance_id: uuid.UUID) -> ProviderStatus | None:
        """The live state in this process, or ``None`` if the manager does not know it."""
        running = self._running.get(instance_id)
        if running is not None:
            try:
                reported = running.provider.status()
            except Exception as exc:
                return ProviderStatus("error", f"status failed ({type(exc).__name__})", _now())
            return self._clean(instance_id, running, reported)
        return self._states.get(instance_id)

    def _clean(
        self, instance_id: uuid.UUID, running: _Running, reported: ProviderStatus
    ) -> ProviderStatus:
        """The provider's own message masked with the instance's secrets, then capped.

        Fail closed: a provider may put an error text or a credential into its message,
        and the message is shown by the API and stored in ``provider_instances``. The result
        is cached per instance, reported status and masking inputs (secrets, secret paths),
        so a read of an unchanged status does no masking work on the event loop; a stop or
        start of the instance drops the entry.
        """
        # Keyed by the masking inputs as well: text cleaned with other secrets is never reused.
        key = (reported, running.secrets, running.secret_paths)
        cached = self._status_cache.get(instance_id)
        if cached is not None and cached[0] == key:
            return cached[1]
        raw: object = reported.message  # provider code: do not trust the annotation
        if raw is None:
            cleaned = reported
        else:
            message = _clean_text(running.secret_paths, running.secrets, raw)
            cleaned = ProviderStatus(reported.state, message, reported.since)
        self._status_cache[instance_id] = (key, cleaned)
        return cleaned

    async def _set_state(
        self, instance_id: uuid.UUID, state: ProviderStatusState, message: str | None = None
    ) -> None:
        message = None if message is None else _cap(message)
        self._states[instance_id] = ProviderStatus(state, message, _now())
        await self._persist(instance_id, state, message)

    async def _persist(
        self, instance_id: uuid.UUID, state: ProviderStatusState, message: str | None
    ) -> None:
        # Messages reach this point masked (``status``) or fixed by the manager; capped
        # once more so the column never holds more than the API would show.
        message = None if message is None else _cap(message)
        try:
            async with self._sessions() as session, session.begin():
                await repo.set_status(session, instance_id, state, message)
        except (SQLAlchemyError, OSError) as exc:
            _log.warning("provider status not stored (%s)", type(exc).__name__)

    # -- steps --------------------------------------------------------------

    async def _step(self, call: Coroutine[Any, Any, Any]) -> tuple[bool, Any, asyncio.Task[Any]]:
        """Run ``call`` for at most ``step_timeout``: ``(finished, result or exception, task)``.

        A call that does not finish in time is cancelled and not awaited: a provider that
        ignores the cancellation cannot hold up the manager. It stays referenced in
        ``_abandoned`` until it ends. The task is returned to the caller, never kept in a
        shared attribute: another apply may time out in the meantime.
        """
        task = asyncio.ensure_future(call)
        done, _ = await asyncio.wait({task}, timeout=self.step_timeout)
        if not done:
            task.cancel()
            self._abandoned.add(task)
            task.add_done_callback(self._forget)
            return False, None, task
        if task.cancelled():
            return True, asyncio.CancelledError(), task
        exc = task.exception()
        return True, exc if exc is not None else task.result(), task

    def _forget(self, task: asyncio.Task[Any]) -> None:
        self._abandoned.discard(task)
        if not task.cancelled() and task.exception() is not None:
            _log.warning("abandoned provider call ended with %s", type(task.exception()).__name__)

    async def _stop_running(self, instance_id: uuid.UUID) -> bool:
        """Stop the running object, if any; ``False`` after a timeout."""
        running = self._running.pop(instance_id, None)
        if running is None:
            return True
        self._status_cache.pop(instance_id, None)
        finished, outcome, _ = await self._step(running.provider.stop())
        if not finished:
            await self._set_state(instance_id, "error", "timeout during stop")
            return False
        if isinstance(outcome, BaseException):
            _log.warning("provider %s stop raised %s", instance_id, type(outcome).__name__)
        return True

    async def _shutdown(self, instance_id: uuid.UUID) -> None:
        async with self._lock(instance_id):
            if await self._stop_running(instance_id):
                await self._set_state(instance_id, "stopped")

    def _forget_instance(self, instance_id: uuid.UUID) -> None:
        """Drop everything kept for a deleted instance, also in the provider classes."""
        self._states.pop(instance_id, None)
        self._applied.pop(instance_id, None)
        self._status_cache.pop(instance_id, None)
        # Held by the caller; a later apply makes a new one.
        self._locks.pop(instance_id, None)
        for cls in self._registry.all():
            hook = getattr(cls, "forget_instance", None)
            if callable(hook):
                try:
                    hook(instance_id)
                except Exception as exc:
                    _log.warning("forget_instance of %s failed (%s)", cls, type(exc).__name__)

    def _lock(self, instance_id: uuid.UUID) -> asyncio.Lock:
        return self._locks.setdefault(instance_id, asyncio.Lock())

    # -- apply --------------------------------------------------------------

    async def apply(self, instance_id: uuid.UUID) -> None:
        """Re-read the instance and run it with what is stored now (or stop it)."""
        async with self._lock(instance_id):
            async with self._sessions() as session:
                row = await repo.get(session, instance_id)
            if not await self._stop_running(instance_id):
                if row is not None:
                    self._applied[instance_id] = row.updated_at
                return
            if row is None:
                self._forget_instance(instance_id)
                return
            self._applied[instance_id] = row.updated_at
            await self._start(row)

    async def _start(self, row: ProviderInstance) -> None:
        iid = row.id
        self._status_cache.pop(iid, None)
        if not row.enabled:
            await self._set_state(iid, "stopped")
            return
        cls = self._registry.find(row.kind, row.type_name)
        if cls is None:
            await self._set_state(iid, "error", "provider type is not installed")
            return
        schema = cls.config_schema
        secrets, undecryptable = repo.open_secrets(self._box, row)
        if undecryptable:
            fields = ", ".join(sorted(undecryptable))
            await self._set_state(
                iid, "needs_secret", f"stored secret cannot be decrypted, enter it again: {fields}"
            )
            return
        missing = sorted((required_fields(schema) & set(secret_fields(schema))) - set(secrets))
        if missing:
            await self._set_state(iid, "needs_secret", "secret is missing: " + ", ".join(missing))
            return
        try:
            config = validate(schema, row.config, skip=frozenset(secret_fields(schema)))
        except ValidationError as exc:
            await self._set_state(iid, "error", f"stored configuration is invalid ({exc.field})")
            return
        secrets = {k: v for k, v in secrets.items() if k in secret_fields(schema)}
        paths = secret_paths_from_schema(schema)
        ctx = ProviderContext(
            instance_id=iid,
            config=config,
            secrets=secrets,
            emit=self._emitter(iid, cls, paths, tuple(secrets.values())),
            record=InstanceRecorder(
                self._recorder,
                self._sessions,
                instance_id=iid,
                secret_paths=paths,
                known_secrets=tuple(secrets.values()),
            ),
        )
        await self._set_state(iid, "starting")
        try:
            provider = cls()
        except Exception as exc:
            await self._set_state(iid, "error", f"start failed ({type(exc).__name__})")
            return
        finished, outcome, start_task = await self._step(provider.start(ctx))
        if not finished:
            # It may still finish starting after the cancellation: stop it only once its own
            # start has ended, never while it is still running.
            self._background(self._stop_after(start_task, provider))
            await self._set_state(iid, "error", "timeout during start")
            return
        if isinstance(outcome, BaseException):
            await self._set_state(iid, "error", f"start failed ({type(outcome).__name__})")
            self._background(asyncio.wait_for(provider.stop(), timeout=self.step_timeout))
            return
        self._running[iid] = _Running(provider, tuple(secrets.values()), paths)
        status = self.status(iid)
        if status is not None:
            self._states[iid] = status
            await self._persist(iid, status.state, status.message)

    async def _stop_after(self, start: asyncio.Task[Any], provider: Provider) -> None:
        # Unbounded on purpose: a start that never ends has nothing to stop.
        await asyncio.wait({start})
        await asyncio.wait_for(provider.stop(), timeout=self.step_timeout)

    def _background(self, call: Awaitable[Any]) -> None:
        async def bounded() -> None:
            try:
                await call
            except Exception as exc:
                _log.warning("provider cleanup ended with %s", type(exc).__name__)

        task = asyncio.ensure_future(bounded())
        self._abandoned.add(task)
        task.add_done_callback(self._abandoned.discard)

    def _emitter(
        self,
        instance_id: uuid.UUID,
        cls: type[Provider],
        secret_paths: Collection[str] = (),
        secrets: Collection[str] = (),
    ) -> Any:
        declared = {e.name: e for e in cls.event_types}

        async def emit(
            *,
            type: str,  # noqa: A002  # the name EventService.emit uses
            payload: dict[str, Any],
            schema_version: int,
            dedup_key: str | None = None,
            correlation_id: uuid.UUID | None = None,
        ) -> uuid.UUID | None:
            event_type = declared.get(type)
            if event_type is None or event_type.schema_version != schema_version:
                raise ValueError("the provider does not declare this event type and version")
            try:
                validate(event_type.payload_schema, payload)
            except ValidationError as exc:
                raise ValueError(f"payload does not match the event type ({exc})") from None
            # Events are shown in the web UI and passed on to subscribers: a provider's
            # payload is masked with the instance's secrets like everything else it returns.
            payload = await asyncio.to_thread(
                lambda: masker_for(secret_paths, secrets).value(payload)
            )
            async with self._sessions() as session:
                try:
                    event_id = await self._events.emit(
                        session,
                        type=type,
                        source_instance_id=instance_id,
                        payload=payload,
                        schema_version=schema_version,
                        dedup_key=dedup_key,
                        correlation_id=correlation_id,
                    )
                    await session.commit()
                except BaseException:
                    await session.rollback()
                    raise
            return event_id

        return emit

    # -- probes and actions -------------------------------------------------

    async def probe(
        self, cls: type[Provider], config: dict[str, Any], secrets: dict[str, str]
    ) -> ProbeResult:
        """``test_connection`` on a fresh object, bounded in time; the message is masked."""
        started = time.monotonic()
        try:
            provider = cls()
        except Exception as exc:
            return ProbeResult(False, f"test failed ({type(exc).__name__})", 0)
        finished, outcome, _ = await self._step(provider.test_connection(config, secrets))
        elapsed = int((time.monotonic() - started) * 1000)
        if not finished:
            return ProbeResult(False, "the test did not finish in time", elapsed)
        if isinstance(outcome, BaseException) or not isinstance(outcome, ProbeResult):
            name = type(outcome).__name__
            return ProbeResult(False, f"test failed ({name})", elapsed)
        if (
            not isinstance(outcome.ok, bool)
            or not isinstance(outcome.message, str)
            or isinstance(outcome.duration_ms, bool)
            or not isinstance(outcome.duration_ms, int)
            or not 0 <= outcome.duration_ms <= 2**31 - 1
        ):
            return ProbeResult(False, "test failed (invalid result)", elapsed)
        message = await asyncio.to_thread(
            _clean_text,
            secret_paths_from_schema(cls.config_schema),
            tuple(secrets.values()),
            outcome.message,
        )
        return ProbeResult(outcome.ok, message, outcome.duration_ms)

    async def run_action(
        self, instance_id: uuid.UUID, name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Run a declared action on the running instance; the result is masked."""
        running = self._running.get(instance_id)
        if running is None:
            raise ProviderNotRunningError("the instance is not running")
        action = next((a for a in type(running.provider).actions if a.name == name), None)
        if action is None:
            raise UnknownActionError("no such action")
        checked = validate(action.params_schema, params)
        started = time.monotonic()
        finished, outcome, _ = await self._step(running.provider.run_action(name, checked))
        if not finished:
            raise ActionTimeoutError("the action did not finish in time")
        if isinstance(outcome, BaseException):
            raise ActionFailedError(type(outcome).__name__)
        if not isinstance(outcome, dict):
            raise ActionFailedError("TypeError")
        _log.debug("action %s took %d ms", name, int((time.monotonic() - started) * 1000))
        masker = masker_for(running.secret_paths, running.secrets)
        masked: dict[str, Any] = await asyncio.to_thread(masker.value, outcome)
        return masked
