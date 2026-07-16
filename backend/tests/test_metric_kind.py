"""Unit tests for metric_kind time rules."""
from apps.chat.balance_time_handler import (
    BALANCE_RANGE_ERROR,
    BalanceTimeKind,
    classify_balance_time,
)
from apps.chat.metric_kind_resolver import (
    build_metric_kind_context,
    should_skip_sql_time_filter,
)
from apps.chat.time_range_prefilter import (
    question_has_explicit_time_constraint,
    question_has_time_constraint,
)
from apps.terminology.metric_kind import (
    MetricKind,
    SCENARIO_BALANCE_ONLY,
    SCENARIO_FLOW_ONLY,
    SCENARIO_MIXED,
    SCENARIO_NONE,
    normalize_metric_kind,
)


def test_normalize_metric_kind():
    assert normalize_metric_kind('发生型指标') == MetricKind.FLOW.value
    assert normalize_metric_kind('balance') == MetricKind.BALANCE.value
    assert normalize_metric_kind('invalid') is None


def test_build_metric_kind_context_flow_only():
    ctx = build_metric_kind_context([
        {'words': ['入金'], 'description': 'd', 'metric_kind': 'flow'},
    ])
    assert ctx.scenario == SCENARIO_FLOW_ONLY
    assert ctx.active_kinds == {'flow'}


def test_build_metric_kind_context_balance_only():
    ctx = build_metric_kind_context([
        {'words': ['账户余额'], 'description': 'd', 'metric_kind': 'balance'},
    ])
    assert ctx.scenario == SCENARIO_BALANCE_ONLY
    assert should_skip_sql_time_filter(ctx) is True


def test_build_metric_kind_context_mixed():
    ctx = build_metric_kind_context([
        {'words': ['入金'], 'metric_kind': 'flow', 'description': 'd'},
        {'words': ['余额'], 'metric_kind': 'balance', 'description': 'd'},
    ])
    assert ctx.scenario == SCENARIO_MIXED
    assert should_skip_sql_time_filter(ctx) is False


def test_build_metric_kind_context_org_ignored():
    ctx = build_metric_kind_context([
        {'words': ['组织'], 'metric_kind': 'org_dimension', 'description': 'd'},
    ])
    assert ctx.scenario == SCENARIO_NONE


def test_explicit_time_strict():
    assert question_has_explicit_time_constraint('12312421 最近一个月入金') is True
    assert question_has_explicit_time_constraint('12312421 本月入金') is True
    assert question_has_explicit_time_constraint('12312421 最近入金') is False
    assert question_has_time_constraint('12312421 最近入金') is False


def test_balance_time_none():
    result = classify_balance_time('8004的账户余额')
    assert result.kind == BalanceTimeKind.NONE
    assert result.error_message is None


def test_balance_time_point():
    result = classify_balance_time('8004 昨天的账户余额')
    assert result.kind == BalanceTimeKind.POINT
    assert result.llm_hint


def test_balance_time_range_error():
    result = classify_balance_time('8004 最近一个月的账户余额')
    assert result.kind == BalanceTimeKind.RANGE
    assert result.error_message == BALANCE_RANGE_ERROR


def test_balance_time_multi_point():
    result = classify_balance_time('8004 2024-06-01和2024-06-15的余额')
    assert result.kind == BalanceTimeKind.MULTI_POINT
    assert result.llm_hint
