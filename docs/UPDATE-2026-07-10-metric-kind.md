# 更新记录：术语指标语义（metric_kind）与问数时间规则

**日期：** 2026-07-10  
**环境：** ECS 测试 8000（`sqlbot_dev` / http://47.83.2.158:8000/）  
**状态：** 已部署上线（含一次热修复）

---

## 1. 背景与目标

在问数流程中，不同业务指标对「时间」的要求不同：

- **发生型指标**（flow）：可在时间段内累加，查询必须有时间范围
- **余额型指标**（balance）：某时点快照，无时间时可取最新数据

此前所有问题统一走全局时间澄清，导致如 `8004的账户余额` 等余额查询被误拦。本次在**术语配置**中新增 `metric_kind`，按命中术语类型决定时间澄清与 SQL 时间校验行为。

---

## 2. 产品规则（已确认）

### 2.1 字段设计

| 项 | 结论 |
|----|------|
| 字段名 | `metric_kind` |
| 前端 | 一个下拉，四选一，**必填** |
| 存库枚举 | `flow` / `balance` / `org_dimension` / `product_dimension` |
| 组织/产品维度 | 仅存储，暂不参与澄清、校验、prompt |
| 传给 LLM | 术语 XML 中带 `<metric_kind>`；具体 SQL 规则由**自定义 prompt** 维护 |

### 2.2 术语匹配

- 子串匹配 + embedding 匹配 **同等对待**
- 未命中任何术语 → **维持现有全局**时间澄清 + SQL 时间校验
- 一条术语只能一种 kind；description 混有两种指标须拆成两条
- 运营在后台自行配置；新建/编辑 **必填**

### 2.3 时间规则

| 场景 | 时间澄清 | SQL 时间校验 |
|------|----------|--------------|
| **仅 flow** | 无明确时间 → 澄清 | 强制 |
| **仅 balance** | 不澄清 | **豁免** |
| **flow + balance** | 无时间 → 只澄清 flow；有时间 → 不澄清 | flow 强制；balance 豁免逻辑不整体跳过 |
| **未命中术语** | 全局逻辑 | 全局逻辑 |

**「明确时间」（flow 用，严格模式）：**

- ✅ `最近一个月`、`本月`、`昨天`、具体日期
- ❌ 单独 `最近`、`近期`（无数量）→ 仍需澄清

**余额型 + 用户写了时间：**

| 用户输入 | 处理 |
|----------|------|
| 准确时点（昨天、2024-06-01） | 传给 LLM（`<balance-time-hint>`） |
| 时间范围（最近一个月） | 报错：「余额型指标不能取时间范围，请提供一个时间节点」 |
| 多个时间节点 | 全部传给 LLM |

**混合场景（flow + balance）：**

- 发生型：使用用户的时间范围
- 余额型：由 LLM 自行判断取哪个时点
- 澄清完成后注入 mixed hint；澄清顺序不变：**时间 → ID → SQL**

**余额「取最新」（自定义 prompt 中说明，系统不硬编码 SQL）：**

- 有快照日期 → `MAX(snapshot_date)`
- 无快照日期字段 → 直接查表（表内始终为最新）

### 2.4 配置开关

```python
METRIC_KIND_TIME_RULES_ENABLED = True  # backend/common/core/config.py
```

---

## 3. 代码改动清单

### 3.1 数据库

| 文件 | 说明 |
|------|------|
| `backend/alembic/versions/069_add_terminology_metric_kind.py` | 新增 `terminology.metric_kind`，现有数据默认 `flow` |

### 3.2 后端

| 文件 | 说明 |
|------|------|
| `backend/apps/terminology/metric_kind.py` | 枚举、标签解析、场景常量 |
| `backend/apps/terminology/models/terminology_model.py` | 模型 + DTO 增加 `metric_kind` |
| `backend/apps/terminology/curd/terminology.py` | CRUD 校验、查询、XML 输出、批量导入 |
| `backend/apps/terminology/api/terminology.py` | Excel 模板/导入/导出第 6 列 |
| `backend/apps/chat/metric_kind_resolver.py` | 命中术语 → 场景判定 |
| `backend/apps/chat/balance_time_handler.py` | 余额型时点/区间/多时点 |
| `backend/apps/chat/time_range_prefilter.py` | 新增 `question_has_explicit_time_constraint()` |
| `backend/apps/chat/task/llm.py` | prefilter 分支、mixed/balance hint、SQL 校验豁免 |
| `backend/common/core/config.py` | `METRIC_KIND_TIME_RULES_ENABLED` |
| `backend/locales/zh-CN.json` 等 | 术语相关 i18n |
| `backend/tests/test_metric_kind.py` | 单元测试 |

### 3.3 前端

| 文件 | 说明 |
|------|------|
| `frontend/src/views/system/professional/index.vue` | 必填下拉、列表列、详情 |
| `frontend/src/i18n/zh-CN.json` 等 | `professional.metric_kind_*` 文案 |

### 3.4 术语 XML 示例（注入 LLM）

```xml
<terminologies>
  <terminology>
    <words><word>入金</word></words>
    <description>...</description>
    <metric_kind>flow</metric_kind>
  </terminology>
</terminologies>
```

### 3.5 动态 hint（不改 system prompt）

- `<balance-time-hint>`：余额时点/多时点说明
- `<metric-kind-hint>`：混合场景下 flow 用时间范围、balance 由 LLM 选时点

---

## 4. 部署记录

| 项 | 内容 |
|----|------|
| 部署方式 | `scripts/deploy-test-ecs-win.py` |
| 目标 | `/opt/sqlbot_dev`，容器 `sqlbot_dev`，端口 **8000** |
| 未影响 | POC **8004**（`sqlbot` 容器） |
| 迁移 | 容器内 `alembic upgrade head` |
| 验证 | 容器 healthy；HTTP 200；`metric_kind` 列存在 |

### 4.1 部署热修复

首次部署后发现 `balance_time_handler.py` 中 `_CN_RELATIVE_DURATION` 为字符串片段未编译为正则，导致 `AttributeError`。已修复为 `_CN_RELATIVE_DURATION_RE = re.compile(...)` 并二次部署。

---

## 5. 上线后运营配置

1. **术语配置** → 每条术语设置「指标语义」  
   - 入金 / 出金 / 业绩 / 返佣等 → **发生型指标**  
   - 账户余额 / 净值等 → **余额型指标**
2. 现有术语迁移后默认为 `flow`，余额类需手动修改
3. **自定义 prompt** 中补充 flow/balance 的 SQL 写法（系统只传 `metric_kind`）

---

## 6. 验收用例

### 仅发生型（flow）

| # | 问题 | 预期 |
|---|------|------|
| F1 | `12312421 入金` | 弹时间澄清 |
| F2 | `12312421 最近一个月入金` | 不弹时间澄清 |
| F3 | `12312421 最近入金` | 弹时间澄清（「最近」无数量） |
| F4 | `12312421 本月入金` | 不弹时间澄清 |

### 仅余额型（balance）

| # | 问题 | 预期 |
|---|------|------|
| B1 | `8004的账户余额` | 不弹时间澄清；SQL 豁免时间校验 |
| B2 | `8004 昨天的账户余额` | 不澄清；时点传给 LLM |
| B3 | `8004 最近一个月的账户余额` | 提示余额型不能取时间范围 |
| B4 | `8004 2024-06-01和2024-06-15的余额` | 多时点传给 LLM |

### 混合（flow + balance）

| # | 问题 | 预期 |
|---|------|------|
| M1 | `8004 入金和余额` | 只澄清 flow 时间 |
| M2 | `8004 最近一个月入金和余额` | 不澄清；flow 用区间；balance 由 LLM 选时点 |
| M3 | `8004 昨天入金和余额` | 不澄清；flow 用昨天 |

### 未命中术语

| # | 问题 | 预期 |
|---|------|------|
| N1 | 未配置术语的业务词（无时间） | 走现有全局时间澄清 |

---

## 7. 关联历史问题（同周期其他修复）

以下为本周期内**另项**修复，与 metric_kind 独立，一并记录供对照：

| 问题 | 原因 | 处理 |
|------|------|------|
| `12312421 出入金，最近一个月` 仍弹「请补充时间范围」 | 旧正则不认「最近一个月」（汉字「一」） | 扩展 `time_range_prefilter.py` 中英文数量词；部署后改为 ID 澄清（非时间澄清） |
| `8004的账户余额` SQL 报错无时间过滤 | 全局 `SQL_TIME_FILTER_VALIDATION` | metric_kind=balance 后豁免；术语需配置为 balance |

---

## 8. Excel 导入模板变更

术语 Excel 增加第 6 列 **指标语义**，支持值：

- 中文：`发生型指标` / `余额型指标` / `组织维度` / `产品维度`
- 英文：`flow` / `balance` / `org_dimension` / `product_dimension`

旧版 5 列模板导入将因缺少 `metric_kind` 而校验失败，请使用新模板。

---

## 9. 本地仓库路径

```
C:\Users\Neo\Downloads\sqlbot
```

GitHub：`https://github.com/lishengjieneo-design/sqlbot.git`（本次改动尚未提交，如需 commit 请另行说明）

---

*文档生成：2026-07-10*
