# 蓝卡出图（BlueCard）

> Codename: **`bluecard`**  
> 方便你我从中断处继续：提到「蓝卡出图」或 `bluecard` 即指本工程。

## 目标

优化问数结果展示：按结果形态分流 UI（卡片 / Summary+图 / Summary+表），浅色底 + 蓝色强调。

套图参考：`docs/mockups/result-cards/complete-set/`

## 分期

| 阶段 | 状态 | 内容 |
|------|------|------|
| **P0** | 已完成 | 前端按行数分流：单行→卡片（Hero / 横排 KPI / 档案）；多行→沿用现有图/表；浅底蓝样式 |
| **P1** | 已完成 | `sql-data` 先出数；多行 Summary（后端 SSE）；无图前临时表 |
| **P2** | 已完成 | 后端 layout 规则、单行跳过 chart、不可视图强制表 |
| **P2.5** | 已完成 | 结果展示兜底：问句无「每月/趋势」但 SQL 返回时间序列 → 前端 SUM 成 KPI 卡，下方仍保留图/表 |
| **P2.6** | 已完成 | 指标展示名：术语字典优先；缺失则 LLM 出中英别名，按系统语言选用 |
| **P3** | 已完成 | 档案字段排序、Summary 兜底+双栏关键数据、轻量埋点、折线蓝卡皮肤对齐 set-04 |
| **P4** | 未开始 | 柱/条皮肤、埋点落库、更多 polish |

## P0 规则（已实现）

```text
rows == 0     → 空态卡片
rows == 1
  · 1 个数值列（几乎无文本） → Hero
  · 2～5 个数值、文本很少     → 横排 KPI
  · 其他（含邮箱/账号等）    → 档案列表卡
rows > 1      → 现有 ChartBlock / DisplayChartBlock（图或表）
```

## P1 规则（已实现）

```text
sql-data 到达后
  · 不再等 finish / chart 才展示结果区
  · 单行 → 立刻出蓝卡
  · 多行 → 先出临时表；chart 到达后换正式图/表
  · 多行 → 后端流式 summary（核心洞察）
```

## P2 规则（已实现）

```text
后端 plan_bluecard_result（apps/chat/bluecard/layout.py）
  · empty / hero / metrics / profile → skip_chart（不调 chart LLM）
  · 多行 + 可可视化（维度+度量）→ 走 generate_chart
  · 多行 + 不可视（宽表/纯文本等）→ force_table，合成 type=table 的 chart JSON 并 SSE
  · SSE type=layout 下发 layout / skip_chart / force_table
```

## P2.5 结果展示兜底（已实现）

不改问句 / SQL 生成偏好；仅前端展示层：

```text
问句不含「每月/按月/趋势/…」
且结果：多行 + 恰好 1 个时间维（month 等）+ 1～5 个数值度量
  → SUM 度量 → 上方 Hero / 横排 KPI（期间合计）
  → 下方仍出 Summary + 折线/临时表（明细趋势）
问句已要求按月/趋势 → 不触发，只出图/表
```

实现：`tryAggregateCardFallback`（`resultLayout.ts`）+ `ChartBlock.vue` 挂载。

## P2.6 指标展示名（已实现）

```text
sql-data 之后
  1. 术语表 / 静态友好别名精确匹配列名 → name_zh / name_en（source=terminology|static）
  2. 未命中字段 → LLM 补中英别名（source=llm）
  3. 合并后 SSE type=field-aliases，写入 chat_record.field_aliases
前端 ResultCards / 临时表
  · zh-CN / zh-TW → name_zh
  · 其它语言 → name_en
  · 无别名时回退列名
```

## P3 规则（已实现）

```text
档案字段排序
  · sortProfileFields：id → 文本 → 金额/数值 → 其余（仅 profile）

Summary
  · LLM 失败/空：FE 兜底文案（共 N 行…）
  · set-04 双栏：左洞察 + 右关键数据（末 vs 首变化率；有聚合卡时不重复合计）

折线皮肤（bluecardSkin 门控）
  · 单系列：蓝线 #3b82f6 + 面积 + 实心点 + 默认点标签
  · 多系列：不锁单色；白底卡片 + 图内标题/单位 pill
  · Dashboard/Predict 不传 skin

埋点
  · trackBluecard → CustomEvent sqlbot_bluecard + embedded postMessage
```

## 关键代码

- 布局判定 FE：`frontend/.../bluecard/resultLayout.ts`
- 字段别名 FE：`frontend/.../bluecard/fieldLabel.ts`
- 埋点 FE：`frontend/.../bluecard/track.ts`
- 折线皮肤：`frontend/.../charts/Line.ts`
- 布局判定 BE：`backend/apps/chat/bluecard/layout.py`
- 字段别名 BE：`backend/apps/chat/bluecard/field_aliases.py`
- 卡片 / Summary：`ResultCards.vue` / `SummaryCard.vue`
- 接入：`ChartBlock.vue`、`ChartAnswer.vue`、`DisplayChartBlock.vue`、`task/llm.py`

## 续作提示

下一刀默认 **P4**（柱/条皮肤）或埋点落库。
