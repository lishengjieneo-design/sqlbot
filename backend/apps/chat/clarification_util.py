from __future__ import annotations

import re
from typing import Any, Optional

import orjson

from datetime import datetime

from apps.chat.time_i18n import resolve_lang_key, time_range_prompt
from apps.chat.time_range_prefilter import (
    build_time_preset_candidates,
    build_time_resolution_label,
    question_has_time_constraint,
)
from common.core.config import settings

# Business aliases when schema comments are missing or equal to column names.
_FIELD_FRIENDLY_ALIASES: dict[str, str] = {
    'account_no': 'MT 交易账号（Login）',
    'login': 'MT 交易账号',
    'mt_login': 'MT 交易账号',
    'mtlogin': 'MT 交易账号',
    'crm_id': 'CRM 客户 ID',
    'member_id': '会员 ID',
    'referrer_crm_id': '推荐人 CRM ID',
    'descendant_login': '下级 MT 账号',
    'memberid_or_login': '会员 ID 或 MT 账号',
    'agent_account': '上级代理 MT 账号',
    'introduce_code': '邀请码',
    'maxtec_member_id': 'Maxtec 会员 ID',
}

_INTERNAL_FIELD_RE = re.compile(r'^[a-z][a-z0-9_]*$', re.I)
_TRAILING_FIELD_IN_LABEL_RE = re.compile(
    r'\s*[\(（][a-z][a-z0-9_]*[\)）]\s*$',
    re.I,
)

TIME_RANGE_FACTOR = 'time_range'


def default_max_rounds() -> int:
    return settings.CLARIFICATION_MAX_ROUNDS


def is_time_factor(raw: Optional[dict]) -> bool:
    if not raw:
        return False
    return raw.get('factor_type') == TIME_RANGE_FACTOR or raw.get('factor_key') == TIME_RANGE_FACTOR


def build_initial_clarification(current: dict, max_rounds: Optional[int] = None) -> dict:
    return {
        'round': 0,
        'ask_count': 1,
        'max_rounds': max_rounds if max_rounds is not None else default_max_rounds(),
        'resolved': [],
        'current': current,
        'abandoned': False,
        'force_finalized': False,
        'plan': {'steps': []},
        'progress': _empty_progress(),
    }


def _empty_progress() -> dict:
    return {
        'total_steps': 0,
        'completed_steps': 0,
        'current_step': 0,
        'remaining_steps': 0,
    }


def _resolved_id_raw_values(resolved: Optional[list]) -> set[str]:
    values: set[str] = set()
    for item in resolved or []:
        if not isinstance(item, dict) or is_time_factor(item):
            continue
        raw = item.get('raw_value')
        if raw is not None and str(raw).strip():
            values.add(str(raw).strip())
    return values


def _time_range_already_resolved(resolved: Optional[list]) -> bool:
    for item in resolved or []:
        if isinstance(item, dict) and is_time_factor(item):
            return True
    return False


def build_clarification_plan(
    question: str,
    schema_text: str = '',
    resolved: Optional[list] = None,
    *,
    time_clarification_enabled: bool = True,
) -> dict:
    """Ordered steps still required for this question (time first, then each ambiguous ID)."""
    resolved = resolved or []
    steps: list[dict] = []
    if time_clarification_enabled and not _time_range_already_resolved(resolved):
        if not question_has_time_constraint(question, resolved):
            steps.append({
                'step_key': 'time_range',
                'factor_type': TIME_RANGE_FACTOR,
                'factor_key': TIME_RANGE_FACTOR,
            })
    from apps.chat.id_schema_prefilter import plan_id_clarification_steps

    id_steps = plan_id_clarification_steps(
        question, schema_text, _resolved_id_raw_values(resolved),
    )
    steps.extend(id_steps)
    return {'steps': steps, 'total_steps': len(steps)}


def compute_clarification_progress(clarification: dict) -> dict:
    plan = clarification.get('plan') or {}
    steps = plan.get('steps') or []
    total = int(plan.get('total_steps') if plan.get('total_steps') is not None else len(steps))
    resolved = clarification.get('resolved') or []
    completed = len(resolved)
    has_current = bool(clarification.get('current'))
    if total <= 0:
        if has_current:
            total = max(completed + 1, 1)
        else:
            total = max(completed, 0)
    current_step = completed + 1 if has_current else completed
    remaining = max(0, total - completed)
    return {
        'total_steps': total,
        'completed_steps': completed,
        'current_step': min(current_step, total) if total else current_step,
        'remaining_steps': remaining,
    }


def attach_clarification_plan_and_progress(
    clarification: dict,
    question: str,
    schema_text: str = '',
    *,
    time_clarification_enabled: bool = True,
) -> dict:
    plan = build_clarification_plan(
        question,
        schema_text,
        clarification.get('resolved'),
        time_clarification_enabled=time_clarification_enabled,
    )
    merged = {**clarification, 'plan': plan}
    merged['progress'] = compute_clarification_progress(merged)
    return merged


def is_internal_field_name(text: Optional[str], field: Optional[str] = None) -> bool:
    """True when text looks like a DB column identifier, not a user-facing alias."""
    if not text or not str(text).strip():
        return True
    t = str(text).strip()
    if field and t.lower() == str(field).lower():
        return True
    if _INTERNAL_FIELD_RE.fullmatch(t):
        return True
    if field and t.lower().endswith(str(field).lower()) and len(t) <= len(field) + 4:
        return True
    return False


def resolve_user_label(field: str, raw_label: Optional[str] = None,
                       description: Optional[str] = None) -> Optional[str]:
    """Resolve a user-visible alias; never return bare column names."""
    field_key = (field or '').lower()
    candidates_text: list[str] = []
    for text in (raw_label, description):
        if not text or not str(text).strip():
            continue
        part = str(text).split('，')[0].split(',')[0].strip()
        part = _TRAILING_FIELD_IN_LABEL_RE.sub('', part).strip()
        if part and not is_internal_field_name(part, field):
            candidates_text.append(part)
    if candidates_text:
        label = candidates_text[0]
        if len(label) > 80:
            label = label[:77] + '...'
        return label
    return _FIELD_FRIENDLY_ALIASES.get(field_key)


def sanitize_clarification_candidates(candidates: Optional[list]) -> list[dict]:
    """Drop or fix options that would expose internal column names to users."""
    if not candidates:
        return []
    sanitized: list[dict] = []
    seen_labels: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        field = item.get('field')
        if not field:
            continue
        label = resolve_user_label(
            str(field),
            item.get('label'),
            item.get('description'),
        )
        if not label:
            continue
        key = label.casefold()
        if key in seen_labels:
            continue
        seen_labels.add(key)
        sanitized.append({'field': field, 'label': label})
    return sanitized


def _parse_clarification_anchor(current_date: Optional[str]) -> Optional[datetime]:
    if not current_date:
        return None
    try:
        return datetime.fromisoformat(str(current_date))
    except ValueError:
        return None


def merge_time_range_candidates(
    raw_candidates: Optional[list],
    earliest_date: str,
    anchor: Optional[datetime] = None,
    lang: Optional[str] = None,
) -> list[dict]:
    """Ensure every preset has date_start/date_end; add missing presets (e.g. all_time)."""
    presets = build_time_preset_candidates(earliest_date, anchor, lang=lang)
    by_field = {p['field']: p for p in presets}
    if not raw_candidates:
        return presets
    merged: list[dict] = []
    seen: set[str] = set()
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        field = item.get('field')
        if not field:
            continue
        base = dict(by_field.get(field, {}))
        if base:
            base['label'] = item.get('label') or base.get('label')
            if item.get('date_start'):
                base['date_start'] = item['date_start']
            if item.get('date_end'):
                base['date_end'] = item['date_end']
            merged.append(base)
        else:
            merged.append(dict(item))
        seen.add(str(field))
    if 'all_time' not in seen and 'all_time' in by_field:
        merged.insert(0, dict(by_field['all_time']))
    for p in presets:
        if p['field'] not in seen:
            merged.append(dict(p))
    return merged if merged else presets


def normalize_current(raw: dict) -> dict:
    factor_type = raw.get('factor_type') or 'id'
    if is_time_factor(raw):
        earliest = raw.get('earliest_data_date') or settings.QUERY_EARLIEST_DATE
        lang = raw.get('locale') or raw.get('lang')
        lang_key = resolve_lang_key(lang)
        anchor = _parse_clarification_anchor(raw.get('current_date'))
        candidates = merge_time_range_candidates(raw.get('candidates'), earliest, anchor, lang=lang_key)
        today_iso = anchor.date().isoformat() if anchor else datetime.now().date().isoformat()
        return {
            'factor_type': TIME_RANGE_FACTOR,
            'factor_key': raw.get('factor_key') or TIME_RANGE_FACTOR,
            'prompt': raw.get('prompt') or time_range_prompt(lang_key),
            'locale': lang_key,
            'raw_value': raw.get('raw_value'),
            'candidates': candidates,
            'earliest_data_date': earliest,
            'current_date': raw.get('current_date') or today_iso,
            'data_hint': raw.get('data_hint'),
            'source': raw.get('source'),
            'allow_custom_range': raw.get('allow_custom_range', True),
        }
    candidates = sanitize_clarification_candidates(raw.get('candidates'))
    return {
        'factor_type': factor_type,
        'factor_key': raw.get('factor_key') or raw.get('raw_value') or 'unknown',
        'prompt': raw.get('prompt') or '请确认字段含义',
        'raw_value': raw.get('raw_value'),
        'candidates': candidates,
    }


def get_time_range_resolved(clarification: Optional[dict]) -> Optional[dict]:
    if not clarification:
        return None
    for item in reversed(clarification.get('resolved') or []):
        if isinstance(item, dict) and (
            item.get('factor_type') == TIME_RANGE_FACTOR or item.get('factor_key') == TIME_RANGE_FACTOR
        ):
            return item
    return None


def apply_user_resolution(clarification: dict, selection: Optional[dict] = None,
                          free_text: Optional[str] = None,
                          earliest_date: Optional[str] = None,
                          lang: Optional[str] = None) -> dict:
    current = clarification.get('current') or {}
    is_time = is_time_factor(current)
    field = None
    label = None
    source = 'free_text'
    date_start = None
    date_end = None
    if selection:
        field = selection.get('field')
        if is_time:
            label = build_time_resolution_label(
                selection, earliest_date=earliest_date, lang=lang or current.get('locale'),
            )
            date_start = selection.get('date_start')
            date_end = selection.get('date_end')
        else:
            label = resolve_user_label(str(field or ''), selection.get('label')) or selection.get('label')
        source = 'click'
    resolved_entry: dict[str, Any] = {
        'factor_type': TIME_RANGE_FACTOR if is_time else 'id',
        'factor_key': current.get('factor_key') or current.get('raw_value'),
        'raw_value': current.get('raw_value'),
        'field': field,
        'label': label or free_text,
        'source': source,
        'free_text': free_text,
    }
    if is_time:
        if date_start:
            resolved_entry['date_start'] = date_start
        if date_end:
            resolved_entry['date_end'] = date_end
        if earliest_date:
            resolved_entry['earliest_data_date'] = earliest_date
    resolved = list(clarification.get('resolved') or [])
    resolved.append(resolved_entry)
    result = {
        **clarification,
        'resolved': resolved,
        'current': None,
    }
    if is_time:
        return result
    return {
        **result,
        'round': int(clarification.get('round') or 0) + 1,
    }


def should_force_finalize(clarification: Optional[dict]) -> bool:
    if not clarification:
        return False
    if clarification.get('force_finalized'):
        return True
    ask_count = int(clarification.get('ask_count') or 0)
    max_rounds = int(clarification.get('max_rounds') or default_max_rounds())
    return ask_count >= max_rounds


def increment_ask_count(clarification: dict) -> dict:
    return {
        **clarification,
        'ask_count': int(clarification.get('ask_count') or 0) + 1,
    }


def resolved_blocks_xml(clarification: dict, earliest_date: Optional[str] = None) -> str:
    blocks = []
    for item in clarification.get('resolved') or []:
        if not isinstance(item, dict):
            continue
        if item.get('factor_type') == TIME_RANGE_FACTOR or item.get('factor_key') == TIME_RANGE_FACTOR:
            ed = item.get('earliest_data_date') or earliest_date or settings.QUERY_EARLIEST_DATE
            ds = item.get('date_start') or ''
            de = item.get('date_end') or ''
            blocks.append(
                f'<time-range-resolved>\n'
                f'用户确认时间范围：{item.get("label") or item.get("free_text")}\n'
                f'开始日期：{ds}\n'
                f'结束日期：{de}\n'
                f'预设键（如有）：{item.get("field")}\n'
                f'数据最早可查日（下界不得早于）：{ed}\n'
                f'必须在 SQL 的 WHERE 或子查询中对时间字段施加过滤；'
                f'时间下界 >= {ds or ed}，时间上界 <= {de}（若仅单日则起止相同）。\n'
                f'禁止对时间范围再次返回 clarification。\n'
                f'</time-range-resolved>'
            )
            continue
        blocks.append(
            f'<id-clarification-resolved>\n'
            f'原始歧义值：{item.get("raw_value")}\n'
            f'用户确认字段：{item.get("field")}\n'
            f'用户说明：{item.get("label") or item.get("free_text")}\n'
            f'必须使用用户确认的字段生成 SQL，禁止对同一因子再次返回 clarification。\n'
            f'</id-clarification-resolved>'
        )
    return '\n'.join(blocks)


def clarification_limit_xml(clarification: dict) -> str:
    return (
        f'<clarification-limit-reached>\n'
        f'已达本问澄清上限（{clarification.get("max_rounds", default_max_rounds())} 轮）。'
        f'以下为用户已确认信息，必须据此生成 SQL，禁止再返回 clarification：\n'
        f'{orjson.dumps(clarification.get("resolved") or []).decode()}\n'
        f'对尚未确认的歧义，采用 schema/术语中最合理的一种解释，并在 reasoning 中简要说明假设。\n'
        f'</clarification-limit-reached>'
    )
