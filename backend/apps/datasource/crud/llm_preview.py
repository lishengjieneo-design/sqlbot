"""LLM preview sampling, masking, and M-Schema formatting helpers."""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_
from sqlmodel import Session

from apps.db.constant import DB
from apps.db.db import exec_sql
from apps.db.engine import get_engine_config
from apps.datasource.models.datasource import CoreDatasource, CoreField, CoreTable, DatasourceConf
from apps.datasource.utils.utils import aes_decrypt
from apps.datasource.crud.permission import (
    get_column_permission_fields,
    get_row_permission_filters,
    is_normal_user,
)
from sqlbot_xpack.permissions.models.ds_rules import DsRules
from common.core.deps import CurrentUser

SEMANTIC_ROLES = ('pk', 'metric', 'high_dim', 'low_dim', 'time')
ROLE_LABELS = {
    'pk': '主键',
    'metric': '指标',
    'high_dim': '高基维度',
    'low_dim': '低基维度',
    'time': '时间',
    'unknown': 'unknown',
}

_PHONE_RE = re.compile(r'(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)')
_ID_CARD_RE = re.compile(r'(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?!\d)')
_ID_CARD_15_RE = re.compile(r'(?<!\d)(\d{6})\d{6}(\d{3})(?!\d)')
_EMAIL_RE = re.compile(r'([A-Za-z0-9._%+-]{1,3})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})')


def normalize_role(role: Optional[str]) -> Optional[str]:
    if role is None or role == '':
        return None
    role = str(role).strip()
    if role not in SEMANTIC_ROLES:
        raise ValueError(f'invalid semantic_role: {role}')
    return role


def schema_role(role: Optional[str]) -> str:
    return role if role in SEMANTIC_ROLES else 'unknown'


def mask_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        s = str(value)
        # long digit-like ids (phone stored as number)
        if re.fullmatch(r'1[3-9]\d{9}', s):
            return s[:3] + '****' + s[-4:]
        return value
    if not isinstance(value, str):
        value = str(value)
    text = value
    text = _PHONE_RE.sub(r'\1****\2', text)
    text = _ID_CARD_RE.sub(r'\1********\2', text)
    text = _ID_CARD_15_RE.sub(r'\1******\2', text)
    text = _EMAIL_RE.sub(r'\1***\2', text)
    return text


def mask_row(row: dict) -> dict:
    return {k: mask_value(v) for k, v in (row or {}).items()}


def _quote_ident(ds_type: str, name: str) -> str:
    db = DB.get_db(ds_type)
    return f'{db.prefix}{name}{db.suffix}'


def _table_ref(ds: CoreDatasource, table: CoreTable) -> str:
    conf = (
        DatasourceConf(**json.loads(aes_decrypt(ds.configuration)))
        if ds.type != 'excel'
        else get_engine_config()
    )
    t = _quote_ident(ds.type, table.table_name)
    if ds.type in ('mysql', 'doris', 'starrocks', 'ck', 'es'):
        return t
    schema = conf.dbSchema if getattr(conf, 'dbSchema', None) else conf.database
    return f'{_quote_ident(ds.type, schema)}.{t}'


def _limit_clause(ds_type: str, n: int) -> str:
    if ds_type == 'sqlServer':
        return ''  # TOP used in select
    if ds_type == 'oracle':
        return ''  # ROWNUM wrapper
    return f' LIMIT {n}'


def _enabled_fields(
    session: Session,
    current_user: CurrentUser,
    table: CoreTable,
    fields: list[CoreField],
) -> list[CoreField]:
    f_list = [f for f in fields if f.checked]
    if is_normal_user(current_user):
        contain_rules = session.query(DsRules).all()
        f_list = get_column_permission_fields(
            session=session,
            current_user=current_user,
            table=table,
            fields=f_list,
            contain_rules=contain_rules,
        )
    return f_list or []


def _row_where(session: Session, current_user: CurrentUser, ds: CoreDatasource, table: CoreTable) -> str:
    if not is_normal_user(current_user):
        return ''
    filter_mapping = get_row_permission_filters(
        session=session, current_user=current_user, ds=ds, tables=None, single_table=table
    )
    if filter_mapping:
        where_str = filter_mapping[0].get('filter')
        if where_str:
            return ' WHERE ' + where_str
    return ''


def _exec_rows(ds: CoreDatasource, sql: str) -> list[dict]:
    res = exec_sql(ds, sql, True)
    return res.get('data') or []


def sample_row_limit(
    ds: CoreDatasource,
    table: CoreTable,
    field_names: list[str],
    where: str,
    limit: int = 10,
) -> list[dict]:
    cols = ', '.join(_quote_ident(ds.type, n) for n in field_names)
    table_ref = _table_ref(ds, table)
    if ds.type == 'sqlServer':
        sql = f'SELECT TOP {limit} {cols} FROM {table_ref}{where}'
    elif ds.type == 'oracle':
        sql = (
            f'SELECT * FROM (SELECT {cols} FROM {table_ref}{where}) '
            f'WHERE ROWNUM <= {limit}'
        )
    else:
        sql = f'SELECT {cols} FROM {table_ref}{where}{_limit_clause(ds.type, limit)}'
    rows = _exec_rows(ds, sql)
    return [mask_row(r) for r in rows]


def sample_low_dim_enums(
    ds: CoreDatasource,
    table: CoreTable,
    field_name: str,
    where: str,
    limit: int = 10,
) -> list[Any]:
    col = _quote_ident(ds.type, field_name)
    table_ref = _table_ref(ds, table)
    # No ORDER BY: DB default order. Avoids PG "DISTINCT + ORDER BY RANDOM()" errors.
    if ds.type == 'sqlServer':
        sql = f'SELECT DISTINCT TOP {limit} {col} FROM {table_ref}{where}'
    elif ds.type == 'oracle':
        sql = (
            f'SELECT * FROM (SELECT DISTINCT {col} FROM {table_ref}{where}) '
            f'WHERE ROWNUM <= {limit}'
        )
    else:
        sql = f'SELECT DISTINCT {col} FROM {table_ref}{where}{_limit_clause(ds.type, limit)}'
    rows = _exec_rows(ds, sql)
    values = []
    for row in rows:
        # single-column result; key may be field name or lowercased
        if not row:
            values.append(None)
            continue
        val = next(iter(row.values()))
        values.append(mask_value(val))
    return values


def sample_time_value(
    ds: CoreDatasource,
    table: CoreTable,
    field_name: str,
    where: str,
) -> Any:
    col = _quote_ident(ds.type, field_name)
    table_ref = _table_ref(ds, table)
    null_pred = f'{col} IS NOT NULL'
    if where:
        # where already has WHERE
        combined = f'{where} AND {null_pred}'
    else:
        combined = f' WHERE {null_pred}'
    if ds.type == 'sqlServer':
        sql = f'SELECT TOP 1 {col} FROM {table_ref}{combined}'
    elif ds.type == 'oracle':
        sql = (
            f'SELECT * FROM (SELECT {col} FROM {table_ref}{combined}) WHERE ROWNUM <= 1'
        )
    else:
        sql = f'SELECT {col} FROM {table_ref}{combined}{_limit_clause(ds.type, 1)}'
    rows = _exec_rows(ds, sql)
    if not rows:
        return None
    val = next(iter(rows[0].values()))
    return mask_value(val)


def refresh_llm_preview(
    session: Session,
    current_user: CurrentUser,
    ds_id: int,
    table_id: int,
) -> dict:
    ds = session.query(CoreDatasource).filter(CoreDatasource.id == ds_id).first()
    table = session.query(CoreTable).filter(
        and_(CoreTable.id == table_id, CoreTable.ds_id == ds_id)
    ).first()
    if not ds or not table:
        raise ValueError('table_not_found')

    fields = (
        session.query(CoreField)
        .filter(CoreField.table_id == table.id)
        .order_by(CoreField.field_index.asc())
        .all()
    )
    enabled = _enabled_fields(session, current_user, table, fields)
    where = _row_where(session, current_user, ds, table)

    field_names = [f.field_name for f in enabled]
    rows: list[dict] = []
    if field_names:
        try:
            rows = sample_row_limit(ds, table, field_names, where, 10)
        except Exception:
            rows = []

    enums: dict[str, list] = {}
    for f in enabled:
        if f.semantic_role == 'low_dim':
            try:
                enums[f.field_name] = sample_low_dim_enums(ds, table, f.field_name, where, 10)
            except Exception:
                enums[f.field_name] = []

    time_samples: dict[str, Any] = {}
    for f in enabled:
        if f.semantic_role == 'time':
            try:
                time_samples[f.field_name] = sample_time_value(ds, table, f.field_name, where)
            except Exception:
                time_samples[f.field_name] = None

    payload = {
        'version': 1,
        'sampled_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
        'rows': rows,
        'enums': enums,
        'time_samples': time_samples,
    }
    table.llm_preview = payload
    session.add(table)
    session.commit()
    session.refresh(table)
    return payload


def clear_table_llm_preview(session: Session, table_id: int, *, commit: bool = True) -> None:
    table = session.query(CoreTable).filter(CoreTable.id == table_id).first()
    if table and table.llm_preview is not None:
        table.llm_preview = None
        session.add(table)
        if commit:
            session.commit()


def format_field_schema_line(field: CoreField, llm_preview: Optional[dict] = None) -> str:
    role = schema_role(field.semantic_role)
    comment = (field.custom_comment or '').strip()
    parts = [f'{field.field_name}:{field.field_type}']
    if comment:
        parts.append(comment)
    parts.append(role)

    preview = llm_preview or {}
    enums = preview.get('enums') or {}
    time_samples = preview.get('time_samples') or {}

    if role == 'low_dim' and field.field_name in enums:
        # examples:['a','b',null] — keep JSON-ish for null
        examples = enums[field.field_name]
        rendered = []
        for v in examples:
            if v is None:
                rendered.append('null')
            elif isinstance(v, (int, float, bool)):
                rendered.append(str(v))
            else:
                rendered.append(json.dumps(str(v), ensure_ascii=False))
        parts.append(f"examples:[{','.join(rendered)}]")
    elif role == 'time' and field.field_name in time_samples:
        tv = time_samples.get(field.field_name)
        if tv is None:
            parts.append("example:null")
        else:
            parts.append(f"example:{json.dumps(str(tv), ensure_ascii=False)}")

    return '(' + ', '.join(parts) + ')'


def format_llm_preview_block(llm_preview: Optional[dict], field_names: Optional[list[str]] = None) -> str:
    if not llm_preview:
        return ''
    rows = llm_preview.get('rows') or []
    enums = llm_preview.get('enums') or {}
    time_samples = llm_preview.get('time_samples') or {}
    if not rows and not enums and not time_samples:
        return ''

    lines = ['# LLM-Preview']
    if rows:
        # stable column order from first row or provided names
        cols = field_names or list(rows[0].keys())
        # prefer intersection with row keys, keep order
        if rows:
            row_keys = list(rows[0].keys())
            # case-insensitive match
            key_map = {k.lower(): k for k in row_keys}
            ordered = []
            for c in cols:
                k = key_map.get(c.lower())
                if k:
                    ordered.append(k)
            for k in row_keys:
                if k not in ordered:
                    ordered.append(k)
            cols = ordered
        lines.append('rows:')
        lines.append(','.join(cols))
        for row in rows:
            cells = []
            for c in cols:
                v = row.get(c)
                if v is None:
                    cells.append('null')
                else:
                    s = str(v).replace('\n', ' ').replace(',', ' ')
                    cells.append(s)
            lines.append(','.join(cells))

    if enums:
        enum_parts = []
        for k, vals in enums.items():
            rendered = []
            for v in vals:
                if v is None:
                    rendered.append('null')
                else:
                    rendered.append(json.dumps(str(v), ensure_ascii=False))
            enum_parts.append(f"{k}=[{','.join(rendered)}]")
        lines.append('enums: ' + '; '.join(enum_parts))

    if time_samples:
        t_parts = []
        for k, v in time_samples.items():
            if v is None:
                t_parts.append(f'{k}=null')
            else:
                t_parts.append(f'{k}={json.dumps(str(v), ensure_ascii=False)}')
        lines.append('time: ' + '; '.join(t_parts))

    return '\n'.join(lines) + '\n'
