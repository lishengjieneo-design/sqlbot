"""One-off batch update for terminology definitions (field + USD mapping)."""
from __future__ import annotations

from sqlmodel import Session

from apps.terminology.curd.terminology import create_terminology, update_terminology
from apps.terminology.models.terminology_model import TerminologyInfo
from common.core.db import engine

OID = 1
TRANS = lambda key: key  # noqa: E731


def _update(session: Session, term_id: int, word: str, description: str, other_words: list[str]) -> None:
    update_terminology(
        session,
        TerminologyInfo(
            id=term_id,
            word=word,
            description=description,
            other_words=other_words,
            enabled=True,
            specific_ds=False,
            datasource_ids=[],
        ),
        OID,
        TRANS,
    )
    print(f"  updated id={term_id} word={word!r}")


def _create(session: Session, word: str, description: str, other_words: list[str]) -> int:
    new_id = create_terminology(
        session,
        TerminologyInfo(
            word=word,
            description=description,
            other_words=other_words,
            enabled=True,
            specific_ds=False,
            datasource_ids=[],
        ),
        OID,
        TRANS,
        skip_embedding=False,
    )
    print(f"  created id={new_id} word={word!r}")
    return new_id


def main() -> None:
    table = "sqlbot.trd_agent_login_profit_ir_dd_all_view"
    rate = "sqlbot.tscrm_exchange_rate_view"

    updates: list[tuple[int, str, str, list[str]]] = [
        (
            38,
            "业绩",
            (
                "业绩：代理/IB 经营结果，默认不是单一指标。"
                f"表 {table}。"
                "仅问业绩或净入金：SUM(net_deposit_amt) 须经汇率转 USD。"
                "若同时问出入金、返佣、PNL：须分别汇总 deposit_amt、withdrawal_amt、"
                "net_deposit_amt、rebate_amt、closed_pnl（前四项除 rebate 外须转 USD），"
                "禁止只查 net_deposit_amt。"
                "代理邮箱：lower(ib_email) 或 lower(agent_email)；客户：lower(email)。"
            ),
            [],
        ),
        (
            43,
            "返佣",
            (
                "客户交易后给上级 IB 的返佣。"
                f"字段 rebate_amt（表 {table}），单位已是 USD，"
                "禁止 JOIN 汇率表再乘 exchange_rate。"
            ),
            ["rebate", "佣金"],
        ),
        (
            46,
            "Net pnl",
            (
                "PNL/净盈亏：优先 closed_pnl（平仓盈亏）。"
                f"表 {table}，字段 closed_pnl；无 _usd 后缀须 JOIN {rate} "
                "ON r.symbol = t.currency AND r.currency = 'USD'，用 closed_pnl * r.exchange_rate。"
                "公式参考：Net PnL ≈ closed_pnl + 浮动盈亏（若有 float 字段）。"
            ),
            ["netpnl", "net p&l", "net profit&lost", "PNL", "P&L", "pnl", "盈亏"],
        ),
        (
            54,
            "平仓利润",
            (
                "客户平仓后的利润或亏损，SQL 字段名 closed_pnl。"
                f"表 {table}；须按 currency JOIN {rate} 转 USD（除非已是美元列）。"
            ),
            ["closed", "closed pnl", "close pnl"],
        ),
        (
            62,
            "出金",
            (
                "客户从 MT 账户提款。"
                f"字段 withdrawal_amt（表 {table}），原始货币，"
                f"须 JOIN {rate} 按 currency 转 USD。"
            ),
            ["withdraw", "withdrawal", "wd"],
        ),
        (
            66,
            "净入金",
            (
                "入金减出金。"
                f"字段 net_deposit_amt（表 {table}），原始货币，"
                f"须 JOIN {rate} 转 USD；不等于「出入金+返佣+PNL」的多指标汇总。"
            ),
            ["net deposit", "net funding"],
        ),
        (
            69,
            "入金",
            (
                "客户向 MT 账户存款。"
                f"字段 deposit_amt（表 {table}），原始货币，"
                f"须 JOIN {rate} 按 currency 转 USD。"
            ),
            ["deposit", "dp", "fund", "funding"],
        ),
        (
            1,
            "创收",
            (
                "账户或代理为公司带来的收益。"
                f"可参考表 {table}：closed_pnl（转 USD）减去 rebate_amt（已是 USD）。"
                "勿使用未换算的原始金额字段直接相减。"
            ),
            ["创利"],
        ),
        (
            77,
            "代理",
            (
                "在 TS 或 MaxTech 注册的 IB，可发展下级并获得返佣。"
                f"查 {table} 时邮箱常用 ib_email、agent_email；"
                "须 lower() 比较。"
            ),
            ["ib", "agent"],
        ),
    ]

    creates: list[tuple[str, str, list[str]]] = [
        (
            "出入金",
            (
                "同时指出金与入金，不可只查 net_deposit_amt 或只匹配「入金」。"
                f"表 {table}：deposit_amt（入金）、withdrawal_amt（出金），"
                f"均须 JOIN {rate} 转 USD；rebate_amt 已是 USD 不换算。"
            ),
            ["入金出金", "deposit and withdrawal", "资金进出"],
        ),
        (
            "美元金额换算",
            (
                "凡金额字段无 _usd 后缀且 schema 备注为原始金额/原始货币："
                f"必须 JOIN {rate} r ON r.symbol = t.currency AND r.currency = 'USD'，"
                "金额 * r.exchange_rate AS 别名_usd。"
                "例外：rebate_amt 已是 USD，禁止再乘汇率。"
            ),
            ["美元", "USD", "汇率", "换算", "原始金额", "currency"],
        ),
    ]

    with Session(engine) as session:
        print("Updating existing terminologies...")
        for term_id, word, desc, other_words in updates:
            _update(session, term_id, word, desc, other_words)

        print("Creating new terminologies...")
        from sqlalchemy import text

        for word, desc, other_words in creates:
            row = session.execute(
                text(
                    "SELECT id FROM terminology WHERE oid = :oid AND pid IS NULL "
                    "AND word = :word LIMIT 1"
                ),
                {"oid": OID, "word": word},
            ).first()
            if row:
                print(f"  skip create (exists id={row[0]}): {word!r}")
                continue
            _create(session, word, desc, other_words)

    print("Done.")


if __name__ == "__main__":
    main()
