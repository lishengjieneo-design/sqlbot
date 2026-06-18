"""Appearance settings CRUD (OSS, uses sys_arg via xpack arg_manage)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, Request
from sqlbot_xpack.config.arg_manage import get_group_args, save_group_args
from sqlbot_xpack.config.model import SysArgModel
from sqlbot_xpack.file_utils import SQLBotFileUtils

from common.core.deps import SessionDep

APPEARANCE_PKEYS = {
    "name",
    "slogan",
    "foot",
    "showSlogan",
    "footContent",
    "themeColor",
    "customColor",
    "navigateBg",
    "web",
    "login",
    "bg",
    "navigate",
    "help",
    "showDoc",
    "showAbout",
    "pc_welcome",
    "pc_welcome_desc",
    "mobileLogin",
    "mobileLoginBg",
}

APPEARANCE_FILE_RULES: dict[str, dict[str, Any]] = {
    "web": {"types": [".jpg", ".jpeg", ".png", ".svg"], "size": 200 * 1024},
    "login": {"types": [".jpg", ".jpeg", ".png", ".svg"], "size": 200 * 1024},
    "navigate": {"types": [".jpg", ".jpeg", ".png", ".svg"], "size": 200 * 1024},
    "mobileLogin": {"types": [".jpg", ".jpeg", ".png", ".svg"], "size": 200 * 1024},
    "bg": {"types": [".jpg", ".jpeg", ".png", ".svg"], "size": 5 * 1024 * 1024},
    "mobileLoginBg": {"types": [".jpg", ".jpeg", ".png", ".svg"], "size": 5 * 1024 * 1024},
    "footContent": {"types": [".jpg", ".jpeg", ".png", ".svg", ".html", ".htm"], "size": 5 * 1024 * 1024},
}


def _is_appearance_arg(pkey: str) -> bool:
    if pkey in APPEARANCE_PKEYS:
        return True
    return pkey.startswith("appearance.")


async def get_appearance_ui(session: SessionDep) -> list[SysArgModel]:
    args = await get_group_args(session=session)
    return [item for item in args if _is_appearance_arg(item.pkey)]


async def save_appearance(session: SessionDep, request: Request) -> None:
    form_data = await request.form()
    files = form_data.getlist("files")
    json_text = form_data.get("data")
    if not json_text:
        raise HTTPException(status_code=400, detail="missing data")
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid data json") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="data must be a list")

    sys_args: list[SysArgModel] = []
    for item in payload:
        if not isinstance(item, dict) or "pkey" not in item:
            continue
        pkey = str(item["pkey"])
        if not _is_appearance_arg(pkey):
            continue
        sys_args.append(
            SysArgModel(
                pkey=pkey,
                pval=str(item.get("pval", "")),
                ptype=str(item.get("ptype", "str")),
                sort=int(item.get("sort", 1)),
            )
        )
    if not sys_args:
        raise HTTPException(status_code=400, detail="no appearance fields to save")

    file_mapping: dict[str, str] | None = None
    if files:
        file_mapping = {}
        for file in files:
            origin_file_name = file.filename or ""
            file_name, flag_name = SQLBotFileUtils.split_filename_and_flag(origin_file_name)
            file.filename = file_name
            rule = APPEARANCE_FILE_RULES.get(flag_name)
            if not rule:
                raise HTTPException(status_code=400, detail=f"file flag not allowed: {flag_name}")
            try:
                SQLBotFileUtils.check_file(
                    file=file,
                    file_types=rule["types"],
                    limit_file_size=rule["size"],
                )
            except Exception as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            file_id = await SQLBotFileUtils.upload(file)
            file_mapping[flag_name] = file_id

    await save_group_args(session=session, sys_args=sys_args, file_mapping=file_mapping)
