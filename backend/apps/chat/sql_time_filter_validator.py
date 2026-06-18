"""Validate that generated SQL includes time-related filter predicates."""
from __future__ import annotations

import re
from typing import Optional

import sqlglot
from sqlglot import exp

from apps.chat.id_schema_prefilter import _SCHEMA_FIELD_RE

_TIME_FIELD_SUFFIXES = ('_time', '_date', '_dt')
_TIME_FIELD_EXACT = frozenset({
    'trade_date', 'biz_date', 'dt', 'date', 'created_at', 'updated_at',
    'open_time', 'close_time', 'settle_date', 'report_date',
})

_DATE_LITERAL_RE = re.compile(
    r"'\d{4}-\d{2}-\d{2}|'\d{4}/\d{2}/\d{2}|"
    r'\d{4}-\d{2}-\d{2}|\d{4}/\d{2}/\d{2}',
)
_TIME_FUNC_RE = re.compile(
    r'\b(CURRENT_DATE|CURRENT_TIMESTAMP|NOW\s*\(|CURDATE\s*\(|SYSDATE|'
    r'DATE_TRUNC|DATE_ADD|DATE_SUB|INTERVAL|TO_DATE|STR_TO_DATE)\b',
    re.I,
)
_WHERE_TIME_OP_RE = re.compile(
    r'\bWHERE\b.+(?:BETWEEN|>=|<=|>|<|=)\s*',
    re.I | re.S,
)


def is_time_like_field(field_name: str) -> bool:
    n = field_name.lower()
    if n in _TIME_FIELD_EXACT:
        return True
    return any(n.endswith(s) for s in _TIME_FIELD_SUFFIXES)


def parse_time_fields_from_schema(schema_text: str) -> list[str]:
    if not schema_text:
        return []
    seen: set[str] = set()
    fields: list[str] = []
    for match in _SCHEMA_FIELD_RE.finditer(schema_text):
        name = match.group(1)
        if not is_time_like_field(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        fields.append(name)
    return fields


def _column_name(node: exp.Expression) -> Optional[str]:
    if isinstance(node, exp.Column):
        parts = [p.name for p in node.parts if p.name]
        return parts[-1].lower() if parts else None
    if hasattr(node, 'name') and node.name:
        return str(node.name).lower()
    return None


def _expr_references_time_field(node: exp.Expression, time_fields: set[str]) -> bool:
    for col in node.find_all(exp.Column):
        name = _column_name(col)
        if name and name in time_fields:
            return True
    return False


def _expr_has_time_semantics(node: exp.Expression, time_fields: set[str]) -> bool:
    if _expr_references_time_field(node, time_fields):
        return True
    sql_frag = node.sql()
    if _DATE_LITERAL_RE.search(sql_frag):
        return True
    if _TIME_FUNC_RE.search(sql_frag):
        return True
    return False


def _where_clauses_have_time_filter(expression: exp.Expression, time_fields: set[str]) -> bool:
    for where in expression.find_all(exp.Where):
        if _expr_has_time_semantics(where.this, time_fields):
            return True
    for having in expression.find_all(exp.Having):
        if _expr_has_time_semantics(having.this, time_fields):
            return True
    return False


def sql_has_time_filter(
    sql: str,
    schema_text: str = '',
    resolved_time: Optional[dict] = None,
) -> tuple[bool, str]:
    if not sql or not sql.strip():
        return False, 'SQL 为空'
    time_fields = {f.lower() for f in parse_time_fields_from_schema(schema_text)}
    try:
        parsed = sqlglot.parse_one(sql, read=None)
        if parsed and _where_clauses_have_time_filter(parsed, time_fields):
            return True, ''
    except Exception:
        pass

    sql_upper = sql.upper()
    if time_fields:
        for field in time_fields:
            if field.upper() in sql_upper and re.search(
                rf'\b{re.escape(field)}\b\s*(?:>=|<=|>|<|BETWEEN|=)',
                sql,
                re.I,
            ):
                return True, ''
    if _DATE_LITERAL_RE.search(sql) and _WHERE_TIME_OP_RE.search(sql):
        return True, ''
    if _TIME_FUNC_RE.search(sql) and re.search(r'\bWHERE\b', sql, re.I):
        return True, ''

    if resolved_time:
        label = resolved_time.get('label') or resolved_time.get('free_text') or ''
        return False, (
            f'SQL 未包含时间范围过滤条件。用户已确认时间：{label}。'
            f'请在 WHERE 或子查询中对时间字段使用 >= / BETWEEN 等条件。'
        )
    return False, 'SQL 未包含时间范围过滤条件，请在 WHERE 中对时间字段添加过滤。'
