"""Resolve metric_kind scenario from matched terminology rows."""
from __future__ import annotations

from dataclasses import dataclass, field

from apps.terminology.metric_kind import (
    ACTIVE_METRIC_KINDS,
    MetricKind,
    SCENARIO_BALANCE_ONLY,
    SCENARIO_FLOW_ONLY,
    SCENARIO_MIXED,
    SCENARIO_NONE,
)


@dataclass
class MetricKindContext:
    matched: list[dict]
    active_kinds: set[str] = field(default_factory=set)
    scenario: str = SCENARIO_NONE


def build_metric_kind_context(term_results: list[dict] | None) -> MetricKindContext:
    if not term_results:
        return MetricKindContext(matched=[], scenario=SCENARIO_NONE)

    active: set[str] = set()
    for row in term_results:
        kind = (row.get('metric_kind') or MetricKind.FLOW.value).strip()
        if kind in ACTIVE_METRIC_KINDS:
            active.add(kind)

    if not active:
        return MetricKindContext(matched=term_results, active_kinds=active, scenario=SCENARIO_NONE)
    if MetricKind.FLOW.value in active and MetricKind.BALANCE.value in active:
        scenario = SCENARIO_MIXED
    elif MetricKind.FLOW.value in active:
        scenario = SCENARIO_FLOW_ONLY
    elif MetricKind.BALANCE.value in active:
        scenario = SCENARIO_BALANCE_ONLY
    else:
        scenario = SCENARIO_NONE

    return MetricKindContext(matched=term_results, active_kinds=active, scenario=scenario)


def should_skip_sql_time_filter(ctx: MetricKindContext | None) -> bool:
    return bool(ctx and ctx.scenario == SCENARIO_BALANCE_ONLY)
