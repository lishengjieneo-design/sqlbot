import { i18n } from '@/i18n'

const LEGACY_SITE_NAMES = ['sqlbot', 'sqlbot test', 'sqlbottest']

export function resolveSiteName(configured?: string): string {
  const name = configured?.trim()
  if (name && !LEGACY_SITE_NAMES.includes(name.toLowerCase())) {
    return name
  }
  return i18n.global.t('brand.site_name')
}

export function resolveAssistantName(): string {
  return i18n.global.t('brand.assistant_name')
}

function normalizeLegacyWelcome(text: string): string {
  return text.replace(/SQLBot/gi, resolveAssistantName())
}

export function formatPcWelcome(template: string | undefined, userName: string): string {
  const t = i18n.global.t
  const fallback = t('brand.pc_welcome_default')
  const text = normalizeLegacyWelcome(template?.trim() || fallback)
  const name = userName.trim()
  if (!name) {
    return text.replace(/\{name\}/g, '').replace(/，，/g, '，').replace(/,,/g, ',')
  }
  if (text.includes('{name}')) {
    return text.replace(/\{name\}/g, name)
  }
  if (/^你好/.test(text)) {
    const suffix = text.replace(/^你好[，,]?\s*/, '')
    return `你好，${name}，${suffix}`
  }
  if (/^Hello/i.test(text)) {
    const suffix = text.replace(/^Hello,?\s*/i, '')
    return `Hello, ${name}, ${suffix}`
  }
  return `${text}，${name}`
}
