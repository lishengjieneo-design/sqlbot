"""
Detect ambiguous numeric IDs in user questions against m-schema ID-like fields.
Used before LLM SQL generation to force clarification when multiple field mappings exist.
"""
from __future__ import annotations

import re
from typing import Optional

from apps.chat.clarification_util import resolve_user_label, sanitize_clarification_candidates

# m-schema field line: (field_name:type, description...)
_SCHEMA_FIELD_RE = re.compile(
    r'\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:[^,)]*(?:,\s*([^)]*))?\)',
    re.MULTILINE,
)

# Digit boundaries only: \w includes CJK, so "账户130032053" failed with (?<![\w@.]).
_NUMERIC_ID_RE = re.compile(r'(?<!\d)\d{5,}(?!\d)')

_ID_FIELD_SUFFIXES = ('_id', '_no', '_code', '_num')
_ID_FIELD_EXACT = frozenset({
    'login', 'mt_login', 'mtlogin', 'account_no', 'crm_id', 'member_id', 'agent_id',
    'referrer_crm_id', 'descendant_login', 'introduce_code', 'memberid_or_login',
    'agent_account', 'maxtec_member_id',
})

# Prefer these when building clarification options (order preserved).
_ID_FIELD_PRIORITY = (
    'account_no', 'login', 'mt_login', 'mtlogin', 'crm_id', 'member_id',
    'referrer_crm_id', 'descendant_login', 'memberid_or_login', 'agent_account',
)

_MAX_CLARIFICATION_CANDIDATES = 8

# Amount / metric columns must not be treated as ID fields.
_NON_ID_FIELD_SUFFIXES = ('_amt', '_pnl', '_rate', '_fee', '_count', '_qty', '_volume')

# Near the numeric id, these phrases imply the user already chose a mapping.
_DISAMBIG_KEYWORDS = (
    (re.compile(r'ts\s*login|mt\s*login|\blogin\b', re.I), frozenset({'account_no', 'login', 'mt_login'})),
    (re.compile(r'\bcrm_id\b|\bmember_id\b|\bcrm\b', re.I), frozenset({'crm_id', 'member_id'})),
    (re.compile(r'\baccount_no\b|\baccount\b', re.I), frozenset({'account_no'})),
)


def is_id_like_field(field_name: str) -> bool:
    n = field_name.lower()
    if any(n.endswith(s) for s in _NON_ID_FIELD_SUFFIXES):
        return False
    if n in _ID_FIELD_EXACT:
        return True
    if any(n.endswith(s) for s in _ID_FIELD_SUFFIXES):
        # Avoid treating descriptive columns (e.g. client_first_name) as ID keys.
        if any(n.endswith(s) for s in ('_name', '_email', '_status', '_type', '_time', '_date')):
            return False
        return True
    return False


def _prioritize_id_fields(fields: list[dict]) -> list[dict]:
    by_name = {f['field'].lower(): f for f in fields}
    ordered: list[dict] = []
    for name in _ID_FIELD_PRIORITY:
        if name in by_name:
            ordered.append(by_name.pop(name))
    for f in fields:
        key = f['field'].lower()
        if key in by_name:
            ordered.append(f)
    return ordered[:_MAX_CLARIFICATION_CANDIDATES]


def parse_id_fields_from_schema(schema_text: str) -> list[dict]:
    """Parse m-schema text into ID-like field candidates."""
    if not schema_text:
        return []
    seen: set[str] = set()
    fields: list[dict] = []
    for match in _SCHEMA_FIELD_RE.finditer(schema_text):
        name = match.group(1)
        if not is_id_like_field(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        desc = (match.group(2) or '').strip()
        label = resolve_user_label(name, desc, desc)
        if not label:
            continue
        fields.append({
            'field': name,
            'label': label,
            'description': desc,
        })
    return fields


def extract_numeric_ids(question: str) -> list[str]:
    if not question:
        return []
    ids: list[str] = []
    for match in _NUMERIC_ID_RE.finditer(question):
        start, end = match.span()
        window = question[max(0, start - 30):min(len(question), end + 30)]
        if '@' in window:
            continue
        ids.append(match.group(0))
    return list(dict.fromkeys(ids))


def _context_window(question: str, raw_id: str, radius: int = 40) -> str:
    q = question.lower()
    pos = q.find(raw_id.lower())
    if pos < 0:
        return q
    start = max(0, pos - radius)
    end = min(len(q), pos + len(raw_id) + radius)
    return q[start:end]


def question_disambiguates_id(question: str, raw_id: str, schema_fields: list[dict]) -> bool:
    """True when user text already pins the id to a single field type."""
    window = _context_window(question, raw_id)
    allowed: set[str] = set()
    for pattern, fields in _DISAMBIG_KEYWORDS:
        if pattern.search(window):
            allowed |= fields
    if not allowed:
        return False
    schema_names = {f['field'].lower() for f in schema_fields}
    matched = allowed & schema_names
    return len(matched) == 1


def detect_id_clarification_needed(
    question: str,
    schema_text: str,
    resolved_raw_values: Optional[set[str]] = None,
    min_candidates: int = 2,
) -> Optional[dict]:
    """
    Return clarification `current` payload for the first ambiguous numeric id, or None.
    """
    resolved_raw_values = resolved_raw_values or set()
    question_ids = extract_numeric_ids(question)
    if question_ids and resolved_raw_values and all(i in resolved_raw_values for i in question_ids):
        return None
    schema_fields = _prioritize_id_fields(parse_id_fields_from_schema(schema_text))
    if len(schema_fields) < min_candidates:
        return None

    for raw_id in extract_numeric_ids(question):
        if raw_id in resolved_raw_values:
            continue
        if question_disambiguates_id(question, raw_id, schema_fields):
            continue

        candidates = sanitize_clarification_candidates([
            {'field': f['field'], 'label': f['label'], 'description': f.get('description')}
            for f in schema_fields
        ])
        if len(candidates) < min_candidates:
            continue

        return {
            'factor_key': f'id_{raw_id}',
            'prompt': f'请确认「{raw_id}」指的是哪一种账号或 ID。',
            'raw_value': raw_id,
            'candidates': candidates,
            'source': 'schema_prefilter',
        }

    return None


def plan_id_clarification_steps(
    question: str,
    schema_text: str,
    resolved_raw_values: Optional[set[str]] = None,
    min_candidates: int = 2,
) -> list[dict]:
    """List all ambiguous numeric IDs in the question that still need clarification."""
    resolved_raw_values = resolved_raw_values or set()
    schema_fields = _prioritize_id_fields(parse_id_fields_from_schema(schema_text))
    if len(schema_fields) < min_candidates:
        return []
    steps: list[dict] = []
    for raw_id in extract_numeric_ids(question):
        if raw_id in resolved_raw_values:
            continue
        if question_disambiguates_id(question, raw_id, schema_fields):
            continue
        candidates = sanitize_clarification_candidates([
            {'field': f['field'], 'label': f['label'], 'description': f.get('description')}
            for f in schema_fields
        ])
        if len(candidates) < min_candidates:
            continue
        steps.append({
            'step_key': f'id_{raw_id}',
            'factor_type': 'id',
            'factor_key': f'id_{raw_id}',
            'raw_value': raw_id,
        })
    return steps
