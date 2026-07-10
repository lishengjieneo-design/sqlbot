"""Larksuite SSO: user lookup, bind, auto-create."""

from __future__ import annotations

import re
from typing import Optional

from sqlmodel import Session, select

from apps.system.crud.authentication_manage import LARKSUITE_TYPE, get_by_type, parse_config
from apps.system.models.system_model import AuthenticationModel, UserWsModel, WorkspaceModel
from apps.system.models.user import UserModel, UserPlatformModel
from apps.system.platform.larksuite_client import LarksuiteClient, LarksuiteConfig, LarksuiteUserInfo
from apps.system.schemas.system_schema import BaseUserDTO
from common.core.security import default_md5_pwd
from common.utils.locale import I18n

LARKSUITE_ORIGIN = 9
STATE_PREFIX = "fit2cloud-larksuite-"


def validate_larksuite_state(state: Optional[str]) -> None:
    if not state or STATE_PREFIX not in state:
        raise ValueError("invalid larksuite oauth state")


def is_larksuite_in_app_state(state: Optional[str]) -> bool:
    """True for Lark client / mini-program web-view (requestAuthCode) login."""
    return bool(state and f"{STATE_PREFIX}client" in state)


def get_larksuite_config(session: Session) -> tuple[AuthenticationModel, LarksuiteConfig]:
    model = get_by_type(session, LARKSUITE_TYPE)
    if not model or not model.config:
        raise ValueError("larksuite not configured")
    cfg = LarksuiteConfig.from_dict(parse_config(model.config))
    if not cfg.client_id or not cfg.client_secret:
        raise ValueError("larksuite client_id or client_secret missing")
    return model, cfg


def find_user_by_platform_uid(session: Session, platform_uid: str) -> Optional[UserModel]:
    stmt = (
        select(UserModel)
        .join(UserPlatformModel, UserPlatformModel.uid == UserModel.id)
        .where(
            UserPlatformModel.origin == LARKSUITE_ORIGIN,
            UserPlatformModel.platform_uid == platform_uid,
        )
    )
    return session.exec(stmt).first()


def _sanitize_account_part(open_id: str) -> str:
    part = re.sub(r"[^a-zA-Z0-9_]", "_", open_id)[:48]
    return part or "user"


def _default_email(open_id: str) -> str:
    return f"lark_{_sanitize_account_part(open_id)}@larksuite.oauth"


def create_larksuite_user(
    session: Session,
    lark_user: LarksuiteUserInfo,
    default_oid: int,
) -> UserModel:
    account = f"lark_{_sanitize_account_part(lark_user.open_id)}"
    existing = session.exec(select(UserModel).where(UserModel.account == account)).first()
    if existing:
        return existing
    name = lark_user.name or lark_user.en_name or account
    email = lark_user.email if lark_user.email and "@" in lark_user.email else _default_email(lark_user.open_id)
    oid = default_oid
    if oid:
        ws = session.get(WorkspaceModel, oid)
        if not ws:
            oid = 0
    user = UserModel(
        account=account,
        name=name[:255],
        email=email[:255],
        password=default_md5_pwd(),
        status=1,
        origin=LARKSUITE_ORIGIN,
        oid=oid,
        language="zh-CN",
    )
    session.add(user)
    session.flush()
    if oid:
        session.add(UserWsModel(uid=user.id, oid=oid, weight=0))
    session.add(
        UserPlatformModel(
            uid=user.id,
            origin=LARKSUITE_ORIGIN,
            platform_uid=lark_user.open_id,
        )
    )
    session.commit()
    session.refresh(user)
    return user


def bind_platform_user(session: Session, user: UserModel, platform_uid: str) -> None:
    link = session.exec(
        select(UserPlatformModel).where(
            UserPlatformModel.uid == user.id,
            UserPlatformModel.origin == LARKSUITE_ORIGIN,
        )
    ).first()
    if link:
        link.platform_uid = platform_uid
        session.add(link)
    else:
        session.add(
            UserPlatformModel(
                uid=user.id,
                origin=LARKSUITE_ORIGIN,
                platform_uid=platform_uid,
            )
        )
    session.commit()


async def resolve_user_for_larksuite(
    session: Session,
    lark_user: LarksuiteUserInfo,
    cfg: LarksuiteConfig,
    trans: I18n,
) -> UserModel:
    user = find_user_by_platform_uid(session, lark_user.open_id)
    if user:
        return user
    if not cfg.auto_create_user:
        raise ValueError(trans("i18n_login.no_platform_user"))
    if not cfg.default_oid:
        raise ValueError(trans("i18n_login.no_associated_ws", msg=trans("i18n_concat_admin")))
    return create_larksuite_user(session, lark_user, cfg.default_oid)


def user_to_token_dto(user: UserModel) -> BaseUserDTO:
    return BaseUserDTO.model_validate(user.model_dump())
