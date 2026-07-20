"""CRUD for configurable terminology metric_kind options."""
from __future__ import annotations

import datetime
from typing import List

from sqlalchemy import and_, delete, func, select

from apps.terminology.metric_kind import (
    BUILTIN_METRIC_KIND_CODES,
    MetricKind,
    is_valid_metric_kind_code,
    normalize_metric_kind,
)
from apps.terminology.models.terminology_model import (
    Terminology,
    TerminologyMetricKind,
    TerminologyMetricKindInfo,
)
from common.core.deps import SessionDep, Trans


def _to_info(row: TerminologyMetricKind) -> TerminologyMetricKindInfo:
    return TerminologyMetricKindInfo(
        id=row.id,
        code=row.code,
        label=row.label,
        sort_order=row.sort_order if row.sort_order is not None else 0,
        enabled=bool(row.enabled) if row.enabled is not None else True,
        builtin=bool(row.builtin) if row.builtin is not None else False,
        create_time=row.create_time,
    )


def list_metric_kinds(session: SessionDep, oid: int, enabled_only: bool = False) -> List[TerminologyMetricKindInfo]:
    ensure_builtin_metric_kinds(session, oid)
    conditions = [TerminologyMetricKind.oid == oid]
    if enabled_only:
        conditions.append(TerminologyMetricKind.enabled.is_(True))
    stmt = (
        select(TerminologyMetricKind)
        .where(and_(*conditions))
        .order_by(TerminologyMetricKind.sort_order.asc(), TerminologyMetricKind.id.asc())
    )
    rows = session.execute(stmt).scalars().all()
    return [_to_info(r) for r in rows]


def get_metric_kind_extras(session: SessionDep, oid: int) -> list[tuple[str, str]]:
    ensure_builtin_metric_kinds(session, oid)
    stmt = select(TerminologyMetricKind.code, TerminologyMetricKind.label).where(
        TerminologyMetricKind.oid == oid
    )
    return [(str(c), str(l or '')) for c, l in session.execute(stmt).all()]


def get_metric_kind_label_map(session: SessionDep, oid: int) -> dict[str, str]:
    return {code: label for code, label in get_metric_kind_extras(session, oid)}


def ensure_builtin_metric_kinds(session: SessionDep, oid: int) -> None:
    """Seed builtin kinds for an oid if missing (new workspace)."""
    existing = set(
        session.execute(
            select(TerminologyMetricKind.code).where(TerminologyMetricKind.oid == oid)
        ).scalars().all()
    )
    seeds = [
        (MetricKind.FLOW.value, '发生型指标', 10),
        (MetricKind.BALANCE.value, '余额型指标', 20),
        (MetricKind.ORG_DIMENSION.value, '组织维度', 30),
        (MetricKind.PRODUCT_DIMENSION.value, '产品维度', 40),
    ]
    missing = [s for s in seeds if s[0] not in existing]
    if not missing:
        return
    now = datetime.datetime.now()
    for code, label, sort_order in missing:
        session.add(
            TerminologyMetricKind(
                oid=oid,
                code=code,
                label=label,
                sort_order=sort_order,
                enabled=True,
                builtin=True,
                create_time=now,
            )
        )
    session.commit()


def create_or_update_metric_kind(
    session: SessionDep, info: TerminologyMetricKindInfo, oid: int, trans: Trans
) -> TerminologyMetricKindInfo:
    ensure_builtin_metric_kinds(session, oid)

    label = (info.label or '').strip()
    if not label:
        raise Exception(trans('i18n_terminology.metric_kind_label_required'))

    sort_order = info.sort_order if info.sort_order is not None else 0
    enabled = True if info.enabled is None else bool(info.enabled)

    if info.id:
        row = session.get(TerminologyMetricKind, info.id)
        if not row or row.oid != oid:
            raise Exception(trans('i18n_terminology.metric_kind_not_found'))

        if row.builtin:
            # builtin: cannot change code
            if info.code and info.code.strip() and info.code.strip() != row.code:
                raise Exception(trans('i18n_terminology.metric_kind_builtin_code_immutable'))
        else:
            code = (info.code or '').strip().lower()
            if not is_valid_metric_kind_code(code):
                raise Exception(trans('i18n_terminology.metric_kind_code_invalid'))
            if code != row.code:
                dup = session.execute(
                    select(TerminologyMetricKind.id).where(
                        and_(
                            TerminologyMetricKind.oid == oid,
                            TerminologyMetricKind.code == code,
                            TerminologyMetricKind.id != row.id,
                        )
                    )
                ).scalar_one_or_none()
                if dup:
                    raise Exception(trans('i18n_terminology.metric_kind_code_exists'))
                # block rename if referenced
                used = session.execute(
                    select(func.count()).select_from(Terminology).where(
                        and_(Terminology.oid == oid, Terminology.metric_kind == row.code)
                    )
                ).scalar_one()
                if used and used > 0:
                    raise Exception(trans('i18n_terminology.metric_kind_in_use'))
                row.code = code

        if row.code == MetricKind.FLOW.value and not enabled:
            raise Exception(trans('i18n_terminology.metric_kind_flow_cannot_disable'))

        row.label = label
        row.sort_order = sort_order
        row.enabled = enabled
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_info(row)

    code = (info.code or '').strip().lower()
    if not is_valid_metric_kind_code(code):
        raise Exception(trans('i18n_terminology.metric_kind_code_invalid'))
    if code in BUILTIN_METRIC_KIND_CODES:
        raise Exception(trans('i18n_terminology.metric_kind_code_reserved'))

    dup = session.execute(
        select(TerminologyMetricKind.id).where(
            and_(TerminologyMetricKind.oid == oid, TerminologyMetricKind.code == code)
        )
    ).scalar_one_or_none()
    if dup:
        raise Exception(trans('i18n_terminology.metric_kind_code_exists'))

    row = TerminologyMetricKind(
        oid=oid,
        code=code,
        label=label,
        sort_order=sort_order,
        enabled=enabled,
        builtin=False,
        create_time=datetime.datetime.now(),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return _to_info(row)


def delete_metric_kinds(session: SessionDep, id_list: list[int], oid: int, trans: Trans) -> None:
    if not id_list:
        return
    ensure_builtin_metric_kinds(session, oid)
    rows = session.execute(
        select(TerminologyMetricKind).where(
            and_(TerminologyMetricKind.oid == oid, TerminologyMetricKind.id.in_(id_list))
        )
    ).scalars().all()
    if not rows:
        return

    for row in rows:
        if row.builtin:
            raise Exception(trans('i18n_terminology.metric_kind_builtin_cannot_delete'))
        used = session.execute(
            select(func.count()).select_from(Terminology).where(
                and_(Terminology.oid == oid, Terminology.metric_kind == row.code)
            )
        ).scalar_one()
        if used and used > 0:
            raise Exception(trans('i18n_terminology.metric_kind_in_use'))

    session.execute(
        delete(TerminologyMetricKind).where(
            and_(TerminologyMetricKind.oid == oid, TerminologyMetricKind.id.in_(id_list))
        )
    )
    session.commit()


def resolve_and_validate_metric_kind(
    session: SessionDep, oid: int, metric_kind: str | None, trans: Trans, *, require_enabled: bool = True
) -> str:
    extras = get_metric_kind_extras(session, oid)
    normalized = normalize_metric_kind(metric_kind, extras)
    if not normalized:
        raise Exception(trans('i18n_terminology.metric_kind_required'))

    stmt = select(TerminologyMetricKind).where(
        and_(TerminologyMetricKind.oid == oid, TerminologyMetricKind.code == normalized)
    )
    row = session.execute(stmt).scalar_one_or_none()
    if not row:
        raise Exception(trans('i18n_terminology.metric_kind_invalid'))
    if require_enabled and not row.enabled:
        raise Exception(trans('i18n_terminology.metric_kind_invalid'))
    return normalized
