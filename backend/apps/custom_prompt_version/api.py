"""API for custom_prompt versioning."""
from fastapi import APIRouter

from apps.custom_prompt_version.crud import (
    get_versioning_state,
    list_versions,
    publish_draft,
    publish_version,
    save_draft,
)
from apps.custom_prompt_version.models import CustomPromptDraftSave
from apps.system.schemas.permission import SqlbotPermission, require_permissions
from common.core.deps import CurrentUser, SessionDep, Trans

router = APIRouter(tags=['CustomPromptVersion'], prefix='/system/custom_prompt')


@router.get('/{prompt_id}/versioning')
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def versioning_state(session: SessionDep, current_user: CurrentUser, prompt_id: int):
    return get_versioning_state(session, prompt_id, current_user.oid)


@router.get('/{prompt_id}/versions')
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def versions(session: SessionDep, current_user: CurrentUser, prompt_id: int):
    return list_versions(session, prompt_id, current_user.oid)


@router.put('/{prompt_id}/draft')
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def put_draft(
    session: SessionDep,
    current_user: CurrentUser,
    trans: Trans,
    prompt_id: int,
    payload: CustomPromptDraftSave,
):
    return save_draft(
        session,
        prompt_id,
        current_user.oid,
        payload,
        created_by=getattr(current_user, 'id', None),
        trans=trans,
    )


@router.post('/{prompt_id}/publish')
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def post_publish(session: SessionDep, current_user: CurrentUser, trans: Trans, prompt_id: int):
    return publish_draft(
        session,
        prompt_id,
        current_user.oid,
        created_by=getattr(current_user, 'id', None),
        trans=trans,
    )


@router.post('/{prompt_id}/versions/{version_id}/publish')
@require_permissions(permission=SqlbotPermission(role=['ws_admin']))
async def post_publish_version(
    session: SessionDep,
    current_user: CurrentUser,
    trans: Trans,
    prompt_id: int,
    version_id: int,
):
    return publish_version(session, prompt_id, version_id, current_user.oid, trans=trans)
