"""BlueCard field display aliases: terminology/static dict first, LLM bilingual fallback."""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlmodel import Session

from apps.chat.clarification_util import _FIELD_FRIENDLY_ALIASES, is_internal_field_name
from apps.terminology.models.terminology_model import Terminology

CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_NON_ALNUM = re.compile(r'[^a-z0-9\u4e00-\u9fff]+', re.I)


def normalize_field_key(value: Optional[str]) -> str:
    if not value:
        return ''
    return _NON_ALNUM.sub('', str(value).strip().lower())


def _has_cjk(text: Optional[str]) -> bool:
    return bool(text and CJK_RE.search(str(text)))


def pick_bilingual_from_words(
    words: list[str],
    *,
    fallback_zh: Optional[str] = None,
    fallback_en: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Pick Chinese / English labels from a terminology word group."""
    cleaned = [str(w).strip() for w in words if w and str(w).strip()]
    name_zh = next((w for w in cleaned if _has_cjk(w)), None) or fallback_zh
    name_en = next(
        (w for w in cleaned if not _has_cjk(w) and not is_internal_field_name(w)),
        None,
    )
    if not name_en:
        name_en = next((w for w in cleaned if not _has_cjk(w)), None) or fallback_en
    return name_zh, name_en


def humanize_en_field(field: str) -> str:
    raw = (field or '').strip()
    if not raw:
        return ''
    spaced = re.sub(r'[_\-.]+', ' ', raw)
    spaced = re.sub(r'([a-z])([A-Z])', r'\1 \2', spaced)
    return ' '.join(part.capitalize() for part in spaced.split() if part)


def alias_entry(
    field: str,
    *,
    name_zh: Optional[str] = None,
    name_en: Optional[str] = None,
    source: str = 'llm',
) -> dict[str, Any]:
    zh = (name_zh or '').strip() or None
    en = (name_en or '').strip() or None
    if not en:
        en = humanize_en_field(field) or field
    if not zh:
        zh = en
    return {
        'field': field,
        'name_zh': zh,
        'name_en': en,
        'source': source,
    }


def lookup_static_aliases(fields: list[str]) -> dict[str, dict[str, Any]]:
    """Hardcoded clarification-friendly aliases (Chinese)."""
    out: dict[str, dict[str, Any]] = {}
    for field in fields or []:
        if not field:
            continue
        zh = _FIELD_FRIENDLY_ALIASES.get(str(field).lower().strip())
        if not zh:
            continue
        out[field] = alias_entry(field, name_zh=zh, name_en=humanize_en_field(field), source='static')
    return out


def lookup_terminology_aliases(
    session: Session,
    fields: list[str],
    oid: int = 1,
    datasource: Optional[int] = None,
) -> dict[str, dict[str, Any]]:
    """
    Exact/normalized match of result column names against terminology words
    (parent + synonym children). Parent Chinese word preferred for name_zh.
    """
    if not fields:
        return {}
    if not oid:
        oid = 1

    field_by_norm: dict[str, list[str]] = {}
    for field in fields:
        if not field:
            continue
        key = normalize_field_key(field)
        if not key:
            continue
        field_by_norm.setdefault(key, []).append(field)
        field_by_norm.setdefault(str(field).strip().lower(), []).append(field)

    from sqlalchemy import func, text

    raw_fields = [str(f).strip() for f in fields if f and str(f).strip()]
    if not raw_fields:
        return {}

    # Exact case-insensitive equality (NOT ilike — "_" is a LIKE wildcard).
    stmt = (
        select(Terminology.id, Terminology.pid, Terminology.word)
        .where(
            and_(
                Terminology.oid == oid,
                Terminology.enabled == True,  # noqa: E712
                or_(*[func.lower(Terminology.word) == f.lower() for f in raw_fields]),
            )
        )
    )
    if datasource is not None:
        stmt = stmt.where(
            or_(
                or_(Terminology.specific_ds == False, Terminology.specific_ds.is_(None)),  # noqa: E712
                and_(
                    Terminology.specific_ds == True,  # noqa: E712
                    Terminology.datasource_ids.isnot(None),
                    text("datasource_ids @> jsonb_build_array(:datasource)"),
                ),
            )
        )
    else:
        stmt = stmt.where(or_(Terminology.specific_ds == False, Terminology.specific_ds.is_(None)))  # noqa: E712

    params: dict[str, Any] = {}
    if datasource is not None:
        params['datasource'] = datasource
    rows = session.execute(stmt, params).fetchall()
    if not rows:
        return {}

    parent_ids: list[int] = []
    matched_field_for_parent: dict[int, str] = {}
    for row in rows:
        parent_id = row.pid if row.pid is not None else row.id
        parent_ids.append(parent_id)
        word_key = normalize_field_key(row.word) or str(row.word or '').strip().lower()
        for field_name in field_by_norm.get(word_key, []):
            matched_field_for_parent.setdefault(parent_id, field_name)
        # Also try exact lower match list keys
        for field_name in field_by_norm.get(str(row.word or '').strip().lower(), []):
            matched_field_for_parent.setdefault(parent_id, field_name)

    parent_ids = list({pid for pid in parent_ids if pid is not None})
    if not parent_ids:
        return {}

    group_rows = session.query(
        Terminology.id, Terminology.pid, Terminology.word,
    ).filter(
        or_(Terminology.id.in_(parent_ids), Terminology.pid.in_(parent_ids))
    ).all()

    groups: dict[int, dict[str, Any]] = {}
    for row in group_rows:
        pid = row.pid if row.pid is not None else row.id
        if pid not in groups:
            groups[pid] = {'parent': None, 'words': []}
        if row.pid is None:
            groups[pid]['parent'] = row.word
        if row.word:
            groups[pid]['words'].append(row.word)

    out: dict[str, dict[str, Any]] = {}
    for pid, group in groups.items():
        field = matched_field_for_parent.get(pid)
        if not field:
            # Try match any synonym against fields
            for w in group['words']:
                key = normalize_field_key(w) or str(w).strip().lower()
                hits = field_by_norm.get(key) or []
                if hits:
                    field = hits[0]
                    break
        if not field or field in out:
            continue
        name_zh, name_en = pick_bilingual_from_words(
            group['words'],
            fallback_zh=group.get('parent'),
            fallback_en=humanize_en_field(field),
        )
        out[field] = alias_entry(field, name_zh=name_zh, name_en=name_en, source='terminology')
    return out


def resolve_dict_aliases(
    session: Session,
    fields: list[str],
    oid: int = 1,
    datasource: Optional[int] = None,
) -> dict[str, dict[str, Any]]:
    """Terminology first, then static friendly aliases. Dict wins over LLM later."""
    merged: dict[str, dict[str, Any]] = {}
    static = lookup_static_aliases(fields)
    term = lookup_terminology_aliases(session, fields, oid=oid, datasource=datasource)
    # static first, terminology overwrites (higher priority)
    merged.update(static)
    merged.update(term)
    return merged


def merge_aliases(
    preferred: dict[str, dict[str, Any]],
    fallback: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """preferred (dict) wins; fill missing fields / missing lang sides from fallback."""
    out: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (preferred or {}).items()}
    for field, item in (fallback or {}).items():
        if field not in out:
            out[field] = dict(item)
            continue
        cur = out[field]
        if not (cur.get('name_zh') or '').strip() and item.get('name_zh'):
            cur['name_zh'] = item['name_zh']
        if not (cur.get('name_en') or '').strip() and item.get('name_en'):
            cur['name_en'] = item['name_en']
    return out


def aliases_list(aliases: dict[str, dict[str, Any]], fields: Optional[list[str]] = None) -> list[dict[str, Any]]:
    ordered = fields if fields else list(aliases.keys())
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for f in ordered:
        if not f or f in seen:
            continue
        seen.add(f)
        item = aliases.get(f)
        if item:
            result.append(item)
    for f, item in aliases.items():
        if f not in seen:
            result.append(item)
    return result


def parse_llm_alias_payload(text: str) -> dict[str, dict[str, Any]]:
    """Parse LLM JSON array/object into field -> alias dict."""
    import orjson

    if not text or not str(text).strip():
        return {}
    raw = str(text).strip()
    # Strip markdown fences if present
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.I)
        raw = re.sub(r'\s*```$', '', raw)
    try:
        data = orjson.loads(raw)
    except Exception:
        # Try extract first JSON array/object
        m = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', raw)
        if not m:
            return {}
        try:
            data = orjson.loads(m.group(1))
        except Exception:
            return {}

    items: list[Any]
    if isinstance(data, dict):
        if 'aliases' in data and isinstance(data['aliases'], list):
            items = data['aliases']
        else:
            # {field: {name_zh, name_en}} or {field: "中文"}
            items = []
            for k, v in data.items():
                if isinstance(v, dict):
                    items.append({'field': k, **v})
                else:
                    items.append({'field': k, 'name_zh': v, 'name_en': humanize_en_field(k)})
    elif isinstance(data, list):
        items = data
    else:
        return {}

    out: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        field = item.get('field') or item.get('value') or item.get('column')
        if not field:
            continue
        field = str(field).strip()
        name_zh = item.get('name_zh') or item.get('zh') or item.get('label_zh')
        name_en = item.get('name_en') or item.get('en') or item.get('label_en')
        # Single name fallback
        if not name_zh and not name_en and item.get('name'):
            name = str(item.get('name')).strip()
            if _has_cjk(name):
                name_zh = name
            else:
                name_en = name
        out[field] = alias_entry(field, name_zh=name_zh, name_en=name_en, source='llm')
    return out


def incomplete_fields(fields: list[str], aliases: dict[str, dict[str, Any]]) -> list[str]:
    """Fields still needing LLM (missing entry or missing either language label)."""
    missing: list[str] = []
    for f in fields or []:
        if not f:
            continue
        item = aliases.get(f)
        if not item:
            missing.append(f)
            continue
        if not (item.get('name_zh') or '').strip() or not (item.get('name_en') or '').strip():
            missing.append(f)
    return missing
