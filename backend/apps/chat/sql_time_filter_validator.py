"""Validate that generated SQL includes time-related filter predicates.

Hard rule (table semantic roles):
- If any table used in the SQL has fields with semantic_role=time, a time filter is required.
- If none of the used tables have a time-role field, time filter is not required.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable, Optional

import sqlglot
from sqlglot import exp

if TYPE_CHECKING:
    from sqlmodel import Session

# m-schema field line: (field_name:type, description...)
_SCHEMA_FIELD_RE = re.compile(
    r'\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:[^,)]*(?:,\s*([^)]*))?\)',
    re.MULTILINE,
)

_TIME_FIELD_SUFFIXES = ('_time', '_date', '_dt', '_month', '_year')
_TIME_FIELD_EXACT = frozenset({
    'trade_date', 'biz_date', 'dt', 'date', 'created_at', 'updated_at',
    'open_time', 'close_time', 'settle_date', 'report_date',
    'month', 'year', 'year_month', 'ym', 'stat_month', 'biz_month',
    'report_month', 'data_month', 'period', 'period_month',
})

_DATE_LITERAL_RE = re.compile(
    r"'\d{4}-\d{2}-\d{2}'|"
    r"'\d{4}/\d{2}/\d{2}'|"
    r"'\d{4}-\d{2}'|"  # year-month partitions, e.g. '2026-01'
    r"'\d{4}/\d{2}'|"
    r'\d{4}-\d{2}-\d{2}|'
    r'\d{4}/\d{2}/\d{2}|'
    r'\d{4}-\d{2}(?!\d)|'
    r'\d{4}/\d{2}(?!\d)',
)
_TIME_FUNC_RE = re.compile(
    r'\b(CURRENT_DATE|CURRENT_TIMESTAMP|NOW\s*\(|CURDATE\s*\(|SYSDATE|'
    r'DATE_TRUNC|DATE_ADD|DATE_SUB|INTERVAL|TO_DATE|STR_TO_DATE|'
    r'EXTRACT\s*\(|YEAR\s*\(|MONTH\s*\(|DATE_FORMAT)\b',
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
    """Fallback: infer time-like fields from m-schema text by name heuristics."""
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


def extract_sql_table_names(sql: str) -> set[str]:
    """Return bare table names referenced in SQL (schema prefix stripped)."""
    if not sql or not sql.strip():
        return set()
    names: set[str] = set()
    try:
        parsed = sqlglot.parse_one(sql, read=None)
    except Exception:
        return names
    if not parsed:
        return names
    for table in parsed.find_all(exp.Table):
        name = table.name
        if not name:
            continue
        bare = str(name).strip().strip('"').strip("'")
        if '.' in bare:
            bare = bare.split('.')[-1]
        if bare:
            names.add(bare.lower())
    return names


def _normalize_table_name(name: str) -> str:
    bare = (name or '').strip().strip('"').strip("'")
    if '.' in bare:
        bare = bare.split('.')[-1]
    return bare.lower()


def resolve_time_role_fields_for_tables(
    session: 'Session',
    ds_id: Optional[int],
    table_names: Iterable[str],
) -> tuple[bool, list[str]]:
    """
    Look up semantic_role=time fields for the given tables in a datasource.

    Returns:
        (matched_any_table, time_field_names)
        - matched_any_table=False → callers should fall back to schema heuristics
        - matched_any_table=True and empty fields → time filter not required
        - matched_any_table=True and non-empty fields → time filter required
    """
    from apps.datasource.models.datasource import CoreField, CoreTable

    if not ds_id:
        return False, []
    wanted = {_normalize_table_name(n) for n in table_names if n}
    if not wanted:
        return False, []

    tables = session.query(CoreTable).filter(CoreTable.ds_id == ds_id).all()
    matched_ids: list[int] = []
    for table in tables:
        tname = _normalize_table_name(table.table_name or '')
        if tname in wanted:
            matched_ids.append(table.id)
    if not matched_ids:
        return False, []

    fields = (
        session.query(CoreField)
        .filter(
            CoreField.table_id.in_(matched_ids),
            CoreField.semantic_role == 'time',
            CoreField.checked == True,  # noqa: E712
        )
        .all()
    )
    seen: set[str] = set()
    names: list[str] = []
    for field in fields:
        key = (field.field_name or '').lower()
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(field.field_name)
    return True, names


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
    *,
    required_time_fields: Optional[list[str]] = None,
    tables_matched: bool = False,
) -> tuple[bool, str]:
    """
    Check whether SQL has an adequate time filter.

    When tables_matched=True:
      - empty required_time_fields → pass (no time-role fields on used tables)
      - non-empty required_time_fields → require a time filter
    Otherwise fall back to name heuristics on schema_text.
    """
    if not sql or not sql.strip():
        return False, 'SQL 为空'

    if tables_matched:
        if not required_time_fields:
            return True, ''
        time_fields = {f.lower() for f in required_time_fields}
    else:
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

    hint_fields = required_time_fields or sorted(time_fields)
    field_hint = '、'.join(hint_fields) if hint_fields else '时间字段'
    if resolved_time:
        label = resolved_time.get('label') or resolved_time.get('free_text') or ''
        return False, (
            f'SQL 未包含时间范围过滤条件。用户已确认时间：{label}。'
            f'请在 WHERE 或子查询中对时间字段（{field_hint}）使用 >= / BETWEEN 等条件。'
        )
    return False, (
        f'SQL 未包含时间范围过滤条件，所用表配置了时间角色字段（{field_hint}），'
        f'请在 WHERE 中对其添加过滤。'
    )
