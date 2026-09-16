"""BlueCard layout resolver (P0/P2) — mirrors frontend resultLayout.ts + visualizability."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

CURRENCY_PREFIX = re.compile(r'^[$¥€£]\s*')
PERCENT_SUFFIX = re.compile(r'%$')
ID_FIELD_RE = re.compile(
    r'(^id$|_id$|账号|账户|帐户|客户号|login|account|uid|uuid|mt4|mt5|ticket|order_?id)',
    re.I,
)
# Dimension-like / category / time fields for chart X axis
DIM_FIELD_RE = re.compile(
    r'(month|year|week|date|day|time|period|类别|分类|类型|名称|name|region|area|'
    r'国家|country|产品|product|渠道|channel|代理|agent|email|邮箱|币种|currency|'
    r'ib|team|团队|status|状态)',
    re.I,
)


def is_numeric_like(value: Any) -> bool:
    if value is None or value == '':
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    raw = str(value).strip()
    if not raw:
        return False
    cleaned = CURRENCY_PREFIX.sub('', raw).replace(',', '')
    cleaned = PERCENT_SUFFIX.sub('', cleaned).strip()
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _ordered_fields(fields: Optional[list[str]], row: dict) -> list[str]:
    if fields:
        return list(fields)
    return list(row.keys())


def classify_columns(
    fields: Optional[list[str]],
    rows: list[dict],
) -> tuple[list[str], list[str]]:
    """Return (numeric_cols, text_cols) based on first non-empty sample values."""
    if not rows:
        return [], []
    ordered = _ordered_fields(fields, rows[0])
    # Prefer first row with any values; fall back to first
    row = rows[0]
    for candidate in rows[:5]:
        if any(v is not None and v != '' for v in candidate.values()):
            row = candidate
            break

    numeric: list[str] = []
    text: list[str] = []
    for col in ordered:
        v = row.get(col)
        if v is None or v == '':
            # look ahead a few rows
            for r in rows[:10]:
                if r.get(col) is not None and r.get(col) != '':
                    v = r.get(col)
                    break
        if is_numeric_like(v):
            numeric.append(col)
        elif v is not None and str(v).strip() != '':
            text.append(col)
    return numeric, text


def resolve_bluecard_layout(
    fields: Optional[list[str]],
    rows: Optional[list[dict]],
) -> str:
    """Mirror frontend resolveBluecardLayout. Multi-row returns 'chart' (generic multi path)."""
    if not rows:
        return 'empty'
    if len(rows) > 1:
        return 'chart'

    row = rows[0] or {}
    ordered = _ordered_fields(fields, row)
    numeric_cols, text_cols = classify_columns(ordered, rows)

    if len(numeric_cols) == 1 and len(text_cols) == 0:
        return 'hero'
    if 2 <= len(numeric_cols) <= 5 and len(text_cols) <= 1:
        return 'metrics'
    if len(numeric_cols) == 1 and len(text_cols) <= 1 and len(ordered) <= 2:
        return 'hero'
    if 1 <= len(numeric_cols) <= 5 and len(text_cols) == 0:
        return 'metrics'
    return 'profile'


def is_chart_visualizable(
    fields: Optional[list[str]],
    rows: Optional[list[dict]],
) -> bool:
    """
    Multi-row is chartable when there is at least one measure and one dimension-like
    (or a single measure with an indexable category column).
    Wide text dumps / many ID columns → not visualizable → force table.
    """
    if not rows or len(rows) <= 1:
        return False

    numeric_cols, text_cols = classify_columns(fields, rows)
    if not numeric_cols:
        return False

    # Too many columns of mixed text → prefer table (raw listing)
    ordered = _ordered_fields(fields, rows[0])
    if len(ordered) >= 8 and len(text_cols) >= 4:
        return False

    # Need a category / time dimension for X, or exactly one text col
    dim_cols = [c for c in text_cols if DIM_FIELD_RE.search(c) or not ID_FIELD_RE.search(c)]
    # Exclude pure IDs from dimensions
    dim_cols = [c for c in dim_cols if not ID_FIELD_RE.search(c)]

    if dim_cols:
        return True
    # Numeric-only multi-row with an ordered field that looks like month/year in values
    if len(numeric_cols) >= 1 and len(text_cols) == 1:
        return not ID_FIELD_RE.search(text_cols[0])
    if len(numeric_cols) >= 1 and len(text_cols) == 0:
        # e.g. only measures across rows without labels — still chartable as index series? prefer table
        return False
    return False


def build_table_chart_config(
    fields: Optional[list[str]],
    rows: Optional[list[dict]],
    title: str = '',
) -> dict:
    """Synthesize a chart JSON of type table (no LLM)."""
    ordered = _ordered_fields(fields, (rows or [{}])[0] if rows else {})
    columns = [{'name': f, 'value': (f or '').lower()} for f in ordered]
    return {
        'type': 'table',
        'title': title or '查询结果',
        'columns': columns,
    }


@dataclass
class BluecardPlan:
    layout: str  # empty|hero|metrics|profile|chart|table
    skip_chart: bool
    force_table: bool
    chart_type: Optional[str] = None  # suggested override: table|line|...
    row_count: int = 0


def plan_bluecard_result(
    fields: Optional[list[str]],
    rows: Optional[list[dict]],
    *,
    preferred_chart_type: Optional[str] = None,
    title: str = '',
) -> BluecardPlan:
    """
    P2 decision:
    - empty / single-row card layouts → skip chart LLM
    - multi-row not visualizable → force table config (no chart LLM)
    - multi-row visualizable → keep LLM chart (optionally prefer preferred_chart_type)
    """
    rows = rows or []
    row_count = len(rows)
    layout = resolve_bluecard_layout(fields, rows)

    if layout in ('empty', 'hero', 'metrics', 'profile'):
        return BluecardPlan(
            layout=layout,
            skip_chart=True,
            force_table=False,
            chart_type=None,
            row_count=row_count,
        )

    # multi-row path (layout == 'chart')
    if not is_chart_visualizable(fields, rows):
        return BluecardPlan(
            layout='table',
            skip_chart=True,
            force_table=True,
            chart_type='table',
            row_count=row_count,
        )

    ctype = (preferred_chart_type or '').strip().lower() or None
    if ctype == 'table':
        # LLM asked for table even though visualizable — honor it
        return BluecardPlan(
            layout='table',
            skip_chart=True,
            force_table=True,
            chart_type='table',
            row_count=row_count,
        )

    return BluecardPlan(
        layout='chart',
        skip_chart=False,
        force_table=False,
        chart_type=ctype,
        row_count=row_count,
    )
