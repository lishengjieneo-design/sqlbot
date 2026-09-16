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
    r'今天|今日|昨天|昨日|前天|本周|这周|这个周|这个星期|这星期|当周|'
    r'上周|上一周|上个星期|上星期|本月|这个月|当月|上月|上个月|上一月|上月份|'
    r'本季度|这个季度|上季度|上个季度|'
    r'今年|本年|本年度|这一年|这个年度|本年份|'
    r'去年|上一年|上一年度|上年度|去年度|前年|'
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
    last_week_end = week_start - timedelta(days=1)
    last_week_start = last_week_end - timedelta(days=6)
    month_start = today.replace(day=1)
    # last day of previous month = day before this month's start
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    year_start = today.replace(month=1, day=1)

    def _label(field: str) -> str:
        return preset_label(field, lang_key)

    return [
        _pack_candidate('all_time', _label('all_time'), earliest, today, earliest),
        _pack_candidate('today', _label('today'), today, today, earliest),
        _pack_candidate('yesterday', _label('yesterday'), yesterday, yesterday, earliest),
        _pack_candidate('this_week', _label('this_week'), week_start, today, earliest),
        _pack_candidate('last_week', _label('last_week'), last_week_start, last_week_end, earliest),
        _pack_candidate('this_month', _label('this_month'), month_start, today, earliest),
        _pack_candidate('last_month', _label('last_month'), last_month_start, last_month_end, earliest),
        _pack_candidate('this_year', _label('this_year'), year_start, today, earliest),
        _pack_candidate('last_7_days', _label('last_7_days'), today - timedelta(days=6), today, earliest),
        _pack_candidate('last_30_days', _label('last_30_days'), today - timedelta(days=29), today, earliest),
    ]


# Longer / more specific phrases first. Each maps to a preset field or a synthetic range.
_INFER_TIME_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r'本年度|这一年|这个年度|本年份|本年|今年|this\s+year|year\s+to\s+date|\bytd\b', re.I), 'this_year'),
    (re.compile(r'前年', re.I), 'year_before_last'),
    (re.compile(r'上年度|上一年度|上一年|去年度|去年|last\s+year', re.I), 'last_year'),
    (re.compile(r'本季度|这个季度|this\s+quarter', re.I), 'this_quarter'),
    (re.compile(r'上季度|上个季度|last\s+quarter', re.I), 'last_quarter'),
    (re.compile(r'本月|这个月|当月|this\s+month', re.I), 'this_month'),
    (re.compile(r'上月|上个月|上一月|上月份|last\s+month', re.I), 'last_month'),
    (re.compile(r'本周|这周|这个星期|这星期|这个周|当周|this\s+week', re.I), 'this_week'),
    (re.compile(r'上周|上一周|上个星期|上星期|last\s+week', re.I), 'last_week'),
    (re.compile(r'今天|今日|today', re.I), 'today'),
    (re.compile(r'昨天|昨日|yesterday', re.I), 'yesterday'),
    (re.compile(r'前天|day\s+before\s+yesterday', re.I), 'day_before_yesterday'),
    (re.compile(r'最近\s*7\s*天|近\s*7\s*天|last\s*7\s*days?', re.I), 'last_7_days'),
    (re.compile(r'最近\s*30\s*天|近\s*30\s*天|last\s*30\s*days?', re.I), 'last_30_days'),
)

_CN_DURATION_INFER_RE = re.compile(
    rf'(?:最近|近|过去)\s*({_CN_NUM})\s*个?\s*({_CN_TIME_UNIT})'
)
_EN_DURATION_INFER_RE = re.compile(
    rf'\b(?:last|past)\s+({_EN_NUM})\s+({_EN_DURATION_UNIT})\b',
    re.I,
)

_CN_NUM_MAP = {
    '零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
    '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
}


def _parse_simple_cn_num(token: str) -> Optional[int]:
    token = (token or '').strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    if token in _CN_NUM_MAP:
        return _CN_NUM_MAP[token]
    # 十一..十九 / 二十 / 三十…
    if token.startswith('十') and len(token) <= 2:
        return 10 + (_CN_NUM_MAP.get(token[1], 0) if len(token) == 2 else 0)
    if len(token) >= 2 and token[1] == '十':
        tens = _CN_NUM_MAP.get(token[0])
        ones = _CN_NUM_MAP.get(token[2], 0) if len(token) > 2 else 0
        if tens is not None:
            return tens * 10 + ones
    return None


def _parse_en_num(token: str) -> Optional[int]:
    t = (token or '').strip().lower()
    if not t:
        return None
    if t.isdigit():
        return int(t)
    words = {
        'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14, 'fifteen': 15,
        'sixteen': 16, 'seventeen': 17, 'eighteen': 18, 'nineteen': 19,
        'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
        'couple': 2, 'few': 3, 'several': 3,
    }
    return words.get(t)


def _subtract_months(d: date, months: int) -> date:
    y = d.year
    m = d.month - months
    while m <= 0:
        m += 12
        y -= 1
    if m == 12:
        last_day = 31
    else:
        last_day = (date(y, m + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last_day))


def _synthetic_day_before_yesterday(earliest: date, today: date, lang_key: str) -> dict:
    d = today - timedelta(days=2)
    label = '前天' if lang_key.startswith('zh') else 'Day before yesterday'
    return _pack_candidate('day_before_yesterday', label, d, d, earliest)


def _synthetic_calendar_year(earliest: date, today: date, lang_key: str, *, years_ago: int) -> dict:
    y = today.year - years_ago
    start = date(y, 1, 1)
    end = date(y, 12, 31)
    if years_ago == 1:
        label = '去年' if lang_key.startswith('zh') else 'Last year'
        field = 'last_year'
    else:
        label = '前年' if lang_key.startswith('zh') else 'Year before last'
        field = 'year_before_last'
    return _pack_candidate(field, label, start, end, earliest)


def _synthetic_this_quarter(earliest: date, today: date, lang_key: str) -> dict:
    q = (today.month - 1) // 3
    start = date(today.year, q * 3 + 1, 1)
    label = '本季度' if lang_key.startswith('zh') else 'This quarter'
    return _pack_candidate('this_quarter', label, start, today, earliest)


def _synthetic_last_quarter(earliest: date, today: date, lang_key: str) -> dict:
    q = (today.month - 1) // 3
    if q == 0:
        start = date(today.year - 1, 10, 1)
        end = date(today.year - 1, 12, 31)
    else:
        start = date(today.year, (q - 1) * 3 + 1, 1)
        end = date(today.year, q * 3 + 1, 1) - timedelta(days=1)
    label = '上季度' if lang_key.startswith('zh') else 'Last quarter'
    return _pack_candidate('last_quarter', label, start, end, earliest)


def _infer_from_duration(
    n: int, unit: str, earliest: date, today: date, lang_key: str,
) -> Optional[dict]:
    if n <= 0:
        return None
    u = unit.lower()
    if u in ('天', '日', 'day', 'days'):
        start = today - timedelta(days=n - 1)
        label = f'最近{n}天' if lang_key.startswith('zh') else f'Last {n} days'
        return _pack_candidate(f'last_{n}_days', label, start, today, earliest)
    if u in ('周', 'week', 'weeks'):
        start = today - timedelta(days=n * 7 - 1)
        label = f'最近{n}周' if lang_key.startswith('zh') else f'Last {n} weeks'
        return _pack_candidate(f'last_{n}_weeks', label, start, today, earliest)
    if u in ('月', 'month', 'months'):
        start = _subtract_months(today, n)
        label = f'最近{n}个月' if lang_key.startswith('zh') else f'Last {n} months'
        return _pack_candidate(f'last_{n}_months', label, start, today, earliest)
    if u in ('年', 'year', 'years'):
        try:
            start = today.replace(year=today.year - n)
        except ValueError:
            start = today.replace(year=today.year - n, day=28)
        label = f'最近{n}年' if lang_key.startswith('zh') else f'Last {n} years'
        return _pack_candidate(f'last_{n}_years', label, start, today, earliest)
    return None


def infer_time_range_from_question(
    question: str,
    earliest_date: str,
    anchor: Optional[datetime] = None,
    lang: Optional[str] = None,
) -> Optional[dict]:
    """
    When the user already wrote a relative time phrase (e.g. 本年度 / 上周 / 上月),
    map it to concrete date_start/date_end so SQL generation can enforce a filter
    without going through clarification.
    """
    if not question or not question.strip():
        return None
    q = question.strip()
    if _EXEMPT_RE.search(q):
        return None

    lang_key = resolve_lang_key(lang)
    anchor = anchor or datetime.now()
    today = anchor.date()
    earliest = _parse_iso_date(earliest_date)
    presets = {
        p['field']: p
        for p in build_time_preset_candidates(earliest_date, anchor, lang=lang)
    }

    for pattern, field in _INFER_TIME_RULES:
        if not pattern.search(q):
            continue
        if field in presets:
            return dict(presets[field])
        if field == 'last_year':
            return _synthetic_calendar_year(earliest, today, lang_key, years_ago=1)
        if field == 'year_before_last':
            return _synthetic_calendar_year(earliest, today, lang_key, years_ago=2)
        if field == 'day_before_yesterday':
            return _synthetic_day_before_yesterday(earliest, today, lang_key)
        if field == 'this_quarter':
            return _synthetic_this_quarter(earliest, today, lang_key)
        if field == 'last_quarter':
            return _synthetic_last_quarter(earliest, today, lang_key)

    # Generic「最近N天/周/月/年」and English last/past N …
    m = _CN_DURATION_INFER_RE.search(q)
    if m:
        n = _parse_simple_cn_num(m.group(1))
        if n is not None:
            inferred = _infer_from_duration(n, m.group(2), earliest, today, lang_key)
            if inferred:
                return inferred
    m = _EN_DURATION_INFER_RE.search(q)
    if m:
        n = _parse_en_num(m.group(1))
        if n is not None:
            inferred = _infer_from_duration(n, m.group(2), earliest, today, lang_key)
            if inferred:
                return inferred

    return None


def question_time_range_xml(inferred: dict) -> str:
    return (
        '<time-range-from-question>\n'
        f'用户问题已表达时间范围：{inferred.get("label") or inferred.get("field")}\n'
        f'开始日期：{inferred.get("date_start") or ""}\n'
        f'结束日期：{inferred.get("date_end") or ""}\n'
        '必须在 SQL 的 WHERE（或等价子查询）中对时间字段使用上述起止日期过滤'
        '（推荐 >= 开始日期 AND <= 结束日期，或 BETWEEN）。\n'
        '</time-range-from-question>'
    )


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
