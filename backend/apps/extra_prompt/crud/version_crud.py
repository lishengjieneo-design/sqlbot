"""CRUD for extra_prompt draft / publish / rollback."""
from __future__ import annotations

import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlmodel import Session, select

from apps.extra_prompt.models.version_model import (
    ExtraPromptDraftSave,
    ExtraPromptVersion,
    ExtraPromptVersionInfo,
    ExtraPromptVersioningState,
)
from common.core.deps import Trans


def _to_info(
    row: ExtraPromptVersion,
    *,
    published_id: Optional[int],
    draft_id: Optional[int],
) -> ExtraPromptVersionInfo:
    return ExtraPromptVersionInfo(
        id=row.id,
        prompt_id=row.prompt_id,
        version_no=row.version_no,
        prompt=row.prompt,
        change_note=row.change_note,
        created_by=row.created_by,
        create_time=row.create_time,
        is_published=bool(published_id and row.id == published_id),
        is_draft=bool(draft_id and row.id == draft_id),
    )


def _get_prompt_row(session: Session, prompt_id: int, oid: int) -> dict[str, Any]:
    row = session.execute(
        text(
            """
            SELECT id, oid, published_version_id, draft_version_id, prompt, description, enabled
            FROM extra_prompt
            WHERE id = :id AND oid = :oid
            """
        ),
        {'id': prompt_id, 'oid': oid},
    ).mappings().first()
    if not row:
        raise Exception('extra_prompt_not_found')
    return dict(row)


def _next_version_no(session: Session, prompt_id: int) -> int:
    current = session.execute(
        text('SELECT COALESCE(MAX(version_no), 0) FROM extra_prompt_version WHERE prompt_id = :pid'),
        {'pid': prompt_id},
    ).scalar()
    return int(current or 0) + 1


def get_versioning_state(session: Session, prompt_id: int, oid: int) -> ExtraPromptVersioningState:
    row = _get_prompt_row(session, prompt_id, oid)
    published_id = row.get('published_version_id')
    draft_id = row.get('draft_version_id')
    versions = session.execute(
        select(ExtraPromptVersion)
        .where(ExtraPromptVersion.prompt_id == prompt_id)
        .order_by(ExtraPromptVersion.version_no.desc())
    ).scalars().all()
    infos = [_to_info(v, published_id=published_id, draft_id=draft_id) for v in versions]
    published = next((i for i in infos if i.is_published), None)
    draft = next((i for i in infos if i.is_draft), None)
    return ExtraPromptVersioningState(
        prompt_id=prompt_id,
        published_version_id=published_id,
        draft_version_id=draft_id,
        published=published,
        draft=draft,
        versions=infos,
    )


def save_draft(
    session: Session,
    prompt_id: int,
    oid: int,
    payload: ExtraPromptDraftSave,
    created_by: Optional[int] = None,
    trans: Optional[Trans] = None,
) -> ExtraPromptVersionInfo:
    row = _get_prompt_row(session, prompt_id, oid)
    draft_id = row.get('draft_version_id')
    content = payload.prompt if payload.prompt is not None else ''
    note = (payload.change_note or '').strip() or None

    if draft_id:
        draft = session.get(ExtraPromptVersion, draft_id)
        if not draft or draft.prompt_id != prompt_id:
            raise Exception(trans('i18n_prompt.version_not_found') if trans else 'version_not_found')
        draft.prompt = content
        if note:
            draft.change_note = note
        session.add(draft)
        session.commit()
        session.refresh(draft)
        return _to_info(draft, published_id=row.get('published_version_id'), draft_id=draft.id)

    version = ExtraPromptVersion(
        prompt_id=prompt_id,
        version_no=_next_version_no(session, prompt_id),
        prompt=content,
        change_note=note,
        created_by=created_by,
        create_time=datetime.datetime.now(),
    )
    session.add(version)
    session.flush()
    session.execute(
        text('UPDATE extra_prompt SET draft_version_id = :vid, update_time = :now WHERE id = :pid'),
        {'vid': version.id, 'pid': prompt_id, 'now': datetime.datetime.now()},
    )
    session.commit()
    session.refresh(version)
    return _to_info(version, published_id=row.get('published_version_id'), draft_id=version.id)


def publish_draft(
    session: Session,
    prompt_id: int,
    oid: int,
    created_by: Optional[int] = None,
    trans: Optional[Trans] = None,
) -> ExtraPromptVersionInfo:
    row = _get_prompt_row(session, prompt_id, oid)
    draft_id = row.get('draft_version_id')
    if not draft_id:
        published_id = row.get('published_version_id')
        if published_id:
            published = session.get(ExtraPromptVersion, published_id)
            if published:
                return _to_info(published, published_id=published_id, draft_id=None)
        raise Exception(trans('i18n_prompt.no_draft_to_publish') if trans else 'no_draft_to_publish')

    draft = session.get(ExtraPromptVersion, draft_id)
    if not draft or draft.prompt_id != prompt_id:
        raise Exception(trans('i18n_prompt.version_not_found') if trans else 'version_not_found')

    session.execute(
        text(
            """
            UPDATE extra_prompt
            SET published_version_id = :vid,
                draft_version_id = NULL,
                prompt = :prompt,
                update_time = :now
            WHERE id = :pid
            """
        ),
        {
            'vid': draft.id,
            'prompt': draft.prompt,
            'pid': prompt_id,
            'now': datetime.datetime.now(),
        },
    )
    session.commit()
    session.refresh(draft)
    return _to_info(draft, published_id=draft.id, draft_id=None)


def publish_version(
    session: Session,
    prompt_id: int,
    version_id: int,
    oid: int,
    trans: Optional[Trans] = None,
) -> ExtraPromptVersionInfo:
    _get_prompt_row(session, prompt_id, oid)
    version = session.get(ExtraPromptVersion, version_id)
    if not version or version.prompt_id != prompt_id:
        raise Exception(trans('i18n_prompt.version_not_found') if trans else 'version_not_found')

    session.execute(
        text(
            """
            UPDATE extra_prompt
            SET published_version_id = :vid,
                prompt = :prompt,
                update_time = :now
            WHERE id = :pid
            """
        ),
        {
            'vid': version.id,
            'prompt': version.prompt,
            'pid': prompt_id,
            'now': datetime.datetime.now(),
        },
    )
    session.commit()
    row = _get_prompt_row(session, prompt_id, oid)
    return _to_info(version, published_id=version.id, draft_id=row.get('draft_version_id'))


def list_versions(session: Session, prompt_id: int, oid: int) -> list[ExtraPromptVersionInfo]:
    return get_versioning_state(session, prompt_id, oid).versions
