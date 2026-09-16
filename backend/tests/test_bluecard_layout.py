"""Tests for BlueCard P2 layout / skip-chart / force-table planning."""
from apps.chat.bluecard.layout import (
    build_table_chart_config,
    is_chart_visualizable,
    plan_bluecard_result,
    resolve_bluecard_layout,
)


def test_empty_layout():
    assert resolve_bluecard_layout([], []) == 'empty'
    plan = plan_bluecard_result(['a'], [])
    assert plan.layout == 'empty'
    assert plan.skip_chart is True


def test_single_row_hero_skips_chart():
    fields = ['total_deposit_usd']
    rows = [{'total_deposit_usd': 1284500.12}]
    assert resolve_bluecard_layout(fields, rows) == 'hero'
    plan = plan_bluecard_result(fields, rows)
    assert plan.skip_chart is True
    assert plan.force_table is False


def test_single_row_metrics_skips_chart():
    fields = ['deposit', 'withdraw', 'net']
    rows = [{'deposit': 1, 'withdraw': 2, 'net': -1}]
    assert resolve_bluecard_layout(fields, rows) == 'metrics'
    plan = plan_bluecard_result(fields, rows)
    assert plan.skip_chart is True


def test_single_row_profile_skips_chart():
    fields = ['email', 'team', 'balance', 'currency']
    rows = [{'email': 'a@b.com', 'team': 'MT', 'balance': 100, 'currency': 'USD'}]
    assert resolve_bluecard_layout(fields, rows) == 'profile'
    plan = plan_bluecard_result(fields, rows)
    assert plan.skip_chart is True


def test_multi_row_month_measure_is_visualizable():
    fields = ['month', 'monthly_withdrawal_usd']
    rows = [
        {'month': '2026-01', 'monthly_withdrawal_usd': -1.0},
        {'month': '2026-02', 'monthly_withdrawal_usd': -2.0},
    ]
    assert is_chart_visualizable(fields, rows) is True
    plan = plan_bluecard_result(fields, rows, preferred_chart_type='line')
    assert plan.skip_chart is False
    assert plan.force_table is False
    assert plan.layout == 'chart'
    assert plan.chart_type == 'line'


def test_multi_row_wide_text_forces_table():
    fields = [
        'email', 'name', 'team', 'region', 'phone', 'status', 'note', 'tag', 'extra',
    ]
    rows = [
        {f: f'v{i}-{f}' for f in fields}
        for i in range(3)
    ]
    # mostly text, few/no numeric → not visualizable
    assert is_chart_visualizable(fields, rows) is False
    plan = plan_bluecard_result(fields, rows, preferred_chart_type='column')
    assert plan.force_table is True
    assert plan.skip_chart is True
    assert plan.layout == 'table'


def test_preferred_table_honored_even_if_visualizable():
    fields = ['month', 'amt']
    rows = [{'month': '2026-01', 'amt': 1}, {'month': '2026-02', 'amt': 2}]
    plan = plan_bluecard_result(fields, rows, preferred_chart_type='table')
    assert plan.force_table is True
    assert plan.skip_chart is True


def test_build_table_chart_config():
    cfg = build_table_chart_config(['Month', 'Amt'], [{'Month': 'a', 'Amt': 1}], title='T')
    assert cfg['type'] == 'table'
    assert cfg['title'] == 'T'
    assert cfg['columns'][0]['value'] == 'month'
    assert cfg['columns'][1]['value'] == 'amt'
