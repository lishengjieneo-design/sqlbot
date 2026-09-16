"""BlueCard field display-name prompt (bilingual zh/en aliases)."""


def get_field_alias_template() -> dict[str, str]:
    return {
        'system': (
            '你是业务数据字段命名助手。根据用户问题与 SQL 结果列名，为每个字段给出'
            '简洁的中文业务名与英文业务名。\n'
            '要求：\n'
            '1. 只输出 JSON 数组，不要 Markdown 代码块或其它说明；\n'
            '2. 每项格式：'
            '{{"field":"列名原样","name_zh":"中文名","name_en":"English Name"}}；\n'
            '3. name_zh / name_en 要短（一般 2～12 字），面向业务用户，禁止照抄下划线列名；\n'
            '4. field 必须与输入列名完全一致；\n'
            '5. 必须覆盖用户给出的每一个字段。\n'
            '{terminologies}'
        ),
        'user': (
            '用户问题：\n{question}\n\n'
            '需要命名的字段：\n{fields}\n'
        ),
    }
