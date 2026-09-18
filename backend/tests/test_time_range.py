"""Unit tests for time range clarification and SQL validation."""
from datetime import datetime

from apps.chat.clarification_util import (
    apply_user_resolution,
    attach_clarification_plan_and_progress,
    build_clarification_plan,
    compute_clarification_progress,
    merge_time_range_candidates,
    normalize_current,
)
from apps.chat.sql_time_filter_validator import (
    extract_sql_table_names,
    parse_time_fields_from_schema,
    sql_has_time_filter,
)
from apps.chat.time_range_prefilter import (
    build_time_preset_candidates,
    build_time_range_clarification,
    build_time_resolution_label,
    format_time_range_display,
    infer_time_range_from_question,
    question_has_time_constraint,
    validate_time_free_text,
    validate_time_selection,
)


def test_question_without_time():
    assert question_has_time_constraint('账户130032053的入金') is False


def test_question_with_relative_time():
    assert question_has_time_constraint('最近7天账户130032053入金') is True


def test_question_with_this_year_variants():
    assert question_has_time_constraint('本年度账户入金') is True
    assert question_has_time_constraint('本年入金汇总') is True
    assert question_has_time_constraint('今年净入金') is True
    assert question_has_time_constraint('上年度出金') is True
    assert question_has_time_constraint('账户入金') is False


def test_infer_covers_new_presets_and_aliases():
    """New clarification presets + common aliases must both skip clarif and infer dates."""
    anchor = datetime(2026, 5, 19)
    earliest = '2024-01-01'
    cases = [
        # new presets (exact labels)
        ('上周入金', 'last_week', '2026-05-11', '2026-05-17'),
        ('上月入金', 'last_month', '2026-04-01', '2026-04-30'),
        ('本年入金', 'this_year', '2026-01-01', '2026-05-19'),
        ('本年度入金', 'this_year', '2026-01-01', '2026-05-19'),
        # aliases
        ('上一周入金', 'last_week', '2026-05-11', '2026-05-17'),
        ('上个月入金', 'last_month', '2026-04-01', '2026-04-30'),
        ('上一月入金', 'last_month', '2026-04-01', '2026-04-30'),
        ('今年入金', 'this_year', '2026-01-01', '2026-05-19'),
        ('这个年度入金', 'this_year', '2026-01-01', '2026-05-19'),
        # related recognized relatives
        ('前天入金', 'day_before_yesterday', '2026-05-17', '2026-05-17'),
        ('去年入金', 'last_year', '2025-01-01', '2025-12-31'),
        ('上年度入金', 'last_year', '2025-01-01', '2025-12-31'),
        ('前年入金', 'year_before_last', '2024-01-01', '2024-12-31'),
        ('最近一个月入金', 'last_1_months', '2026-04-19', '2026-05-19'),
        ('近3天入金', 'last_3_days', '2026-05-17', '2026-05-19'),
    ]
    for q, field, start, end in cases:
        assert question_has_time_constraint(q) is True, q
        inferred = infer_time_range_from_question(q, earliest, anchor)
        assert inferred is not None, q
        assert inferred['field'] == field, (q, inferred)
        assert inferred['date_start'] == start, (q, inferred)
        assert inferred['date_end'] == end, (q, inferred)


def test_question_with_chinese_word_number_time():
    assert question_has_time_constraint('12312421 出入金，最近一个月') is True
    assert question_has_time_constraint('近一个月入金') is True
    assert question_has_time_constraint('过去三天业绩') is True
    assert question_has_time_constraint('最近一月账户余额') is True


def test_question_with_english_word_number_time():
    assert question_has_time_constraint('deposits last one month for account X') is True
    assert question_has_time_constraint('revenue past two weeks by region') is True
    assert question_has_time_constraint('closed lots last a month for IB') is True


def test_question_with_english_month():
    q = (
        'my bro can you share closed lots by IB oliverphamfs99@gmail.com '
        'for the month of April 2026'
    )
    assert question_has_time_constraint(q) is True


def test_question_with_english_relative():
    assert question_has_time_constraint('closed lots last 30 days for account X') is True
    assert question_has_time_constraint('revenue this month by region') is True


def test_question_with_resolved_time():
    resolved = [{'factor_type': 'time_range', 'factor_key': 'time_range', 'label': '本月'}]
    assert question_has_time_constraint('账户入金', resolved) is True


def test_build_clarification_has_earliest_and_presets():
    payload = build_time_range_clarification('2024-01-01', datetime(2026, 5, 19, 12, 0, 0))
    assert payload['earliest_data_date'] == '2024-01-01'
    assert payload['factor_type'] == 'time_range'
    cands = payload['candidates']
    fields = [c['field'] for c in cands]
    assert fields == [
        'all_time',
        'today',
        'yesterday',
        'this_week',
        'last_week',
        'this_month',
        'last_month',
        'this_year',
        'last_7_days',
        'last_30_days',
    ]
    assert cands[0]['label'] == '全部'
    assert cands[0]['date_start'] == '2024-01-01'
    assert cands[0]['date_end'] == '2026-05-19'
    assert cands[1]['field'] == 'today'
    assert cands[1]['date_start'] == cands[1]['date_end']

    by_field = {c['field']: c for c in cands}
    assert by_field['last_week']['date_start'] == '2026-05-11'
    assert by_field['last_week']['date_end'] == '2026-05-17'
    assert by_field['last_month']['date_start'] == '2026-04-01'
    assert by_field['last_month']['date_end'] == '2026-04-30'
    assert by_field['this_year']['date_start'] == '2026-01-01'
    assert by_field['this_year']['date_end'] == '2026-05-19'
    assert by_field['last_week']['label'] == '上周'
    assert by_field['last_month']['label'] == '上月'
    assert by_field['this_year']['label'] == '本年'


def test_merge_appends_new_presets():
    legacy = [
        {'field': 'today', 'label': '今天'},
        {'field': 'last_7_days', 'label': '最近7天'},
    ]
    merged = merge_time_range_candidates(legacy, '2024-01-01', datetime(2026, 5, 19))
    fields = {c['field'] for c in merged}
    assert 'last_week' in fields
    assert 'last_month' in fields
    assert 'this_year' in fields
    assert 'all_time' in fields


def test_build_clarification_english_locale():
    payload = build_time_range_clarification(
        '2024-01-01', datetime(2026, 5, 19, 12, 0, 0), lang='英文',
    )
    cands = payload['candidates']
    assert payload['locale'] == 'en'
    assert payload['prompt'] == 'Please specify the query time range'
    assert cands[0]['label'] == 'All'
    assert cands[0]['date_start'] == '2024-01-01'


def test_merge_legacy_candidates_without_dates():
    legacy = [
        {'field': 'today', 'label': '今天'},
        {'field': 'yesterday', 'label': '昨天'},
    ]
    merged = merge_time_range_candidates(legacy, '2024-01-01', datetime(2026, 5, 19))
    today = next(c for c in merged if c['field'] == 'today')
    assert today['date_start'] == today['date_end'] == '2026-05-19'
    assert any(c['field'] == 'all_time' for c in merged)


def test_normalize_current_enriches_time_candidates():
    current = normalize_current({
        'factor_type': 'time_range',
        'earliest_data_date': '2024-01-01',
        'current_date': '2026-05-19',
        'candidates': [{'field': 'last_7_days', 'label': '最近7天'}],
    })
    preset = next(c for c in current['candidates'] if c['field'] == 'last_7_days')
    assert preset['date_start'] == '2026-05-13'
    assert preset['date_end'] == '2026-05-19'


def test_format_time_range_display():
    assert format_time_range_display('2024-01-01', '2024-01-01') == '2024-01-01'
    assert format_time_range_display('2024-01-01', '2024-03-31') == '2024-01-01 至 2024-03-31'


def test_time_resolution_does_not_increment_round():
    clar = {
        'round': 0,
        'ask_count': 1,
        'max_rounds': 5,
        'resolved': [],
        'current': build_time_range_clarification('2024-01-01'),
    }
    presets = build_time_preset_candidates('2024-01-01', datetime(2026, 5, 19))
    preset = next(c for c in presets if c['field'] == 'last_7_days')
    after = apply_user_resolution(clar, selection=preset, earliest_date='2024-01-01')
    assert after['round'] == 0
    assert after['ask_count'] == 1
    assert after['resolved'][0]['factor_type'] == 'time_range'
    assert after['resolved'][0]['date_start']


def test_clarification_plan_time_and_progress():
    plan = build_clarification_plan('账户130032053的入金', schema_text='')
    assert plan['total_steps'] == 1
    assert plan['steps'][0]['step_key'] == 'time_range'
    clar = {
        'resolved': [],
        'current': {'factor_type': 'time_range'},
        'plan': plan,
    }
    clar = attach_clarification_plan_and_progress(clar, '账户130032053的入金', '')
    prog = clar['progress']
    assert prog['total_steps'] == 1
    assert prog['current_step'] == 1
    assert prog['remaining_steps'] == 1


def test_clarification_progress_after_one_resolved():
    plan = {'steps': [{'step_key': 'time_range'}, {'step_key': 'id_130032053'}], 'total_steps': 2}
    clar = {
        'resolved': [{'factor_type': 'time_range'}],
        'current': {'factor_type': 'id', 'raw_value': '130032053'},
        'plan': plan,
    }
    prog = compute_clarification_progress(clar)
    assert prog['total_steps'] == 2
    assert prog['completed_steps'] == 1
    assert prog['current_step'] == 2
    assert prog['remaining_steps'] == 1


def test_build_time_resolution_label():
    label = build_time_resolution_label(
        {'field': 'all_time', 'label': '全部', 'date_start': '2024-01-01', 'date_end': '2026-05-19'},
        earliest_date='2024-01-01',
    )
    assert '全部' in label
    assert '2024-01-01' in label


def test_validate_selection_before_earliest():
    err = validate_time_selection(
        {'field': 'custom', 'date_start': '2023-01-01', 'date_end': '2024-06-01'},
        '2024-01-01',
    )
    assert err is not None


def test_validate_free_text_before_earliest():
    err = validate_time_free_text('2023-01-01 至 2024-06-01', '2024-01-01')
    assert err is not None


def test_sql_has_time_filter_with_between():
    schema = '(trade_date:date, 交易日期),(amount:decimal, 金额)'
    sql = "SELECT * FROM t WHERE trade_date BETWEEN '2024-01-01' AND '2024-03-31'"
    ok, _ = sql_has_time_filter(sql, schema, {'label': '本月'})
    assert ok is True


def test_sql_has_time_filter_year_month_partition():
    """Partition column `month` with YYYY-MM literals must count as time filter."""
    schema = '(month:varchar, 月份),(deposit_amt:decimal, 入金),(ib_email:varchar, 邮箱)'
    sql = (
        'SELECT SUM(deposit_amt) AS total '
        "FROM t WHERE ib_email = 'a@b.com' "
        "AND month >= '2026-01' AND month <= '2026-09'"
    )
    ok, reason = sql_has_time_filter(sql, schema, {'label': '本年'})
    assert ok is True, reason


def test_sql_missing_time_filter():
    schema = '(trade_date:date, 交易日期)'
    sql = 'SELECT * FROM t WHERE account_no = 123'
    ok, reason = sql_has_time_filter(sql, schema, {'label': '本月'})
    assert ok is False
    assert reason


def test_sql_no_time_role_fields_skips_filter():
    """Used tables have no semantic_role=time → hard check passes without date filter."""
    sql = 'SELECT equity_usd FROM mt_login_account_balance WHERE login = 383090'
    ok, reason = sql_has_time_filter(
        sql,
        schema_text='',
        resolved_time=None,
        required_time_fields=[],
        tables_matched=True,
    )
    assert ok is True, reason


def test_sql_with_time_role_fields_requires_filter():
    sql = 'SELECT deposit_amt FROM daily_metric WHERE login = 383090'
    ok, reason = sql_has_time_filter(
        sql,
        schema_text='',
        resolved_time={'label': '本月'},
        required_time_fields=['transaction_date'],
        tables_matched=True,
    )
    assert ok is False
    assert 'transaction_date' in reason


def test_sql_with_time_role_fields_and_filter_ok():
    sql = (
        "SELECT deposit_amt FROM daily_metric "
        "WHERE login = 383090 AND transaction_date >= '2026-09-01'"
    )
    ok, reason = sql_has_time_filter(
        sql,
        schema_text='',
        resolved_time={'label': '本月'},
        required_time_fields=['transaction_date'],
        tables_matched=True,
    )
    assert ok is True, reason


def test_extract_sql_table_names():
    sql = (
        'SELECT t1.login FROM sqlbot.mt_login_account_balance t1 '
        'JOIN daily_metric t2 ON t1.login = t2.login'
    )
    names = extract_sql_table_names(sql)
    assert 'mt_login_account_balance' in names
    assert 'daily_metric' in names


def test_parse_time_fields():
    schema = '(create_time:datetime, 创建时间),(name:varchar, 名称)'
    fields = parse_time_fields_from_schema(schema)
    assert 'create_time' in fields
    assert 'name' not in fields
