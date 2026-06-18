"""Open-source authentication / platform config API."""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.system.crud.authentication_manage import (
    LARK_TYPE,
    LARKSUITE_TYPE,
    LOGIN_AUTH_TYPES,
    PLATFORM_TYPES,
    card_dict,
    get_by_type,
    parse_config,
    set_enable,
    set_valid,
    upsert_authentication,
)
from apps.system.platform.lark_client import LarkClient, LarkConfig
from apps.system.platform.larksuite_client import LarksuiteClient, LarksuiteConfig
from apps.system.schemas.permission import SqlbotPermission, require_permissions
from common.core.deps import SessionDep

router = APIRouter(tags=["system_authentication"], prefix="/system/authentication")


class AuthSaveBody(BaseModel):
    id: Optional[int] = None
    type: int
    name: str
    config: str = ""


class AuthEnableBody(BaseModel):
    id: int
    enable: bool


class AuthStatusBody(BaseModel):
    type: int
    name: str = ""
    config: str = ""


def _resolve_config(body: AuthStatusBody, model: Any) -> dict[str, Any]:
    if body.config:
        return parse_config(body.config)
    if model and model.config:
        return parse_config(model.config)
    return {}


@router.get("")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def list_authentications(session: SessionDep) -> list[dict[str, Any]]:
    result = []
    for auth_type, name in LOGIN_AUTH_TYPES:
        model = get_by_type(session, auth_type)
        result.append(card_dict(model, auth_type, name))
    return result


@router.post("")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def create_authentication(session: SessionDep, body: AuthSaveBody) -> dict[str, Any]:
    record_id = body.id if body.id is not None else body.type
    model = upsert_authentication(
        session,
        record_id=record_id,
        auth_type=body.type,
        name=body.name,
        config=body.config,
    )
    return card_dict(model, model.type, model.name)


@router.put("")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def update_authentication(session: SessionDep, body: AuthSaveBody) -> dict[str, Any]:
    record_id = body.id if body.id is not None else body.type
    model = upsert_authentication(
        session,
        record_id=record_id,
        auth_type=body.type,
        name=body.name,
        config=body.config,
    )
    return card_dict(model, model.type, model.name)


@router.patch("/enable")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def patch_enable(session: SessionDep, body: AuthEnableBody) -> dict[str, Any]:
    model = set_enable(session, body.id, body.enable)
    if not model:
        raise HTTPException(status_code=404, detail="authentication record not found")
    if body.enable and not model.valid:
        raise HTTPException(status_code=400, detail="platform config is invalid")
    return card_dict(model, model.type, model.name)


@router.patch("/status")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def patch_status(session: SessionDep, body: AuthStatusBody) -> bool:
    auth_type = body.type
    model = get_by_type(session, auth_type)
    if auth_type == LARK_TYPE:
        return await _validate_lark(session, auth_type, _resolve_config(body, model))
    if auth_type == LARKSUITE_TYPE:
        return await _validate_larksuite(session, auth_type, _resolve_config(body, model))
    if not model or not model.config:
        set_valid(session, auth_type, False)
        return False
    set_valid(session, auth_type, True)
    return True


async def _validate_lark(session: SessionDep, auth_type: int, config_data: dict[str, Any]) -> bool:
    cfg = LarkConfig.from_dict(config_data)
    if not cfg.client_id or not cfg.client_secret:
        set_valid(session, auth_type, False)
        return False
    try:
        await LarkClient(cfg).validate_credentials()
        set_valid(session, auth_type, True)
        return True
    except Exception:
        set_valid(session, auth_type, False)
        return False


async def _validate_larksuite(
    session: SessionDep, auth_type: int, config_data: dict[str, Any]
) -> bool:
    cfg = LarksuiteConfig.from_dict(config_data)
    if not cfg.client_id or not cfg.client_secret:
        set_valid(session, auth_type, False)
        return False
    try:
        await LarksuiteClient(cfg).validate_credentials()
        set_valid(session, auth_type, True)
        return True
    except Exception:
        set_valid(session, auth_type, False)
        return False


@router.get("/platform/status")
async def platform_login_status(session: SessionDep) -> list[dict[str, Any]]:
    """Login page: which platform QR / client logins are enabled."""
    result = []
    for auth_type, name in PLATFORM_TYPES:
        model = get_by_type(session, auth_type)
        enabled = bool(model and model.enable and model.valid)
        result.append({"name": name, "enable": enabled})
    return result
