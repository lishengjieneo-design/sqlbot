"""Locale-aware copy for time-range clarification (UI + stored labels)."""
from __future__ import annotations

from typing import Optional

_PRESET_FIELDS = (
    'all_time',
    'today',
    'yesterday',
    'this_week',
    'last_week',
    'this_month',
    'last_month',
    'this_year',
    'last_7_days',
    'last_30_days',
)

_LABELS: dict[str, dict[str, str]] = {
    'zh': {
        'all_time': '全部',
        'today': '今天',
        'yesterday': '昨天',
        'this_week': '本周',
        'last_week': '上周',
        'this_month': '本月',
        'last_month': '上月',
        'this_year': '本年',
        'last_7_days': '最近7天',
        'last_30_days': '最近30天',
    },
    'en': {
        'all_time': 'All',
        'today': 'Today',
        'yesterday': 'Yesterday',
        'this_week': 'This week',
        'last_week': 'Last week',
        'this_month': 'This month',
        'last_month': 'Last month',
        'this_year': 'This year',
        'last_7_days': 'Last 7 days',
        'last_30_days': 'Last 30 days',
    },
    'zh-tw': {
        'all_time': '全部',
        'today': '今天',
        'yesterday': '昨天',
        'this_week': '本週',
        'last_week': '上週',
        'this_month': '本月',
        'last_month': '上月',
        'this_year': '本年',
        'last_7_days': '最近7天',
        'last_30_days': '最近30天',
    },
    'ko': {
        'all_time': '전체',
        'today': '오늘',
        'yesterday': '어제',
        'this_week': '이번 주',
        'last_week': '지난 주',
        'this_month': '이번 달',
        'last_month': '지난 달',
        'this_year': '올해',
        'last_7_days': '최근 7일',
        'last_30_days': '최근 30일',
    },
}

_PROMPTS = {
    'zh': '请补充查询的时间范围',
    'en': 'Please specify the query time range',
    'zh-tw': '請補充查詢的時間範圍',
    'ko': '조회할 시간 범위를 선택해 주세요',
}

_DATA_HINTS = {
    'zh': '最早支持{date}之后的数据',
    'en': 'Data is available from {date} onward',
    'zh-tw': '最早支援 {date} 之後的資料',
    'ko': '{date} 이후 데이터를 조회할 수 있습니다',
}

_VALIDATION = {
    'zh': {
        'pick_date': '请选择日期或日期范围',
        'bad_format': '日期格式无效',
        'end_before_start': '结束日期不能早于开始日期',
        'before_earliest': '起始日期不能早于 {date}',
    },
    'en': {
        'pick_date': 'Please select a date or date range',
        'bad_format': 'Invalid date format',
        'end_before_start': 'End date cannot be earlier than start date',
        'before_earliest': 'Start date cannot be earlier than {date}',
    },
    'zh-tw': {
        'pick_date': '請選擇日期或日期範圍',
        'bad_format': '日期格式無效',
        'end_before_start': '結束日期不能早於開始日期',
        'before_earliest': '起始日期不能早於 {date}',
    },
    'ko': {
        'pick_date': '날짜 또는 기간을 선택해 주세요',
        'bad_format': '날짜 형식이 올바르지 않습니다',
        'end_before_start': '종료일은 시작일보다 이를 수 없습니다',
        'before_earliest': '시작일은 {date}보다 이를 수 없습니다',
    },
}


def resolve_lang_key(lang: Optional[str] = None) -> str:
    """Map user locale / chat_question.lang to a supported key."""
    if not lang:
        return 'zh'
    raw = str(lang).strip().lower()
    if raw.startswith('en') or '英文' in lang or raw == 'english':
        return 'en'
    if raw.startswith('zh-tw') or raw.startswith('zh_tw') or '繁体' in lang or '繁體' in lang:
        return 'zh-tw'
    if raw.startswith('ko') or '韩' in lang or '韓' in lang:
        return 'ko'
    if raw.startswith('zh'):
        return 'zh'
    return 'zh'


def preset_label(field: str, lang_key: Optional[str] = None) -> str:
    key = resolve_lang_key(lang_key)
    labels = _LABELS.get(key) or _LABELS['zh']
    return labels.get(field, field)


def time_range_prompt(lang_key: Optional[str] = None) -> str:
    key = resolve_lang_key(lang_key)
    return _PROMPTS.get(key) or _PROMPTS['zh']


def time_data_hint(earliest_display: str, lang_key: Optional[str] = None) -> str:
    key = resolve_lang_key(lang_key)
    template = _DATA_HINTS.get(key) or _DATA_HINTS['zh']
    return template.format(date=earliest_display)


def range_sep(lang_key: Optional[str] = None) -> str:
    key = resolve_lang_key(lang_key)
    return '至' if key.startswith('zh') else 'to'


def validation_message(code: str, lang_key: Optional[str] = None, **kwargs: str) -> str:
    key = resolve_lang_key(lang_key)
    messages = _VALIDATION.get(key) or _VALIDATION['zh']
    template = messages.get(code, code)
    return template.format(**kwargs)


def all_preset_labels(lang_key: Optional[str] = None) -> dict[str, str]:
    key = resolve_lang_key(lang_key)
    labels = _LABELS.get(key) or _LABELS['zh']
    return {field: labels[field] for field in _PRESET_FIELDS if field in labels}
