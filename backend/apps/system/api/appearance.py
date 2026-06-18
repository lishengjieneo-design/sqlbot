"""OSS appearance settings API."""

import os

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import StreamingResponse

from apps.system.crud.appearance_manage import get_appearance_ui, save_appearance
from apps.system.schemas.permission import SqlbotPermission, require_permissions
from common.audit.models.log_model import OperationModules, OperationType
from common.audit.schemas.logger_decorator import LogConfig, system_log
from common.core.deps import SessionDep
from sqlbot_xpack.file_utils import SQLBotFileUtils

router = APIRouter(tags=["system_appearance"], prefix="/system/appearance", include_in_schema=False)


@router.get("/ui")
async def appearance_ui(session: SessionDep):
    return await get_appearance_ui(session)


@router.post("")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
@system_log(LogConfig(operation_type=OperationType.UPDATE, module=OperationModules.THEME))
async def save_appearance_settings(session: SessionDep, request: Request):
    await save_appearance(session, request)
    return None


@router.get("/picture/{file_id}")
async def appearance_picture(file_id: str = Path(..., description="file_id")):
    file_path = SQLBotFileUtils.get_file_path(file_id=file_id)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    lower = file_id.lower()
    if lower.endswith(".svg"):
        media_type = "image/svg+xml"
    elif lower.endswith(".png"):
        media_type = "image/png"
    elif lower.endswith(".gif"):
        media_type = "image/gif"
    else:
        media_type = "image/jpeg"

    def iterfile():
        with open(file_path, mode="rb") as f:
            yield from f

    return StreamingResponse(iterfile(), media_type=media_type)
