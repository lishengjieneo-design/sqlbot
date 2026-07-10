from fastapi import APIRouter, HTTPException, Request
from sqlbot_xpack.config.model import SysArgModel

from apps.system.crud.chat_config import resolve_default_datasource, validate_default_datasource_args
from apps.system.crud.parameter_manage import get_groups, get_parameter_args, save_parameter_args
from apps.system.schemas.permission import SqlbotPermission, require_permissions
from common.core.deps import CurrentUser, SessionDep

router = APIRouter(tags=["system/parameter"], prefix="/system/parameter", include_in_schema=False)
from common.audit.models.log_model import OperationType, OperationModules
from common.audit.schemas.logger_decorator import LogConfig, system_log

@router.get("/login")
async def get_login_args(session: SessionDep) -> list[SysArgModel]:
    return await get_groups(session, "login")


@router.get("")
@require_permissions(permission=SqlbotPermission(role=['admin']))
async def get_args(session: SessionDep) -> list[SysArgModel]:
    return await get_parameter_args(session)


@router.post("", )
@require_permissions(permission=SqlbotPermission(role=['admin']))
@system_log(LogConfig(operation_type=OperationType.UPDATE, module=OperationModules.PARAMS_SETTING))
async def save_args(session: SessionDep, request: Request):
    form_data = await request.form()
    json_text = form_data.get("data")
    if json_text:
        import json

        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid data json") from exc
        if isinstance(payload, list):
            try:
                validate_default_datasource_args(session, payload)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await save_parameter_args(session=session, request=request)


@router.get("/chat")
async def get_chat_args(session: SessionDep) -> list[SysArgModel]:
    return await get_groups(session, "chat")


@router.get("/chat/default-datasource")
async def get_chat_default_datasource(session: SessionDep, current_user: CurrentUser):
    oid = current_user.oid if current_user.oid is not None else 1
    return await resolve_default_datasource(session, oid)
