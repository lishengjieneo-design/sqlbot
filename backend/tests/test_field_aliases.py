"""Tests for BlueCard field display aliases (dict > LLM merge/parse)."""
from apps.chat.bluecard.field_aliases import (
    alias_entry,
    aliases_list,
    humanize_en_field,
    incomplete_fields,
    merge_aliases,
    parse_llm_alias_payload,
    pick_bilingual_from_words,
)


def test_humanize_en_field():
    assert humanize_en_field('total_deposit_usd') == 'Total Deposit Usd'
    assert humanize_en_field('netInflow') == 'Net Inflow'


def test_pick_bilingual_from_words():
    zh, en = pick_bilingual_from_words(['入金', 'deposit', 'deposit_amount'])
    assert zh == '入金'
    assert en == 'deposit'


def test_parse_llm_alias_payload_array():
    text = '[{"field":"deposit_amount","name_zh":"入金","name_en":"Deposit"}]'
    out = parse_llm_alias_payload(text)
    assert out['deposit_amount']['name_zh'] == '入金'
    assert out['deposit_amount']['name_en'] == 'Deposit'
    assert out['deposit_amount']['source'] == 'llm'


def test_parse_llm_alias_payload_fenced():
    text = '```json\n[{"field":"a","name_zh":"甲","name_en":"A"}]\n```'
    out = parse_llm_alias_payload(text)
    assert out['a']['name_zh'] == '甲'


def test_merge_prefers_dict():
    preferred = {'deposit': alias_entry('deposit', name_zh='入金', name_en='Deposit', source='terminology')}
    fallback = {'deposit': alias_entry('deposit', name_zh='存款', name_en='Cash In', source='llm'),
                'withdraw': alias_entry('withdraw', name_zh='出金', name_en='Withdraw', source='llm')}
    merged = merge_aliases(preferred, fallback)
    assert merged['deposit']['name_zh'] == '入金'
    assert merged['deposit']['source'] == 'terminology'
    assert merged['withdraw']['name_zh'] == '出金'


def test_incomplete_fields():
    aliases = {'a': alias_entry('a', name_zh='甲', name_en='A')}
    assert incomplete_fields(['a', 'b'], aliases) == ['b']


def test_aliases_list_order():
    aliases = {
        'b': alias_entry('b', name_zh='乙', name_en='B'),
        'a': alias_entry('a', name_zh='甲', name_en='A'),
    }
    ordered = aliases_list(aliases, ['a', 'b'])
    assert [x['field'] for x in ordered] == ['a', 'b']
