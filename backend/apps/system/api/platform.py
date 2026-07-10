"""Open-source platform integration API (Larksuite SSO)."""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Body, HTTPException, Path
from pydantic import BaseModel, Field

from apps.system.crud.authentication_manage import (
    LARKSUITE_TYPE,
    PLATFORM_TYPES,
    card_dict,
    get_by_type,
    parse_config,
)
from apps.system.crud.larksuite_sso import (
    LARKSUITE_ORIGIN,
    get_larksuite_config,
    is_larksuite_in_app_state,
    resolve_user_for_larksuite,
    user_to_token_dto,
    validate_larksuite_state,
)
from apps.system.platform.larksuite_client import LarksuiteClient, LarksuiteConfig
from apps.system.schemas.permission import SqlbotPermission, require_permissions
from common.core.config import settings
from common.core.deps import SessionDep, Trans
from common.core.security import create_access_token

router = APIRouter(tags=["system_platform"], prefix="/system/platform")


class PlatformSaveBody(BaseModel):
    id: Optional[int] = None
    type: int
    name: str
    config: str = ""


class PlatformEnableBody(BaseModel):
    id: int
    enable: bool


class PlatformStatusBody(BaseModel):
    type: int
    name: str = ""
    config: str = ""


class PlatformSyncBody(BaseModel):
    origin: int = LARKSUITE_TYPE
    user_ids: list[str] = Field(default_factory=list)


@router.get("")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def list_platforms(session: SessionDep) -> list[dict[str, Any]]:
    result = []
    for auth_type, name in PLATFORM_TYPES:
        model = get_by_type(session, auth_type)
        result.append(card_dict(model, auth_type, name))
    return result


@router.get("/client/{origin}")
async def get_platform_client(
    session: SessionDep,
    origin: int = Path(..., description="platform type, 9=larksuite"),
) -> dict[str, Any]:
    if origin != LARKSUITE_TYPE:
        raise HTTPException(status_code=404, detail="platform client not implemented")
    model = get_by_type(session, LARKSUITE_TYPE)
    if not model or not model.enable:
        raise HTTPException(status_code=400, detail="larksuite platform disabled")
    cfg = LarksuiteConfig.from_dict(parse_config(model.config))
    if not cfg.client_id:
        raise HTTPException(status_code=400, detail="larksuite client_id missing")
    redirect = cfg.redirect_uri or settings.FRONTEND_HOST
    return {
        "client_id": cfg.client_id,
        "redirect_uri": redirect,
    }


@router.post("/sso/{origin}")
async def platform_sso(
    session: SessionDep,
    trans: Trans,
    origin: int = Path(...),
    body: dict[str, Any] = Body(default_factory=dict),
) -> dict[str, Any]:
    if origin != LARKSUITE_TYPE:
        raise HTTPException(status_code=404, detail="platform sso not implemented")
    code = body.get("code")
    state = body.get("state")
    redirect_uri = body.get("redirect_uri") or body.get("redirectUri")
    if not code:
        raise HTTPException(status_code=400, detail=trans("i18n_miss_args", key="code"))
    try:
        validate_larksuite_state(state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    auth_model, cfg = get_larksuite_config(session)
    if not auth_model.enable:
        raise HTTPException(status_code=400, detail="larksuite platform disabled")

    in_app = is_larksuite_in_app_state(state)
    if in_app:
        redirect_uri = ""
    else:
        redirect_uri = unquote(str(redirect_uri or "")).strip()
        if not redirect_uri:
            redirect_uri = cfg.redirect_uri or settings.FRONTEND_HOST

    client = LarksuiteClient(cfg)
    try:
        lark_user, token_data = await client.login_with_code(
            code,
            redirect_uri,
            in_app=in_app,
        )
        user = await resolve_user_for_larksuite(session, lark_user, cfg, trans)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if user.status != 1:
        raise HTTPException(
            status_code=400,
            detail=trans("i18n_login.user_disable", msg=trans("i18n_concat_admin")),
        )
    if not user.oid or user.oid == 0:
        raise HTTPException(
            status_code=400,
            detail=trans("i18n_login.no_associated_ws", msg=trans("i18n_concat_admin")),
        )

    user_dto = user_to_token_dto(user)
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(user_dto.to_dict(), expires_delta=expires)
    exp_ts = int((datetime.now(timezone.utc) + expires).timestamp())
    platform_info = {
        "flag": "larksuite",
        "origin": LARKSUITE_ORIGIN,
        "data": token_data.get("open_id") or lark_user.open_id,
    }
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "platform_info": platform_info,
        "exp": exp_ts,
    }


@router.post("/user/sync")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def sync_platform_users(
    session: SessionDep,
    trans: Trans,
    body: PlatformSyncBody,
) -> dict[str, Any]:
    if body.origin != LARKSUITE_TYPE:
        raise HTTPException(status_code=501, detail="sync not implemented for this platform")
    raise HTTPException(
        status_code=501,
        detail="Larksuite user directory sync will be added in a follow-up; use auto_create_user or manual user bind for now.",
    )
