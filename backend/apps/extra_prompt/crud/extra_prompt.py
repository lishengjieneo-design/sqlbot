from __future__ import annotations

import datetime
from typing import Optional

from sqlalchemy import and_, delete, func, select, update

from apps.datasource.models.datasource import CoreDatasource
from apps.extra_prompt.models.extra_prompt_model import ExtraPrompt, ExtraPromptInfo, ExtraPromptTypeEnum
from common.core.deps import SessionDep, Trans


def _normalize_type(prompt_type: Optional[str]) -> str:
    if not prompt_type:
        return ExtraPromptTypeEnum.GENERATE_SQL.value
    return prompt_type


def page_extra_prompt(
    session: SessionDep,
    current_page: int,
    page_size: int,
    oid: int,
    description: Optional[str] = None,
    datasource_id: Optional[int] = None,
    enabled: Optional[bool] = None,
    prompt_type: str = ExtraPromptTypeEnum.GENERATE_SQL.value,
):
    prompt_type = _normalize_type(prompt_type)

    stmt = (
        select(
            ExtraPrompt.id,
            ExtraPrompt.oid,
            ExtraPrompt.datasource_id,
            CoreDatasource.name.label("datasource_name"),
            ExtraPrompt.type,
            ExtraPrompt.description,
            ExtraPrompt.prompt,
            ExtraPrompt.enabled,
            ExtraPrompt.create_time,
            ExtraPrompt.update_time,
        )
        .select_from(ExtraPrompt)
        .outerjoin(CoreDatasource, CoreDatasource.id == ExtraPrompt.datasource_id)
        .where(and_(ExtraPrompt.oid == oid, ExtraPrompt.type == prompt_type))
        .order_by(ExtraPrompt.create_time.desc().nullslast(), ExtraPrompt.id.desc())
    )

    if description and description.strip():
        stmt = stmt.where(ExtraPrompt.description.ilike(f"%{description.strip()}%"))
    if datasource_id is not None:
        stmt = stmt.where(ExtraPrompt.datasource_id == datasource_id)
    if enabled is not None:
        stmt = stmt.where(ExtraPrompt.enabled == enabled)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total_count = session.execute(count_stmt).scalar() or 0

    page_size = max(10, page_size)
    total_pages = (total_count + page_size - 1) // page_size
    current_page = max(1, min(current_page, total_pages)) if total_pages > 0 else 1

    stmt = stmt.offset((current_page - 1) * page_size).limit(page_size)

    data = []
    for row in session.execute(stmt):
        data.append(
            ExtraPromptInfo(
                id=row.id,
                oid=row.oid,
                datasource_id=row.datasource_id,
                datasource_name=row.datasource_name,
                type=row.type,
                description=row.description,
                prompt=row.prompt,
                enabled=row.enabled if row.enabled is not None else False,
                create_time=row.create_time,
                update_time=row.update_time,
            )
        )

    return current_page, page_size, total_count, total_pages, data


def get_extra_prompt(session: SessionDep, prompt_id: int, oid: int) -> ExtraPromptInfo | None:
    stmt = (
        select(
            ExtraPrompt.id,
            ExtraPrompt.oid,
            ExtraPrompt.datasource_id,
            CoreDatasource.name.label("datasource_name"),
            ExtraPrompt.type,
            ExtraPrompt.description,
            ExtraPrompt.prompt,
            ExtraPrompt.enabled,
            ExtraPrompt.create_time,
            ExtraPrompt.update_time,
        )
        .select_from(ExtraPrompt)
        .outerjoin(CoreDatasource, CoreDatasource.id == ExtraPrompt.datasource_id)
        .where(and_(ExtraPrompt.id == prompt_id, ExtraPrompt.oid == oid))
    )
    row = session.execute(stmt).first()
    if not row:
        return None
    row = row[0] if isinstance(row, tuple) else row
    # SQLAlchemy Row supports attribute access
    return ExtraPromptInfo(
        id=row.id,
        oid=row.oid,
        datasource_id=row.datasource_id,
        datasource_name=getattr(row, "datasource_name", None),
        type=row.type,
        description=row.description,
        prompt=row.prompt,
        enabled=row.enabled if row.enabled is not None else False,
        create_time=row.create_time,
        update_time=row.update_time,
    )


def upsert_extra_prompt(session: SessionDep, info: ExtraPromptInfo, oid: int, trans: Trans) -> int:
    if not info.prompt or not info.prompt.strip():
        raise Exception(trans("prompt.replaced_with") if trans else "prompt cannot be empty")
    if not info.datasource_id:
        raise Exception(trans("i18n_terminology.datasource_cannot_be_none") if trans else "datasource cannot be empty")

    info.type = _normalize_type(info.type)
    if info.type != ExtraPromptTypeEnum.GENERATE_SQL.value:
        raise Exception("only GENERATE_SQL is supported")

    # Uniqueness: (oid, datasource_id, type)
    exists_stmt = select(ExtraPrompt.id).where(
        and_(
            ExtraPrompt.oid == oid,
            ExtraPrompt.datasource_id == info.datasource_id,
            ExtraPrompt.type == info.type,
        )
    )
    existing_id = session.execute(exists_stmt).scalar()
    if existing_id and (not info.id or int(existing_id) != int(info.id)):
        raise Exception("extra prompt already exists for this datasource")

    now = datetime.datetime.now()

    if info.id:
        stmt = (
            update(ExtraPrompt)
            .where(and_(ExtraPrompt.id == info.id, ExtraPrompt.oid == oid))
            .values(
                datasource_id=info.datasource_id,
                type=info.type,
                description=(info.description.strip() if info.description else None),
                prompt=info.prompt,
                enabled=info.enabled,
                update_time=now,
            )
        )
        session.execute(stmt)
        session.commit()
        return int(info.id)

    obj = ExtraPrompt(
        oid=oid,
        datasource_id=info.datasource_id,
        type=info.type,
        description=(info.description.strip() if info.description else None),
        prompt=info.prompt,
        enabled=True if info.enabled is None else info.enabled,
        create_time=now,
        update_time=now,
    )
    session.add(obj)
    session.flush()
    session.refresh(obj)
    session.commit()
    return int(obj.id)


def delete_extra_prompt(session: SessionDep, oid: int, ids: list[int]):
    if not ids:
        return
    stmt = delete(ExtraPrompt).where(and_(ExtraPrompt.oid == oid, ExtraPrompt.id.in_(ids)))
    session.execute(stmt)
    session.commit()


def enable_extra_prompt(session: SessionDep, oid: int, prompt_id: int, enabled: bool):
    stmt = (
        update(ExtraPrompt)
        .where(and_(ExtraPrompt.oid == oid, ExtraPrompt.id == prompt_id))
        .values(enabled=enabled, update_time=datetime.datetime.now())
    )
    session.execute(stmt)
    session.commit()


def find_enabled_extra_prompt(
    session: SessionDep,
    oid: int,
    datasource_id: int,
    prompt_type: str = ExtraPromptTypeEnum.GENERATE_SQL.value,
) -> Optional[ExtraPromptInfo]:
    prompt_type = _normalize_type(prompt_type)
    stmt = (
        select(
            ExtraPrompt.id,
            ExtraPrompt.oid,
            ExtraPrompt.datasource_id,
            CoreDatasource.name.label("datasource_name"),
            ExtraPrompt.type,
            ExtraPrompt.description,
            ExtraPrompt.prompt,
            ExtraPrompt.enabled,
            ExtraPrompt.create_time,
            ExtraPrompt.update_time,
        )
        .select_from(ExtraPrompt)
        .outerjoin(CoreDatasource, CoreDatasource.id == ExtraPrompt.datasource_id)
        .where(
            and_(
                ExtraPrompt.oid == oid,
                ExtraPrompt.datasource_id == datasource_id,
                ExtraPrompt.type == prompt_type,
                ExtraPrompt.enabled == True,  # noqa: E712
            )
        )
        .limit(1)
    )
    row = session.execute(stmt).first()
    if not row:
        return None
    row = row[0] if isinstance(row, tuple) else row
    return ExtraPromptInfo(
        id=row.id,
        oid=row.oid,
        datasource_id=row.datasource_id,
        datasource_name=getattr(row, "datasource_name", None),
        type=row.type,
        description=row.description,
        prompt=row.prompt,
        enabled=row.enabled if row.enabled is not None else False,
        create_time=row.create_time,
        update_time=row.update_time,
    )

