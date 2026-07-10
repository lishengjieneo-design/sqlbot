"""Chat-related workspace configuration stored in sys_arg."""

from __future__ import annotations

from typing import Any

from sqlbot_xpack.config.arg_manage import get_group_args

from apps.datasource.models.datasource import CoreDatasource
from common.core.deps import SessionDep

DEFAULT_DATASOURCE_PKEY_PREFIX = "chat.default_datasource."


def default_datasource_pkey(oid: int) -> str:
    return f"{DEFAULT_DATASOURCE_PKEY_PREFIX}{oid}"


def parse_default_datasource_oid(pkey: str) -> int | None:
    if not pkey.startswith(DEFAULT_DATASOURCE_PKEY_PREFIX):
        return None
    suffix = pkey[len(DEFAULT_DATASOURCE_PKEY_PREFIX) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


async def get_default_datasource_id(session: SessionDep, oid: int) -> int | None:
    pkey = default_datasource_pkey(oid)
    args = await get_group_args(session=session, flag="chat")
    for item in args:
        if item.pkey == pkey and item.pval:
            try:
                return int(str(item.pval).strip())
            except (TypeError, ValueError):
                return None
    return None


def get_datasource_for_workspace(session: SessionDep, ds_id: int, oid: int) -> CoreDatasource | None:
    ds = session.get(CoreDatasource, ds_id)
    if not ds or int(ds.oid) != int(oid):
        return None
    return ds


async def resolve_default_datasource(session: SessionDep, oid: int) -> dict[str, Any] | None:
    ds_id = await get_default_datasource_id(session, oid)
    if not ds_id:
        return None
    ds = get_datasource_for_workspace(session, ds_id, oid)
    if not ds:
        return None
    return {
        "id": ds.id,
        "name": ds.name,
        "type": ds.type,
        "type_name": ds.type_name,
    }


def validate_default_datasource_args(session: SessionDep, payload: list[dict]) -> None:
    for item in payload:
        if not isinstance(item, dict):
            continue
        pkey = str(item.get("pkey", ""))
        oid = parse_default_datasource_oid(pkey)
        if oid is None:
            continue
        pval = item.get("pval")
        if pval is None or str(pval).strip() == "":
            continue
        try:
            ds_id = int(str(pval).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid default datasource id for workspace {oid}") from exc
        if not get_datasource_for_workspace(session, ds_id, oid):
            raise ValueError(f"default datasource {ds_id} not found in workspace {oid}")
