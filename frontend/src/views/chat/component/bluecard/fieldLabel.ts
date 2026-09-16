/** BlueCard field display labels: terminology/LLM aliases × UI locale. */

export type FieldAlias = {
  field: string
  name_zh?: string
  name_en?: string
  source?: string
}

export function isZhLocale(locale?: string): boolean {
  const l = (locale || '').toLowerCase()
  return l.startsWith('zh')
}

/** Prefer zh for zh-CN / zh-TW; otherwise English. */
export function resolveFieldDisplayName(
  field: string,
  aliases?: FieldAlias[] | null,
  locale?: string
): string {
  if (!field) return ''
  const item = (aliases || []).find(
    (a) => a && a.field && String(a.field).toLowerCase() === String(field).toLowerCase()
  )
  if (!item) return field
  const useZh = isZhLocale(locale)
  const zh = (item.name_zh || '').trim()
  const en = (item.name_en || '').trim()
  if (useZh) return zh || en || field
  return en || zh || field
}

export function aliasesToMap(aliases?: FieldAlias[] | null): Record<string, FieldAlias> {
  const out: Record<string, FieldAlias> = {}
  for (const a of aliases || []) {
    if (a?.field) out[a.field] = a
  }
  return out
}
