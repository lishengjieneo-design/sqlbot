"""Detect missing time range in user questions; build time clarification payload."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

from apps.chat.time_config import format_earliest_date_display
from apps.chat.time_i18n import (
    preset_label,
    range_sep,
    resolve_lang_key,
    time_data_hint,
    time_range_prompt,
    validation_message,
)

_TIME_RANGE_FACTOR = 'time_range'

_DATE_PATTERNS = (
    re.compile(r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}'),
    re.compile(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}'),
    re.compile(r'\d{4}年\d{1,2}月'),
    re.compile(r'\d{4}年'),
)

# Arabic digits or Chinese numerals (e.g. 最近一个月 / 近7天 / 过去三天).
_CN_NUM = r'(?:\d+|[一二三四五六七八九十百千万两]+)'
_CN_TIME_UNIT = r'[天日周月年]'
_CN_RELATIVE_DURATION = (
    rf'最近\s*{_CN_NUM}\s*个?\s*{_CN_TIME_UNIT}|'
    rf'近\s*{_CN_NUM}\s*个?\s*{_CN_TIME_UNIT}|'
    rf'过去\s*{_CN_NUM}\s*个?\s*{_CN_TIME_UNIT}'
)

_RELATIVE_TIME_RE = re.compile(
    r'今天|今日|昨天|昨日|前天|本周|这周|上周|本月|这个月|上月|上个月|'
    r'本季度|上季度|今年|去年|前年|'
    + _CN_RELATIVE_DURATION + r'|'
    r'Q[1-4]|第[一二三四]季度',
    re.I,
)
_EN_MONTH_NAMES = (
    r'january|february|march|april|june|july|august|september|october|november|december|'
    r'jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec'
)
_EN_MONTH_TIME_RE = re.compile(
    rf'\b(?:{_EN_MONTH_NAMES})\b(?:\s*,?\s*\d{{2,4}})?'
    rf'|\b\d{{4}}\s+(?:{_EN_MONTH_NAMES})\b'
    rf'|\b(?:for\s+)?(?:the\s+)?month\s+of\s+(?:{_EN_MONTH_NAMES})(?:\s+\d{{4}})?\b'
    rf'|\bin\s+(?:{_EN_MONTH_NAMES})(?:\s+\d{{4}})?\b'
    rf'|\b(?:may)\s+\d{{2,4}}\b',
    re.I,
)
# English digits or word numbers (e.g. last 30 days / last one month / past two weeks).
_EN_NUM = (
    r'(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|'
    r'eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|'
    r'twenty|thirty|forty|fifty|sixty|ninety|a|an|couple|few|several)'
)
_EN_DURATION_UNIT = r'(?:days?|weeks?|months?|years?)'

_EN_RELATIVE_TIME_RE = re.compile(
    r'\b(?:today|yesterday|this\s+week|last\s+week|this\s+month|last\s+month|'
    r'this\s+year|last\s+year|year\s+to\s+date|ytd|'
    rf'(?:last|past)\s+{_EN_NUM}\s+{_EN_DURATION_UNIT}|'
    r'(?:last|past)\s+(?:day|week|month|year))\b',
    re.I,
)
_EN_RANGE_RE = re.compile(
    r'\bfrom\s+.+\s+to\b|\bbetween\s+.+\s+and\b|\bthrough\b|\buntil\b|\bas\s+of\b',
    re.I,
)
_MONTH_YEAR_NUM_RE = re.compile(r'\b\d{1,2}/\d{4}\b|\b\d{4}/\d{1,2}\b')
_RANGE_RE = re.compile(r'从.+到|至|截止|截至|之间|起止|区间', re.I)
_EXEMPT_RE = re.compile(
    r'全量|历史累计|不限时间|全部历史|所有历史|整个历史',
    re.I,
)


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value, '%Y-%m-%d').date()


def _clamp_start(start: date, earliest: date) -> date:
    return max(start, earliest)


def _week_start_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _pack_candidate(field: str, label: str, start: date, end: date, earliest: date) -> dict:
    start = _clamp_start(start, earliest)
    if end < start:
        end = start
    return {
        'field': field,
        'label': label,
        'date_start': start.isoformat(),
        'date_end': end.isoformat(),
    }


def build_time_preset_candidates(
    earliest_date: str,
    anchor: Optional[datetime] = None,
    lang: Optional[str] = None,
) -> list[dict]:
    """Build preset options with concrete ISO date bounds (first = all-time from earliest to today)."""
    lang_key = resolve_lang_key(lang)
    anchor = anchor or datetime.now()
    today = anchor.date()
    earliest = _parse_iso_date(earliest_date)
    yesterday = today - timedelta(days=1)
    week_start = _week_start_monday(today)
    month_start = today.replace(day=1)

    def _label(field: str) -> str:
        return preset_label(field, lang_key)

    return [
        _pack_candidate('all_time', _label('all_time'), earliest, today, earliest),
        _pack_candidate('today', _label('today'), today, today, earliest),
        _pack_candidate('yesterday', _label('yesterday'), yesterday, yesterday, earliest),
        _pack_candidate('this_week', _label('this_week'), week_start, today, earliest),
        _pack_candidate('this_month', _label('this_month'), month_start, today, earliest),
        _pack_candidate('last_7_days', _label('last_7_days'), today - timedelta(days=6), today, earliest),
        _pack_candidate('last_30_days', _label('last_30_days'), today - timedelta(days=29), today, earliest),
    ]


def format_time_range_display(date_start: str, date_end: str, range_sep: str = '至') -> str:
    """Single date or range string for UI / LLM hints."""
    if not date_start:
        return ''
    if not date_end or date_start == date_end:
        return date_start
    return f'{date_start} {range_sep} {date_end}'


def build_time_resolution_label(
    selection: dict,
    earliest_date: Optional[str] = None,
    lang: Optional[str] = None,
) -> str:
    lang_key = resolve_lang_key(lang)
    sep = range_sep(lang_key)
    field = selection.get('field') or ''
    title = (selection.get('label') or preset_label(field, lang_key) or field or '').strip()
    start = selection.get('date_start')
    end = selection.get('date_end')
    wrap_open, wrap_close = ('（', '）') if lang_key.startswith('zh') else (' (', ')')
    if field == 'all_time' and earliest_date and start and end:
        all_title = preset_label('all_time', lang_key)
        return f'{all_title}{wrap_open}{format_time_range_display(start, end, sep)}{wrap_close}'
    if start and end:
        if title:
            return f'{title}{wrap_open}{format_time_range_display(start, end, sep)}{wrap_close}'
        return format_time_range_display(start, end, sep)
    return title or field


def validate_time_selection(
    selection: dict,
    earliest_date: str,
    lang: Optional[str] = None,
) -> Optional[str]:
    """Validate preset or custom selection dates."""
    if not selection:
        return None
    start_s = selection.get('date_start')
    end_s = selection.get('date_end')
    lang_key = resolve_lang_key(lang)
    if not start_s or not end_s:
        if selection.get('field') == 'custom':
            return validation_message('pick_date', lang_key)
        return None
    try:
        start = _parse_iso_date(str(start_s))
        end = _parse_iso_date(str(end_s))
    except ValueError:
        return validation_message('bad_format', lang_key)
    if end < start:
        return validation_message('end_before_start', lang_key)
    earliest = _parse_iso_date(earliest_date)
    if start < earliest:
        display = format_earliest_date_display(earliest_date, lang_key)
        return validation_message('before_earliest', lang_key, date=display)
    return None


def _has_time_range_resolved(resolved: Optional[list]) -> bool:
    for item in resolved or []:
        if not isinstance(item, dict):
            continue
        if item.get('factor_type') == _TIME_RANGE_FACTOR or item.get('factor_key') == _TIME_RANGE_FACTOR:
            return True
    return False


def question_has_time_constraint(question: str, resolved: Optional[list] = None) -> bool:
    if _has_time_range_resolved(resolved):
        return True
    if not question or not question.strip():
        return False
    q = question.strip()
    if _EXEMPT_RE.search(q):
        return True
    for pat in _DATE_PATTERNS:
        if pat.search(q):
            return True
    if _RELATIVE_TIME_RE.search(q):
        return True
    if _EN_MONTH_TIME_RE.search(q):
        return True
    if _EN_RELATIVE_TIME_RE.search(q):
        return True
    if _MONTH_YEAR_NUM_RE.search(q):
        return True
    if _RANGE_RE.search(q) and (
        any(p.search(q) for p in _DATE_PATTERNS)
        or _RELATIVE_TIME_RE.search(q)
        or _EN_MONTH_TIME_RE.search(q)
        or _EN_RELATIVE_TIME_RE.search(q)
    ):
        return True
    if _EN_RANGE_RE.search(q) and (
        any(p.search(q) for p in _DATE_PATTERNS)
        or _EN_MONTH_TIME_RE.search(q)
        or _EN_RELATIVE_TIME_RE.search(q)
        or _MONTH_YEAR_NUM_RE.search(q)
    ):
        return True
    return False


# Bare 最近/近期 without a quantifier — not explicit enough for flow metrics.
_BARE_VAGUE_TIME_RE = re.compile(r'(?:最近|近期)(?![一二三四五六七八九十百千万两\d个])')


def question_has_explicit_time_constraint(question: str, resolved: Optional[list] = None) -> bool:
    """Stricter than question_has_time_constraint: bare 最近/近期 without quantity do not count."""
    if not question_has_time_constraint(question, resolved):
        return False
    q = question.strip()
    if not _BARE_VAGUE_TIME_RE.search(q):
        return True
    stripped = _BARE_VAGUE_TIME_RE.sub('', q)
    return question_has_time_constraint(stripped, None)


def build_time_range_clarification(
    earliest_date: str,
    anchor: Optional[datetime] = None,
    lang: Optional[str] = None,
) -> dict:
    lang_key = resolve_lang_key(lang)
    display = format_earliest_date_display(earliest_date, lang_key)
    anchor = anchor or datetime.now()
    today = anchor.date()
    return {
        'factor_type': _TIME_RANGE_FACTOR,
        'factor_key': _TIME_RANGE_FACTOR,
        'prompt': time_range_prompt(lang_key),
        'earliest_data_date': earliest_date,
        'current_date': today.isoformat(),
        'data_hint': time_data_hint(display, lang_key),
        'raw_value': None,
        'candidates': build_time_preset_candidates(earliest_date, anchor, lang=lang_key),
        'source': 'time_prefilter',
        'allow_custom_range': True,
        'locale': lang_key,
    }


def parse_earliest_date_from_free_text(text: str) -> Optional[datetime]:
    if not text:
        return None
    matches = re.findall(r'(\d{4})[-/年](\d{1,2})[-/月]?(\d{1,2})?', text)
    dates: list[datetime] = []
    for parts in matches:
        y, m = int(parts[0]), int(parts[1])
        d = int(parts[2]) if parts[2] else 1
        try:
            dates.append(datetime(y, m, d))
        except ValueError:
            continue
    if not dates:
        return None
    return min(dates)


def validate_time_free_text(
    free_text: str,
    earliest_date: str,
    lang: Optional[str] = None,
) -> Optional[str]:
    if not free_text or not free_text.strip():
        return None
    if _EXEMPT_RE.search(free_text):
        return None
    earliest = datetime.strptime(earliest_date, '%Y-%m-%d')
    start = parse_earliest_date_from_free_text(free_text)
    if start is None:
        return None
    if start.date() < earliest.date():
        lang_key = resolve_lang_key(lang)
        display = format_earliest_date_display(earliest_date, lang_key)
        return validation_message('before_earliest', lang_key, date=display)
    return None
