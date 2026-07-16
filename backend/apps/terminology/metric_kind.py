"""Terminology metric_kind enum and helpers."""
from __future__ import annotations

from enum import Enum


class MetricKind(str, Enum):
    FLOW = 'flow'
    BALANCE = 'balance'
    ORG_DIMENSION = 'org_dimension'
    PRODUCT_DIMENSION = 'product_dimension'


ACTIVE_METRIC_KINDS = frozenset({MetricKind.FLOW.value, MetricKind.BALANCE.value})

SCENARIO_NONE = 'none'
SCENARIO_FLOW_ONLY = 'flow_only'
SCENARIO_BALANCE_ONLY = 'balance_only'
SCENARIO_MIXED = 'mixed'

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


def normalize_metric_kind(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in _LABEL_TO_VALUE:
        return _LABEL_TO_VALUE[lowered]
    if text in _LABEL_TO_VALUE:
        return _LABEL_TO_VALUE[text]
    return None


def metric_kind_label_zh(value: str) -> str:
    return _VALUE_LABELS_ZH.get(value, value)
