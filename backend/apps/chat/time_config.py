"""Query time-range configuration (system variable + settings fallback)."""
from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from apps.system.models.system_variable_model import SystemVariable
from common.core.config import settings
from common.utils.utils import SQLBotLogUtil

_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_QUERY_EARLIEST_VAR_NAME = 'i18n_variable.query_earliest_date'


def _parse_date(value: str) -> bool:
    if not _DATE_RE.fullmatch(value or ''):
        return False
    try:
        datetime.strptime(value, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def get_query_earliest_date(session: Session | None = None) -> str:
    fallback = settings.QUERY_EARLIEST_DATE
    if not _parse_date(fallback):
        fallback = '2024-01-01'
    if session is None:
        return fallback
    try:
        record = (
            session.query(SystemVariable)
            .filter(SystemVariable.name == _QUERY_EARLIEST_VAR_NAME)
            .first()
        )
        if not record or not record.value:
            return fallback
        raw = record.value[0] if isinstance(record.value, list) else record.value
        candidate = str(raw).strip()
        if _parse_date(candidate):
            return candidate
        SQLBotLogUtil.warning(
            f'Invalid query_earliest_date system variable value: {candidate!r}, using {fallback}'
        )
    except Exception as e:
        SQLBotLogUtil.warning(f'Failed to load query_earliest_date: {e}, using {fallback}')
    return fallback


def format_earliest_date_display(iso_date: str, lang_key: str = 'zh') -> str:
    """Format earliest date for UI hints (locale-aware)."""
    if not _parse_date(iso_date):
        return iso_date
    dt = datetime.strptime(iso_date, '%Y-%m-%d')
    if lang_key == 'en':
        return dt.strftime('%Y-%m-%d')
    if lang_key == 'ko':
        return f'{dt.year}년 {dt.month}월 {dt.day}일'
    if lang_key == 'zh-tw':
        return f'{dt.year}年{dt.month}月{dt.day}日'
    return f'{dt.year}年{dt.month}月{dt.day}日'
