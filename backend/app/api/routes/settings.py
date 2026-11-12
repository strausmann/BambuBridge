"""Runtime settings: ``/api/v1/settings`` (scope ``admin``).

``GET`` lists every setting; a secret is shown only as ``set`` / ``undecryptable``, never
its value. ``PUT`` writes ``{values: {key: value}}`` all-or-nothing and records the acting
user. An unknown key is 422 ``unknown_setting`` (the key is not echoed: the client chose
it); an invalid value is 422 ``invalid_setting_value`` naming the key and the rule, never
the value.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.auth.dependencies import AuthContext, require_scope
from app.db.session import get_session
from app.schemas.problem import ProblemDetail
from app.schemas.settings_api import SettingsUpdate, SettingView
from app.settings_store.registry import InvalidSettingValueError, UnknownSettingError
from app.settings_store.store import SettingsStore

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminDep = Annotated[AuthContext, Depends(require_scope("admin"))]

_PROBLEMS: dict[int | str, dict[str, Any]] = {
    code: {"model": ProblemDetail} for code in (401, 403, 429, 503)
}


def _store(request: Request) -> SettingsStore:
    store: SettingsStore = request.app.state.settings_store
    return store


@router.get("", summary="List settings", responses=_PROBLEMS)
async def list_settings(request: Request, _auth: AdminDep) -> list[SettingView]:
    return [
        SettingView.model_validate(view, from_attributes=True)
        for view in _store(request).describe()
    ]


@router.put(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update settings",
    responses={**_PROBLEMS, 422: {"model": ProblemDetail}},
)
async def update_settings(
    body: SettingsUpdate, request: Request, session: SessionDep, auth: AdminDep
) -> Response:
    # set_many commits itself (all-or-nothing); nothing is committed again here.
    try:
        await _store(request).set_many(session, body.values, updated_by=auth.user_id)
    except UnknownSettingError:
        raise ApiError(
            422,
            "unknown_setting",
            "Unknown setting",
            detail="The request names an unknown setting.",
        ) from None
    except InvalidSettingValueError as exc:
        raise ApiError(
            422, "invalid_setting_value", "Invalid setting value", detail=str(exc)
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
