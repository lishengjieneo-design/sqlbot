export type TimePresetCandidate = {
  field: string
  label?: string
  date_start?: string
  date_end?: string
}

/** Layout A — calendar period chips (row 1) */
export const TIME_PRESET_CALENDAR_FIELDS = [
  'today',
  'yesterday',
  'this_week',
  'last_week',
  'this_month',
  'last_month',
  'this_year',
] as const

/** Layout A — rolling / all-time chips (row 2) */
export const TIME_PRESET_RANGE_FIELDS = [
  'last_7_days',
  'last_30_days',
  'all_time',
] as const

function parseIsoDate(s: string): Date {
  const [y, m, d] = s.split('-').map(Number)
  const dt = new Date(y, (m || 1) - 1, d || 1)
  dt.setHours(0, 0, 0, 0)
  return dt
}

function toIso(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function clampStart(start: Date, earliest: Date): Date {
  return start.getTime() < earliest.getTime() ? new Date(earliest) : start
}

function weekStartMonday(d: Date): Date {
  const day = d.getDay()
  const diff = day === 0 ? 6 : day - 1
  const monday = new Date(d)
  monday.setDate(d.getDate() - diff)
  monday.setHours(0, 0, 0, 0)
  return monday
}

function buildPresetMap(
  earliestDate: string,
  anchorDate?: string
): Record<string, TimePresetCandidate> {
  const anchor = anchorDate ? parseIsoDate(anchorDate) : new Date()
  anchor.setHours(0, 0, 0, 0)
  const earliest = parseIsoDate(earliestDate)
  const today = anchor
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const weekStart = weekStartMonday(today)
  const lastWeekEnd = new Date(weekStart)
  lastWeekEnd.setDate(weekStart.getDate() - 1)
  const lastWeekStart = new Date(lastWeekEnd)
  lastWeekStart.setDate(lastWeekEnd.getDate() - 6)
  const monthStart = new Date(today.getFullYear(), today.getMonth(), 1)
  monthStart.setHours(0, 0, 0, 0)
  const lastMonthEnd = new Date(monthStart)
  lastMonthEnd.setDate(0) // last day of previous month
  lastMonthEnd.setHours(0, 0, 0, 0)
  const lastMonthStart = new Date(lastMonthEnd.getFullYear(), lastMonthEnd.getMonth(), 1)
  lastMonthStart.setHours(0, 0, 0, 0)
  const yearStart = new Date(today.getFullYear(), 0, 1)
  yearStart.setHours(0, 0, 0, 0)

  const pack = (field: string, start: Date, end: Date) => {
    const s = clampStart(start, earliest)
    let e = end.getTime() < s.getTime() ? new Date(s) : end
    return { field, date_start: toIso(s), date_end: toIso(e) }
  }

  const last7 = new Date(today)
  last7.setDate(today.getDate() - 6)
  const last30 = new Date(today)
  last30.setDate(today.getDate() - 29)

  const presets = [
    pack('all_time', earliest, today),
    pack('today', today, today),
    pack('yesterday', yesterday, yesterday),
    pack('this_week', weekStart, today),
    pack('last_week', lastWeekStart, lastWeekEnd),
    pack('this_month', monthStart, today),
    pack('last_month', lastMonthStart, lastMonthEnd),
    pack('this_year', yearStart, today),
    pack('last_7_days', last7, today),
    pack('last_30_days', last30, today),
  ]
  return Object.fromEntries(presets.map((p) => [p.field, p]))
}

/** Fill missing date_start/date_end on time clarification candidates (legacy payloads). */
export function enrichTimeCandidates(
  candidates: TimePresetCandidate[],
  earliestDate: string,
  currentDate?: string
): TimePresetCandidate[] {
  const presetMap = buildPresetMap(earliestDate, currentDate)
  if (!candidates?.length) {
    return Object.values(presetMap) as TimePresetCandidate[]
  }
  const merged: TimePresetCandidate[] = []
  const seen = new Set<string>()
  for (const item of candidates) {
    const field = item.field
    if (!field) continue
    const base = presetMap[field]
    seen.add(field)
    merged.push({
      ...item,
      date_start: item.date_start || base?.date_start,
      date_end: item.date_end || base?.date_end,
    })
  }
  // Append any new presets not present in legacy payload (e.g. last_week)
  for (const [field, preset] of Object.entries(presetMap)) {
    if (!seen.has(field)) {
      merged.push(preset)
      seen.add(field)
    }
  }
  return merged
}

export function formatPresetRange(
  dateStart?: string,
  dateEnd?: string,
  rangeSep = '至'
): string {
  if (!dateStart) return ''
  if (!dateEnd || dateStart === dateEnd) return dateStart
  return `${dateStart} ${rangeSep} ${dateEnd}`
}
