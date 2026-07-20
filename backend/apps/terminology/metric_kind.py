"""Terminology metric_kind enum and helpers."""
from __future__ import annotations

import re
from enum import Enum
from typing import Iterable


class MetricKind(str, Enum):
    FLOW = 'flow'
    BALANCE = 'balance'
    ORG_DIMENSION = 'org_dimension'
    PRODUCT_DIMENSION = 'product_dimension'


ACTIVE_METRIC_KINDS = frozenset({MetricKind.FLOW.value, MetricKind.BALANCE.value})
BUILTIN_METRIC_KIND_CODES = frozenset(m.value for m in MetricKind)

SCENARIO_NONE = 'none'
SCENARIO_FLOW_ONLY = 'flow_only'
SCENARIO_BALANCE_ONLY = 'balance_only'
SCENARIO_MIXED = 'mixed'

CODE_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,31}$')

_LABEL_TO_VALUE: dict[str, str] = {
    'flow': MetricKind.FLOW.value,
    'balance': MetricKind.BALANCE.value,
    'org_dimension': MetricKind.ORG_DIMENSION.value,
    'product_dimension': MetricKind.PRODUCT_DIMENSION.value,
    '发生型指标': MetricKind.FLOW.value,
    '发生型': MetricKind.FLOW.value,
    '余额型指标': MetricKind.BALANCE.value,
    '余额型': MetricKind.BALANCE.value,
    '组织维度': MetricKind.ORG_DIMENSION.value,
    '产品维度': MetricKind.PRODUCT_DIMENSION.value,
}

_VALUE_LABELS_ZH: dict[str, str] = {
    MetricKind.FLOW.value: '发生型指标',
    MetricKind.BALANCE.value: '余额型指标',
    MetricKind.ORG_DIMENSION.value: '组织维度',
    MetricKind.PRODUCT_DIMENSION.value: '产品维度',
}


def metric_kind_values() -> frozenset[str]:
    return frozenset(m.value for m in MetricKind)


def is_valid_metric_kind_code(code: str | None) -> bool:
    if not code:
        return False
    return bool(CODE_PATTERN.match(code.strip()))


def normalize_metric_kind(raw: str | None, extras: Iterable[tuple[str, str]] | None = None) -> str | None:
    """Resolve raw code/label to a stable code.

    ``extras`` is an optional iterable of ``(code, label)`` from DB options.
    Built-in Chinese aliases remain for Excel compatibility.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    label_map: dict[str, str] = dict(_LABEL_TO_VALUE)
    if extras:
        for code, label in extras:
            if not code:
                continue
            code_s = str(code).strip()
            label_map[code_s.lower()] = code_s
            label_map[code_s] = code_s
            if label:
                label_s = str(label).strip()
                if label_s:
                    label_map[label_s] = code_s
                    label_map[label_s.lower()] = code_s

    lowered = text.lower()
    if lowered in label_map:
        return label_map[lowered]
    if text in label_map:
        return label_map[text]
    return None


def metric_kind_label_zh(value: str, label_by_code: dict[str, str] | None = None) -> str:
    if label_by_code and value in label_by_code:
        return label_by_code[value]
    return _VALUE_LABELS_ZH.get(value, value)
