/** Lightweight BlueCard analytics — CustomEvent + embedded postMessage. */

export type BluecardTrackEvent =
  | 'layout_show'
  | 'summary_hit'
  | 'summary_miss'
  | 'aggregate_fallback'
  | 'line_skin'

export function trackBluecard(
  event: BluecardTrackEvent,
  payload: Record<string, unknown> = {}
): void {
  const detail = {
    event,
    ts: Date.now(),
    ...payload,
  }
  try {
    window.dispatchEvent(new CustomEvent('sqlbot_bluecard', { detail }))
  } catch {
    /* ignore */
  }
  try {
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ type: 'sqlbot_bluecard', ...detail }, '*')
    }
  } catch {
    /* ignore */
  }
  if (typeof console !== 'undefined' && console.debug) {
    console.debug('[bluecard]', event, payload)
  }
}
