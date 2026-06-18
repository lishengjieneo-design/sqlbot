/** Format resolved clarification entries into a single display line for result headers. */
export function formatClarifiedRequirements(
  clarification?: Record<string, unknown> | null
): string {
  const resolved = clarification?.resolved
  if (!Array.isArray(resolved) || !resolved.length) {
    return ''
  }
  const parts: string[] = []
  for (const item of resolved) {
    if (!item || typeof item !== 'object') continue
    const row = item as Record<string, unknown>
    const label = String(row.label || row.free_text || '').trim()
    if (label) {
      parts.push(label)
    }
  }
  return parts.join(' · ')
}

export function shouldShowClarifiedRequirementLine(
  record?: {
    question?: string
    clarification?: Record<string, unknown>
    clarification_resolved?: boolean
    clarification_abandoned?: boolean
  } | null
): boolean {
  if (!record || record.clarification_abandoned) {
    return false
  }
  const line = formatClarifiedRequirements(record.clarification)
  if (!line) {
    return false
  }
  return !!(record.clarification_resolved || record.clarification?.resolved)
}
