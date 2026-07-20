from typing import Optional

from fastapi import APIRouter, Query

from apps.swagger.i18n import PLACEHOLDER_PREFIX
from apps.system.schemas.permission import SqlbotPermission, require_permissions
from apps.extra_prompt.crud.extra_prompt import (
    delete_extra_prompt,
    enable_extra_prompt,
    find_enabled_extra_prompt,
    get_extra_prompt,
    page_extra_prompt,
    upsert_extra_prompt,
)
from apps.extra_prompt.crud.version_crud import (
    get_versioning_state,
    list_versions,
    publish_draft,
    publish_version,
    save_draft,
)
from apps.extra_prompt.models.extra_prompt_model import ExtraPromptInfo, ExtraPromptTypeEnum
from apps.extra_prompt.models.version_model import ExtraPromptDraftSave
from common.core.deps import CurrentUser, SessionDep, Trans
from common.audit.models.log_model import OperationType, OperationModules
from common.audit.schemas.logger_decorator import LogConfig, system_log


router = APIRouter(tags=["ExtraPrompt"], prefix="/system/extra_prompt")


@router.get("/page/{current_page}/{page_size}", summary=f"{PLACEHOLDER_PREFIX}get_extra_prompt_page")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def pager(
    session: SessionDep,
    current_user: CurrentUser,
    current_page: int,
    page_size: int,
    description: Optional[str] = Query(None, description="搜索描述(可选)"),
    datasource_id: Optional[int] = Query(None, description="数据源ID(可选)"),
    enabled: Optional[bool] = Query(None, description="启用状态(可选)"),
):
    current_page, page_size, total_count, total_pages, data = page_extra_prompt(
        session=session,
        current_page=current_page,
        page_size=page_size,
        oid=current_user.oid,
        description=description,
        datasource_id=datasource_id,
        enabled=enabled,
        prompt_type=ExtraPromptTypeEnum.GENERATE_SQL.value,
    )
    return {
        "current_page": current_page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "data": data,
    }


@router.get("/active/find", summary=f"{PLACEHOLDER_PREFIX}find_active_extra_prompt")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def find_active(
    session: SessionDep,
    current_user: CurrentUser,
    datasource_id: int = Query(..., description="数据源ID"),
):
    return find_enabled_extra_prompt(
        session=session,
        oid=current_user.oid,
        datasource_id=datasource_id,
        prompt_type=ExtraPromptTypeEnum.GENERATE_SQL.value,
    )


@router.get("/{prompt_id}/versioning")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def versioning_state(session: SessionDep, current_user: CurrentUser, prompt_id: int):
    return get_versioning_state(session, prompt_id, current_user.oid)


@router.get("/{prompt_id}/versions")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def versions(session: SessionDep, current_user: CurrentUser, prompt_id: int):
    return list_versions(session, prompt_id, current_user.oid)


@router.put("/{prompt_id}/draft")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def put_draft(
    session: SessionDep,
    current_user: CurrentUser,
    trans: Trans,
    prompt_id: int,
    payload: ExtraPromptDraftSave,
):
    return save_draft(
        session,
        prompt_id,
        current_user.oid,
        payload,
        created_by=getattr(current_user, "id", None),
        trans=trans,
    )


@router.post("/{prompt_id}/publish")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def post_publish(session: SessionDep, current_user: CurrentUser, trans: Trans, prompt_id: int):
    return publish_draft(
        session,
        prompt_id,
        current_user.oid,
        created_by=getattr(current_user, "id", None),
        trans=trans,
    )


@router.post("/{prompt_id}/versions/{version_id}/publish")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def post_publish_version(
    session: SessionDep,
    current_user: CurrentUser,
    trans: Trans,
    prompt_id: int,
    version_id: int,
):
    return publish_version(session, prompt_id, version_id, current_user.oid, trans=trans)


@router.get("/{id}", summary=f"{PLACEHOLDER_PREFIX}get_extra_prompt_one")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
async def get_one(session: SessionDep, current_user: CurrentUser, id: int):
    res = get_extra_prompt(session=session, prompt_id=id, oid=current_user.oid)
    return res


@router.put("", summary=f"{PLACEHOLDER_PREFIX}create_or_update_extra_prompt")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
@system_log(
    LogConfig(
        operation_type=OperationType.CREATE_OR_UPDATE,
        module=OperationModules.SETTING,
        resource_id_expr="info.id",
        result_id_expr="result_self",
    )
)
async def create_or_update(session: SessionDep, current_user: CurrentUser, trans: Trans, info: ExtraPromptInfo):
    oid = current_user.oid
    return upsert_extra_prompt(session=session, info=info, oid=oid, trans=trans)


@router.delete("", summary=f"{PLACEHOLDER_PREFIX}delete_extra_prompt")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
@system_log(LogConfig(operation_type=OperationType.DELETE, module=OperationModules.SETTING, resource_id_expr="id_list"))
async def delete(session: SessionDep, current_user: CurrentUser, id_list: list[int]):
    delete_extra_prompt(session=session, oid=current_user.oid, ids=id_list)


@router.get("/{id}/enable/{enabled}", summary=f"{PLACEHOLDER_PREFIX}enable_extra_prompt")
@require_permissions(permission=SqlbotPermission(role=["admin"]))
@system_log(
    LogConfig(operation_type=OperationType.UPDATE_STATUS, module=OperationModules.SETTING, resource_id_expr="id")
)
async def enable(session: SessionDep, current_user: CurrentUser, id: int, enabled: bool):
    enable_extra_prompt(session=session, oid=current_user.oid, prompt_id=id, enabled=enabled)
