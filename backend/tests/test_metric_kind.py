"""Unit tests for metric_kind time rules and configurable options."""
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
    is_valid_metric_kind_code,
    normalize_metric_kind,
)

try:
    import pytest
except ImportError:  # pragma: no cover
    pytest = None


def test_normalize_metric_kind():
    assert normalize_metric_kind('发生型指标') == MetricKind.FLOW.value
    assert normalize_metric_kind('balance') == MetricKind.BALANCE.value
    assert normalize_metric_kind('invalid') is None


def test_normalize_metric_kind_with_extras():
    extras = [('rate_type', '费率型'), ('inventory', '库存型')]
    assert normalize_metric_kind('费率型', extras) == 'rate_type'
    assert normalize_metric_kind('rate_type', extras) == 'rate_type'
    assert normalize_metric_kind('库存型', extras) == 'inventory'
    assert normalize_metric_kind('unknown_label', extras) is None


def test_is_valid_metric_kind_code():
    assert is_valid_metric_kind_code('flow') is True
    assert is_valid_metric_kind_code('rate_type') is True
    assert is_valid_metric_kind_code('a1') is True
    assert is_valid_metric_kind_code('1bad') is False
    assert is_valid_metric_kind_code('Bad') is False
    assert is_valid_metric_kind_code('') is False


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


def test_build_metric_kind_context_custom_code_no_time_logic():
    ctx = build_metric_kind_context([
        {'words': ['费率'], 'metric_kind': 'rate_type', 'description': 'd'},
    ])
    assert ctx.scenario == SCENARIO_NONE
    assert should_skip_sql_time_filter(ctx) is False


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


def _require_pytest_and_sqlalchemy():
    if pytest is None:
        raise ImportError('pytest required')
    try:
        import sqlalchemy  # noqa: F401
    except ImportError as e:
        pytest.skip(f'sqlalchemy not available: {e}')


def test_cannot_delete_builtin_metric_kind():
    _require_pytest_and_sqlalchemy()
    from unittest.mock import MagicMock
    from apps.terminology.curd.metric_kind_crud import delete_metric_kinds
    from apps.terminology.models.terminology_model import TerminologyMetricKind
    import apps.terminology.curd.metric_kind_crud as mkc

    session = MagicMock()
    builtin = TerminologyMetricKind(
        id=1, oid=1, code='flow', label='发生型指标', builtin=True, enabled=True, sort_order=10
    )
    mkc.ensure_builtin_metric_kinds = lambda *a, **k: None
    session.execute.return_value.scalars.return_value.all.return_value = [builtin]

    with pytest.raises(Exception) as exc:
        delete_metric_kinds(session, [1], 1, lambda k: k)
    assert 'metric_kind_builtin_cannot_delete' in str(exc.value)


def test_cannot_disable_flow():
    _require_pytest_and_sqlalchemy()
    from unittest.mock import MagicMock
    from apps.terminology.curd.metric_kind_crud import create_or_update_metric_kind
    from apps.terminology.models.terminology_model import (
        TerminologyMetricKind,
        TerminologyMetricKindInfo,
    )
    import apps.terminology.curd.metric_kind_crud as mkc

    session = MagicMock()
    flow = TerminologyMetricKind(
        id=1, oid=1, code='flow', label='发生型指标', builtin=True, enabled=True, sort_order=10
    )
    mkc.ensure_builtin_metric_kinds = lambda *a, **k: None
    session.get.return_value = flow

    with pytest.raises(Exception) as exc:
        create_or_update_metric_kind(
            session,
            TerminologyMetricKindInfo(id=1, code='flow', label='发生型指标', enabled=False),
            1,
            lambda k: k,
        )
    assert 'metric_kind_flow_cannot_disable' in str(exc.value)


def test_cannot_delete_in_use_metric_kind():
    _require_pytest_and_sqlalchemy()
    from unittest.mock import MagicMock
    from apps.terminology.curd.metric_kind_crud import delete_metric_kinds
    from apps.terminology.models.terminology_model import TerminologyMetricKind
    import apps.terminology.curd.metric_kind_crud as mkc

    session = MagicMock()
    custom = TerminologyMetricKind(
        id=9, oid=1, code='rate_type', label='费率型', builtin=False, enabled=True, sort_order=50
    )
    mkc.ensure_builtin_metric_kinds = lambda *a, **k: None

    scalars_result = MagicMock()
    scalars_result.all.return_value = [custom]
    first = MagicMock()
    first.scalars.return_value = scalars_result
    second = MagicMock()
    second.scalar_one.return_value = 2
    session.execute.side_effect = [first, second]

    with pytest.raises(Exception) as exc:
        delete_metric_kinds(session, [9], 1, lambda k: k)
    assert 'metric_kind_in_use' in str(exc.value)
