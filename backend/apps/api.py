from fastapi import APIRouter

from apps.chat.api import chat
from apps.dashboard.api import dashboard_api
from apps.data_training.api import data_training
from apps.datasource.api import datasource, table_relation, recommended_problem
from apps.mcp import mcp
from apps.system.api import (
    login,
    user,
    aimodel,
    workspace,
    assistant,
    parameter,
    apikey,
    variable_api,
    appearance,
    platform,
    authentication_platform,
)
from apps.terminology.api import terminology
from apps.extra_prompt.api import extra_prompt
from apps.custom_prompt_version.api import router as custom_prompt_version_router
from apps.settings.api import base


api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(user.router)
api_router.include_router(workspace.router)
api_router.include_router(assistant.router)
api_router.include_router(aimodel.router)
api_router.include_router(base.router)
api_router.include_router(terminology.router)
api_router.include_router(extra_prompt.router)
# Register before xpack so versioning paths take precedence over generic /{id}
api_router.include_router(custom_prompt_version_router)
api_router.include_router(data_training.router)
api_router.include_router(datasource.router)
api_router.include_router(chat.router)
api_router.include_router(dashboard_api.router)
api_router.include_router(mcp.router)
api_router.include_router(table_relation.router)
api_router.include_router(parameter.router)
api_router.include_router(apikey.router)

api_router.include_router(recommended_problem.router)

api_router.include_router(variable_api.router)
api_router.include_router(appearance.router)
# Registered before xpack so OSS handlers take precedence over duplicate paths.
api_router.include_router(authentication_platform.router)
api_router.include_router(platform.router)

from sqlbot_xpack.audit.api import audit_api

api_router.include_router(audit_api.router)
