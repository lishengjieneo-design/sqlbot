"""Balance-type metric time semantics in user questions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from apps.chat.time_range_prefilter import (
    _CN_RELATIVE_DURATION,
    _DATE_PATTERNS,
    _EN_RANGE_RE,
    _EN_RELATIVE_TIME_RE,
    _RANGE_RE,
    _RELATIVE_TIME_RE,
    question_has_explicit_time_constraint,
)

_CN_RELATIVE_DURATION_RE = re.compile(_CN_RELATIVE_DURATION, re.I)

BALANCE_RANGE_ERROR = '余额型指标不能取时间范围，请提供一个时间节点（如：昨天、2024-06-01）。'

_MULTI_POINT_JOIN_RE = re.compile(r'和|、|与|以及|及')
_SINGLE_POINT_RE = re.compile(
    r'今天|今日|昨天|昨日|前天|'
    r'\d{4}[-/年]\d{1,2}[-/月]\d{1,2}|'
    r'\d{4}[-/]\d{1,2}[-/]\d{1,2}|'
    r'\d{4}年\d{1,2}月\d{1,2}日?',
    re.I,
)


class BalanceTimeKind(str, Enum):
    NONE = 'none'
    POINT = 'point'
    RANGE = 'range'
    MULTI_POINT = 'multi_point'


@dataclass
class BalanceTimeResult:
    kind: BalanceTimeKind
    error_message: Optional[str] = None
    llm_hint: Optional[str] = None


def _count_date_literals(question: str) -> int:
    count = 0
    for pat in _DATE_PATTERNS:
        count += len(pat.findall(question))
    count += len(_SINGLE_POINT_RE.findall(question))
    return count


def _is_time_range(question: str) -> bool:
    q = question.strip()
    if _SINGLE_POINT_RE.search(q) and not _CN_RELATIVE_DURATION_RE.search(q):
        if not _RANGE_RE.search(q) and not _EN_RANGE_RE.search(q) and _count_date_literals(q) <= 1:
            return False
    if _CN_RELATIVE_DURATION_RE.search(q):
        return True
    if _RELATIVE_TIME_RE.search(q) and not _SINGLE_POINT_RE.fullmatch(q):
        # Relative durations like 本月 still count as range for balance-only rules.
        if re.search(r'本月|这个月|上月|上个月|本季度|上季度|今年|去年|本周|这周|上周', q):
            return True
    if _EN_RELATIVE_TIME_RE.search(q):
        return True
    if _RANGE_RE.search(q):
        return True
    if _EN_RANGE_RE.search(q):
        return True
    if re.search(r'至|到|between|from\s+.+\s+to', q, re.I) and _count_date_literals(q) >= 2:
        return True
    return False


def _is_multi_point(question: str) -> bool:
    q = question.strip()
    if _count_date_literals(q) >= 2 and _MULTI_POINT_JOIN_RE.search(q):
        return True
    if len(re.findall(r'和|、', q)) >= 1 and _count_date_literals(q) >= 2:
        return True
    return False


def _is_single_point(question: str) -> bool:
    q = question.strip()
    if question_has_explicit_time_constraint(q):
        if _is_time_range(q) or _is_multi_point(q):
            return False
        return True
    return bool(_SINGLE_POINT_RE.search(q))


def classify_balance_time(question: str) -> BalanceTimeResult:
    if not question or not question.strip():
        return BalanceTimeResult(BalanceTimeKind.NONE)

    q = question.strip()

    if _is_multi_point(q):
        return BalanceTimeResult(
            BalanceTimeKind.MULTI_POINT,
            llm_hint=f'用户问题中包含多个时间节点，请在 SQL 中分别处理：{q}',
        )

    if _is_time_range(q):
        return BalanceTimeResult(BalanceTimeKind.RANGE, error_message=BALANCE_RANGE_ERROR)

    if _is_single_point(q):
        return BalanceTimeResult(
            BalanceTimeKind.POINT,
            llm_hint=f'用户指定的余额查询时点（请据此过滤或选取快照）：{q}',
        )

    return BalanceTimeResult(BalanceTimeKind.NONE)


MIXED_METRIC_KIND_HINT = (
    '<metric-kind-hint>\n'
    '本次问题同时涉及发生型与余额型指标。\n'
    '- 发生型指标：使用用户问题中的时间范围。\n'
    '- 余额型指标：请自行判断取哪一个时点。\n'
    '</metric-kind-hint>'
)
