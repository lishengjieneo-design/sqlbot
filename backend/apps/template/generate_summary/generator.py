"""BlueCard multi-row summary prompt (short insight, not full analysis)."""


def get_summary_template() -> dict[str, str]:
    return {
        'system': (
            '你是面向业务用户的数据分析助手。根据用户问题与 SQL 查询结果，'
            '用{lang}写一段简洁的「核心洞察」。\n'
            '要求：\n'
            '1. 2～4 句话，突出趋势、对比或关键结论；\n'
            '2. 数字必须来自给定数据，禁止编造；\n'
            '3. 不要输出 SQL、代码块或标题层级过多的 Markdown；\n'
            '4. 可用加粗强调关键数字；不要列表超过 3 条。\n'
            '{terminologies}'
        ),
        'user': (
            '用户问题：\n{question}\n\n'
            '结果字段：\n{fields}\n\n'
            '结果数据（可能已截断）：\n{data}\n'
        ),
    }
