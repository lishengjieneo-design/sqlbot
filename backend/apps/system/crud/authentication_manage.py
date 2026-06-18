"""CRUD for sys_authentication (platform + login auth configs)."""

from __future__ import annotations

import json
from typing import Any, Optional

from sqlmodel import Session, select

from apps.system.models.system_model import AuthenticationModel
from common.utils.time import get_timestamp

LARK_TYPE = 8
LARKSUITE_TYPE = 9
LARKSUITE_NAME = "larksuite"

PLATFORM_TYPES: list[tuple[int, str]] = [
    (6, "wecom"),
    (7, "dingtalk"),
    (8, "lark"),
    (9, LARKSUITE_NAME),
]

LOGIN_AUTH_TYPES: list[tuple[int, str]] = [
    (1, "cas"),
    (2, "oidc"),
    (3, "ldap"),
    (4, "oauth2"),
]


def parse_config(config: Optional[str]) -> dict[str, Any]:
    if not config:
        return {}
    try:
        return json.loads(config)
    except json.JSONDecodeError:
        return {}


def get_by_type(session: Session, auth_type: int) -> Optional[AuthenticationModel]:
    stmt = select(AuthenticationModel).where(AuthenticationModel.type == auth_type)
    return session.exec(stmt).first()


def get_by_id(session: Session, record_id: int) -> Optional[AuthenticationModel]:
    return session.get(AuthenticationModel, record_id)


def upsert_authentication(
    session: Session,
    *,
    record_id: int,
    auth_type: int,
    name: str,
    config: str,
) -> AuthenticationModel:
    existing = session.get(AuthenticationModel, record_id)
    if existing:
        if existing.config != config:
            existing.valid = False
            existing.enable = False
        existing.name = name
        existing.type = auth_type
        existing.config = config
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    model = AuthenticationModel(
        id=record_id,
        name=name,
        type=auth_type,
        config=config,
        enable=False,
        valid=False,
        create_time=get_timestamp(),
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


def set_enable(session: Session, record_id: int, enable: bool) -> Optional[AuthenticationModel]:
    model = session.get(AuthenticationModel, record_id)
    if not model:
        model = get_by_type(session, record_id)
    if not model:
        return None
    model.enable = enable
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


def set_valid(session: Session, record_id: int, valid: bool) -> Optional[AuthenticationModel]:
    model = session.get(AuthenticationModel, record_id)
    if not model:
        model = get_by_type(session, record_id)
    if not model:
        return None
    model.valid = valid
    session.add(model)
    session.commit()
    session.refresh(model)
    return model


def card_dict(model: Optional[AuthenticationModel], auth_type: int, name: str) -> dict[str, Any]:
    if not model:
        return {
            "id": None,
            "type": auth_type,
            "name": name,
            "config": {},
            "enable": False,
            "valid": False,
        }
    return {
        "id": model.id,
        "type": model.type,
        "name": model.name,
        "config": parse_config(model.config),
        "enable": model.enable,
        "valid": model.valid,
    }
