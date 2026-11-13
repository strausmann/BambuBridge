"""Provider types and instances: ``/api/v1/provider-types`` and ``/api/v1/providers``.

Reading needs ``read``; creating, changing, deleting and testing need ``admin``; running an
action needs ``operate``. A secret never leaves the server: responses show each secret field
as ``{set: bool}``, probe messages and action results are masked with the instance's
secrets. Writes notify the provider manager of every server process from the writing
transaction; no request waits for an instance to stop or start.

Errors name the field and the rule, never a value.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Body, Depends, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.auth.dependencies import AuthContext, require_scope
from app.db.session import get_session
from app.models.provider_instance import ProviderInstance
from app.providers.base import ProbeResult, Provider
from app.providers.config import SecretRebindError, plan_create, plan_update
from app.providers.manager import (
    ActionFailedError,
    ActionTimeoutError,
    ProviderManager,
    ProviderNotRunningError,
    UnknownActionError,
)
from app.providers.registry import ProviderRegistry
from app.providers.schema import ValidationError, secret_fields
from app.repositories import provider_instances as repo
from app.schemas.problem import ProblemDetail
from app.schemas.providers import (
    ActionRequest,
    ActionResult,
    ActionView,
    EventTypeView,
    ProbeResultView,
    ProviderCreate,
    ProviderInstanceView,
    ProviderTest,
    ProviderTypeView,
    ProviderUpdate,
    SecretState,
    StatusView,
)
from app.security.secret_box import SecretBox

router = APIRouter(prefix="/api/v1", tags=["providers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadDep = Annotated[AuthContext, Depends(require_scope("read"))]
OperateDep = Annotated[AuthContext, Depends(require_scope("operate"))]
AdminDep = Annotated[AuthContext, Depends(require_scope("admin"))]

_BASE: dict[int | str, dict[str, Any]] = {
    code: {"model": ProblemDetail} for code in (401, 403, 429, 503)
}


def _problems(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {**_BASE, **{code: {"model": ProblemDetail} for code in codes}}


def _registry(request: Request) -> ProviderRegistry:
    registry: ProviderRegistry = request.app.state.provider_registry
    return registry


def _manager(request: Request) -> ProviderManager:
    manager: ProviderManager = request.app.state.provider_manager
    return manager


def _box(request: Request) -> SecretBox:
    box: SecretBox = request.app.state.secret_box
    return box


def _not_found() -> ApiError:
    return ApiError(404, "provider_not_found", "Provider instance not found")


def _type_not_found() -> ApiError:
    return ApiError(404, "provider_type_not_found", "Provider type not found")


def _invalid_config(exc: ValidationError) -> ApiError:
    return ApiError(
        422, "invalid_provider_config", "Invalid provider configuration", detail=str(exc)
    )


def _secret_required(exc: SecretRebindError) -> ApiError:
    return ApiError(422, "secret_required", "Secret required", detail=str(exc))


def _name_taken() -> ApiError:
    return ApiError(
        409,
        "provider_name_taken",
        "Name taken",
        detail="Another provider instance has this name.",
    )


def _raise_integrity(exc: IntegrityError) -> NoReturn:
    if "uq_provider_instances_name" in str(getattr(exc, "orig", "")):
        raise _name_taken() from None
    raise exc


def _type_view(cls: type[Provider]) -> ProviderTypeView:
    return ProviderTypeView(
        kind=cls.kind,
        type_name=cls.type_name,
        config_schema=cls.config_schema,
        event_types=[
            EventTypeView(
                name=e.name, schema_version=e.schema_version, payload_schema=e.payload_schema
            )
            for e in cls.event_types
        ],
        actions=[ActionView(name=a.name, params_schema=a.params_schema) for a in cls.actions],
    )


def _instance_view(request: Request, row: ProviderInstance) -> ProviderInstanceView:
    cls = _registry(request).find(row.kind, row.type_name)
    stored = set(row.secrets or {})
    fields = secret_fields(cls.config_schema) if cls is not None else tuple(sorted(stored))
    live = _manager(request).status(row.id)
    status_view = (
        StatusView(state=live.state, message=live.message, since=live.since)
        if live is not None
        else StatusView(state=row.status, message=row.status_message, since=row.updated_at)  # type: ignore[arg-type]
    )
    return ProviderInstanceView(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]
        type_name=row.type_name,
        name=row.name,
        enabled=row.enabled,
        # Defensive: a field that became a secret in a later version is never shown.
        config={k: v for k, v in (row.config or {}).items() if k not in set(fields)},
        secrets={f: SecretState(set=f in stored) for f in fields},
        status=status_view,
        created_by=row.created_by,
        updated_by=row.updated_by,
        updated_at=row.updated_at,
    )


def _probe_view(result: ProbeResult) -> ProbeResultView:
    return ProbeResultView(ok=result.ok, message=result.message, duration_ms=result.duration_ms)


async def _row(
    session: AsyncSession, instance_id: uuid.UUID, *, for_update: bool = False
) -> ProviderInstance:
    row = await repo.get(session, instance_id, for_update=for_update)
    if row is None:
        raise _not_found()
    return row


# -- types ----------------------------------------------------------------------------------


@router.get("/provider-types", summary="List provider types", responses=_problems())
async def list_provider_types(request: Request, _auth: ReadDep) -> list[ProviderTypeView]:
    return [_type_view(cls) for cls in _registry(request).all()]


@router.post(
    "/provider-types/{kind}/{type_name}/test",
    summary="Test unsaved values of a new instance",
    responses=_problems(404, 422),
)
async def test_provider_type(
    kind: str,
    type_name: str,
    request: Request,
    _auth: AdminDep,
    body: Annotated[ProviderTest, Body()],
) -> ProbeResultView:
    cls = _registry(request).find(kind, type_name)
    if cls is None:
        raise _type_not_found()
    try:
        plan = plan_create(cls.config_schema, body.config)
    except ValidationError as exc:
        raise _invalid_config(exc) from None
    return _probe_view(await _manager(request).probe(cls, plan.config, plan.set_secrets))


# -- instances ------------------------------------------------------------------------------


@router.get("/providers", summary="List provider instances", responses=_problems())
async def list_providers(
    request: Request, session: SessionDep, _auth: ReadDep
) -> list[ProviderInstanceView]:
    return [_instance_view(request, row) for row in await repo.list_all(session)]


@router.post(
    "/providers",
    status_code=status.HTTP_201_CREATED,
    summary="Create a provider instance",
    responses=_problems(404, 409, 422),
)
async def create_provider(
    body: ProviderCreate, request: Request, session: SessionDep, auth: AdminDep
) -> ProviderInstanceView:
    cls = _registry(request).find(body.kind, body.type_name)
    if cls is None:
        raise _type_not_found()
    try:
        plan = plan_create(cls.config_schema, body.config)
    except ValidationError as exc:
        raise _invalid_config(exc) from None
    try:
        row = await repo.create(
            session,
            _box(request),
            kind=body.kind,
            type_name=body.type_name,
            name=body.name,
            enabled=body.enabled,
            config=plan.config,
            secrets=plan.set_secrets,
            user_id=auth.user_id,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        _raise_integrity(exc)
    return _instance_view(request, row)


@router.get(
    "/providers/{instance_id}", summary="Get a provider instance", responses=_problems(404, 422)
)
async def get_provider(
    instance_id: uuid.UUID, request: Request, session: SessionDep, _auth: ReadDep
) -> ProviderInstanceView:
    return _instance_view(request, await _row(session, instance_id))


@router.patch(
    "/providers/{instance_id}",
    summary="Change a provider instance",
    responses=_problems(404, 409, 422),
)
async def update_provider(
    instance_id: uuid.UUID,
    body: ProviderUpdate,
    request: Request,
    session: SessionDep,
    auth: AdminDep,
) -> ProviderInstanceView:
    row = await _row(session, instance_id, for_update=True)
    cls = _registry(request).find(row.kind, row.type_name)
    try:
        if cls is None:
            # Without the type there is no schema: only name and enabled can change.
            if body.config:
                raise _type_not_found()
            config, to_set, to_clear = dict(row.config), {}, frozenset[str]()
        else:
            plan = plan_update(
                cls.config_schema,
                stored_config=row.config,
                stored_secrets=set(row.secrets or {}),
                form=body.config,
            )
            config, to_set, to_clear = plan.config, plan.set_secrets, plan.clear_secrets
    except ValidationError as exc:
        raise _invalid_config(exc) from None
    except SecretRebindError as exc:
        raise _secret_required(exc) from None
    try:
        updated = await repo.update_instance(
            session,
            _box(request),
            row,
            name=body.name,
            enabled=body.enabled,
            config=config,
            set_secrets=to_set,
            clear_secrets=to_clear,
            user_id=auth.user_id,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        _raise_integrity(exc)
    return _instance_view(request, updated)


@router.delete(
    "/providers/{instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a provider instance",
    responses=_problems(404, 422),
)
async def delete_provider(instance_id: uuid.UUID, session: SessionDep, _auth: AdminDep) -> Response:
    if not await repo.delete(session, instance_id):
        raise _not_found()
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/providers/{instance_id}/test",
    summary="Test a stored instance, optionally with unsaved values",
    responses=_problems(404, 409, 422),
)
async def test_provider(
    instance_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    _auth: AdminDep,
    body: Annotated[ProviderTest | None, Body()] = None,
) -> ProbeResultView:
    row = await _row(session, instance_id)
    # End the transaction: the test may take seconds and must not hold it open. Detached
    # first, so that the rollback does not expire what is read below.
    session.expunge(row)
    await session.rollback()
    cls = _registry(request).find(row.kind, row.type_name)
    if cls is None:
        raise _type_not_found()
    try:
        plan = plan_update(
            cls.config_schema,
            stored_config=row.config,
            stored_secrets=set(row.secrets or {}),
            form=(body or ProviderTest()).config,
        )
    except ValidationError as exc:
        raise _invalid_config(exc) from None
    except SecretRebindError as exc:
        raise _secret_required(exc) from None
    stored, undecryptable = repo.open_secrets(_box(request), row)
    unreadable = sorted(plan.keep_secrets & undecryptable)
    if unreadable:
        raise ApiError(
            409,
            "secret_undecryptable",
            "Stored secret cannot be decrypted",
            detail="Enter these secrets again: " + ", ".join(unreadable),
        )
    secrets = {name: stored[name] for name in plan.keep_secrets if name in stored}
    secrets.update(plan.set_secrets)
    return _probe_view(await _manager(request).probe(cls, plan.config, secrets))


@router.post(
    "/providers/{instance_id}/actions/{name}",
    summary="Run an action of a running instance",
    responses=_problems(404, 409, 422, 502, 504),
)
async def run_provider_action(
    instance_id: uuid.UUID,
    name: str,
    body: ActionRequest,
    request: Request,
    session: SessionDep,
    _auth: OperateDep,
) -> ActionResult:
    await _row(session, instance_id)
    await session.rollback()
    try:
        result = await _manager(request).run_action(instance_id, name, body.params)
    except ProviderNotRunningError:
        raise ApiError(
            409,
            "provider_not_running",
            "Provider instance not running",
            detail="The instance is stopped, failed or restarting.",
        ) from None
    except UnknownActionError:
        raise ApiError(404, "unknown_action", "Unknown action") from None
    except ValidationError as exc:
        raise ApiError(
            422, "invalid_action_params", "Invalid action parameters", detail=str(exc)
        ) from None
    except ActionTimeoutError:
        raise ApiError(504, "action_timeout", "Action timed out") from None
    except ActionFailedError as exc:
        raise ApiError(502, "action_failed", "Action failed", detail=str(exc)) from None
    return ActionResult(result=result)
