/** BlueCard (蓝卡出图) — P0 layout resolver for single-row vs multi-row results. */

export type BluecardLayout = 'empty' | 'hero' | 'metrics' | 'profile' | 'chart'

const CURRENCY_PREFIX = /^[$¥€£]\s*/
const PERCENT_SUFFIX = /%$/
/** GTC forex amounts default to USD. */
const AMOUNT_CURRENCY = '$'
const NUMBER_LOCALE = 'en-US'

/** Count / qty fields — never treat as money even if name contains 入金 etc. */
const COUNT_FIELD_RE =
  /(笔数|次数|数量|个数|条数|人数|count|qty|quantity|num|rows?|cnt)(_|$)/i

/** Amount / money field name heuristics. */
const AMOUNT_FIELD_RE =
  /(金额|入金|出金|净入金|余额|净值|权益|amount|deposit|withdraw|withdrawal|balance|equity|money|usd|cny|profit|pnl|fee|commission|返佣|手续费|业绩|swap|volume|credit)/i

const PERCENT_FIELD_RE = /(比率|比例|占比|百分比|rate|ratio|percent|pct|增长率|涨跌)/i

/** Identifiers — keep raw digits, no thousands / currency. */
const ID_FIELD_RE =
  /(^id$|_id$|账号|账户|帐户|客户号|login|account|uid|uuid|mt4|mt5|ticket|order_?id)/i

export function isNumericLike(value: unknown): boolean {
  return parseCardNumber(value) !== null
}

export function isAmountField(field?: string): boolean {
  if (!field) return false
  const n = field.trim()
  if (!n || COUNT_FIELD_RE.test(n) || ID_FIELD_RE.test(n)) return false
  return AMOUNT_FIELD_RE.test(n)
}

export function isPercentField(field?: string): boolean {
  if (!field) return false
  return PERCENT_FIELD_RE.test(field.trim())
}

export function isIdField(field?: string): boolean {
  if (!field) return false
  return ID_FIELD_RE.test(field.trim())
}

/** Parse SQL / JSON cell into a finite number (strips $, commas, %). */
export function parseCardNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'boolean') return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  const raw = String(value).trim()
  if (!raw) return null
  const cleaned = raw.replace(/,/g, '').replace(CURRENCY_PREFIX, '').replace(PERCENT_SUFFIX, '').trim()
  if (!cleaned) return null
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : null
}

/** Question explicitly asks for time-series / period breakdown. */
const TIME_SERIES_QUESTION_RE =
  /(每月|逐月|按月|分月|各月|每月份|按周|每周|按日|每日|按天|每天|趋势|走势|变化|曲线|折线|对比各月|月度明细)/i

/** Column names that look like a time / period dimension. */
const TIME_DIM_FIELD_RE =
  /^(month|year|week|date|day|dt|period|stat_month|biz_month|year_month|ym|月份|年月|周|日期|时间)$|(^|_)(month|year|week|date|day|period)(_|$)|月份|年月/i

export function questionImpliesTimeSeriesBreakdown(question?: string): boolean {
  if (!question || !question.trim()) return false
  return TIME_SERIES_QUESTION_RE.test(question.trim())
}

export function isTimeDimField(field?: string): boolean {
  if (!field) return false
  return TIME_DIM_FIELD_RE.test(field.trim())
}

function orderedFields(
  fields: string[] | undefined,
  row: Record<string, unknown>
): string[] {
  if (fields && fields.length > 0) return fields
  return Object.keys(row)
}

function classifyRowCols(
  ordered: string[],
  row: Record<string, unknown>
): { numericCols: string[]; textCols: string[] } {
  const numericCols = ordered.filter((c) => isNumericLike(row[c]))
  const textCols = ordered.filter((c) => {
    const v = row[c]
    if (v === null || v === undefined) return false
    if (isNumericLike(v)) return false
    return String(v).trim() !== ''
  })
  return { numericCols, textCols }
}

function resolveSingleRowLayout(
  ordered: string[],
  row: Record<string, unknown>
): Exclude<BluecardLayout, 'empty' | 'chart'> {
  const { numericCols, textCols } = classifyRowCols(ordered, row)
  if (numericCols.length === 1 && textCols.length === 0) return 'hero'
  if (numericCols.length >= 2 && numericCols.length <= 5 && textCols.length <= 1) return 'metrics'
  if (numericCols.length === 1 && textCols.length <= 1 && ordered.length <= 2) return 'hero'
  if (numericCols.length >= 1 && numericCols.length <= 5 && textCols.length === 0) return 'metrics'
  return 'profile'
}

export type AggregateCardFallback = {
  fields: string[]
  row: Record<string, unknown>
  layout: 'hero' | 'metrics'
  timeField: string
}

/**
 * Display fallback: when the question did not ask for 每月/趋势, but SQL returned a
 * time-series (e.g. month + multiple amounts), SUM numeric measures into one KPI row.
 */
export function tryAggregateCardFallback(
  fields: string[] | undefined,
  rows: Array<Record<string, unknown>> | undefined,
  question?: string
): AggregateCardFallback | null {
  if (!rows || rows.length <= 1) return null
  if (questionImpliesTimeSeriesBreakdown(question)) return null

  const ordered = orderedFields(fields, rows[0] || {})
  const timeFields = ordered.filter((f) => isTimeDimField(f))
  if (timeFields.length !== 1) return null
  const timeField = timeFields[0]

  // Collect numeric measure columns (exclude the time dim even if parseable as number)
  const measureFields = ordered.filter((f) => {
    if (f === timeField) return false
    // Prefer columns that look numeric across rows
    return rows.some((r) => isNumericLike(r?.[f]))
  })
  if (measureFields.length < 1 || measureFields.length > 5) return null

  const aggregated: Record<string, unknown> = {}
  for (const f of measureFields) {
    let sum = 0
    let hit = 0
    for (const r of rows) {
      const n = parseCardNumber(r?.[f])
      if (n === null) continue
      sum += n
      hit += 1
    }
    if (hit === 0) return null
    aggregated[f] = sum
  }

  const layout = resolveSingleRowLayout(measureFields, aggregated)
  if (layout !== 'hero' && layout !== 'metrics') return null

  return {
    fields: measureFields,
    row: aggregated,
    layout,
    timeField,
  }
}

export function resolveBluecardLayout(
  fields: string[] | undefined,
  rows: Array<Record<string, unknown>> | undefined
): BluecardLayout {
  if (!rows || rows.length === 0) return 'empty'
  if (rows.length > 1) return 'chart'

  const row = rows[0] || {}
  const ordered = orderedFields(fields, row)
  return resolveSingleRowLayout(ordered, row)
}

/**
 * Profile card field order: id/contact → other text → amounts/numbers → rest.
 * Does not change SQL order for hero/metrics/charts.
 */
export function sortProfileFields(
  fields: string[] | undefined,
  row: Record<string, unknown>
): string[] {
  const ordered = orderedFields(fields, row)
  const rank = (f: string): number => {
    if (isIdField(f)) return 0
    const v = row?.[f]
    if (isAmountField(f)) return 2
    if (isNumericLike(v)) return 2
    if (v !== null && v !== undefined && String(v).trim() !== '') return 1
    return 3
  }
  return [...ordered].sort((a, b) => {
    const d = rank(a) - rank(b)
    if (d !== 0) return d
    return ordered.indexOf(a) - ordered.indexOf(b)
  })
}

/** Period change rate (last vs first) for Summary key metric. */
export function computePeriodChangeRate(
  rows: Array<Record<string, unknown>> | undefined,
  measureField?: string
): { field: string; rate: number; first: number; last: number } | null {
  if (!rows || rows.length < 2 || !measureField) return null
  const first = parseCardNumber(rows[0]?.[measureField])
  const last = parseCardNumber(rows[rows.length - 1]?.[measureField])
  if (first === null || last === null) return null
  if (first === 0) {
    if (last === 0) return { field: measureField, rate: 0, first, last }
    return null
  }
  return {
    field: measureField,
    rate: ((last - first) / Math.abs(first)) * 100,
    first,
    last,
  }
}

export function formatChangeRate(rate: number): string {
  const sign = rate > 0 ? '+' : ''
  const body = rate.toLocaleString('en-US', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })
  return `${sign}${body}%`
}

function formatPlainNumber(num: number, fractionDigits: number): string {
  const rounded =
    fractionDigits <= 0
      ? Math.round(num)
      : Math.round(num * 10 ** fractionDigits) / 10 ** fractionDigits
  const isInt = Math.abs(rounded - Math.round(rounded)) < 1e-9
  if (isInt) {
    return Math.round(rounded).toLocaleString(NUMBER_LOCALE)
  }
  return rounded.toLocaleString(NUMBER_LOCALE, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  })
}

/**
 * Display formatter for bluecard values.
 * - amount fields → `$1,284,500.00` (2 dp + thousands + currency)
 * - percent → `12.40%`
 * - other numbers → thousands + up to 2 dp (integers have no decimal)
 * - non-numeric → string as-is
 */
export function formatCardValue(value: unknown, field?: string): string {
  if (value === null || value === undefined || value === '') return '—'

  // Keep account / id cells unformatted (no thousands separators)
  if (isIdField(field)) return String(value)

  const rawStr = typeof value === 'string' ? value.trim() : ''
  const hadPercent = typeof value === 'string' && PERCENT_SUFFIX.test(rawStr)
  const num = parseCardNumber(value)
  if (num === null) return String(value)

  if (hadPercent || isPercentField(field)) {
    return `${formatPlainNumber(num, 2)}%`
  }

  if (isAmountField(field)) {
    const body = num.toLocaleString(NUMBER_LOCALE, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
    return `${AMOUNT_CURRENCY}${body}`
  }

  // Generic numeric: round to 2 dp, keep thousands; drop .00 for whole numbers
  return formatPlainNumber(num, 2)
}
