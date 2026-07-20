"""Runtime: resolve published custom prompts for SQL generation."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import text
from sqlmodel import Session


def _matches_datasource(specific_ds: Optional[bool], datasource_ids: Any, ds_id: Optional[int]) -> bool:
    is_specific = bool(specific_ds)
    ids = datasource_ids if isinstance(datasource_ids, list) else []
    if ds_id is None:
        # assistant / no ds: only global prompts
        return not is_specific
    if not is_specific:
        return True
    try:
        return int(ds_id) in {int(x) for x in ids}
    except Exception:
        return False


def find_published_custom_prompts(
    session: Session,
    custom_prompt_type,
    oid: Optional[int],
    ds_id: Optional[int],
) -> tuple[str, list[dict]]:
    """Return (concatenated_prompt_text, detail_list_for_chat_log).

    Only published versions are used. Prompts without published_version_id are skipped
    (except legacy fallback to custom_prompt.prompt when version table empty — handled by ensure).
    """
    if oid is None:
        return '', []

    type_value = custom_prompt_type.value if hasattr(custom_prompt_type, 'value') else str(custom_prompt_type)

    rows = session.execute(
        text(
            """
            SELECT
                p.id,
                p.name,
                p.type,
                p.specific_ds,
                p.datasource_ids,
                p.published_version_id,
                p.prompt AS legacy_prompt,
                v.id AS version_id,
                v.version_no,
                v.prompt AS version_prompt
            FROM custom_prompt p
            LEFT JOIN custom_prompt_version v
              ON v.id = p.published_version_id
            WHERE p.oid = :oid AND p.type = :ptype
            ORDER BY p.id ASC
            """
        ),
        {'oid': oid, 'ptype': type_value},
    ).mappings().all()

    texts: list[str] = []
    details: list[dict] = []
    for row in rows:
        if not _matches_datasource(row.get('specific_ds'), row.get('datasource_ids'), ds_id):
            continue
        content = row.get('version_prompt')
        version_id = row.get('version_id')
        version_no = row.get('version_no')
        # no published version => not live
        if not row.get('published_version_id') or content is None:
            continue
        texts.append(content)
        details.append({
            'id': row.get('id'),
            'name': row.get('name') or '',
            'type': row.get('type'),
            'version_id': version_id,
            'version_no': version_no,
            'prompt': content,
        })

    return '\n\n'.join(texts), details
