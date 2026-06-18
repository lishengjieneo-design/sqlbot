import type { RouteRecordRaw, Router } from 'vue-router'
import Appearance from '@/views/system/appearance/index.vue'
import Authentication from '@/views/system/authentication/index.vue'
import Platform from '@/views/system/platform/index.vue'
import Audit from '@/views/system/audit/index.vue'
import { i18n } from '@/i18n'

const t = i18n.global.t

/** Routes hidden by xpack LicenseGenerator when license is invalid; restore for OSS. */
export const OSS_SETTING_CHILDREN: RouteRecordRaw[] = [
  {
    path: 'appearance',
    name: 'appearance',
    component: Appearance,
    meta: { title: t('system.appearance_settings') },
  },
  {
    path: 'authentication',
    name: 'authentication',
    component: Authentication,
    meta: { title: t('system.authentication_settings') },
  },
  {
    path: 'platform',
    name: 'platform',
    component: Platform,
    meta: { title: t('platform.title') },
  },
]

export const OSS_SYSTEM_CHILDREN: RouteRecordRaw[] = [
  {
    path: 'audit',
    name: 'audit',
    component: Audit,
    meta: { title: t('audit.system_log'), iconActive: 'log', iconDeActive: 'noLog' },
  },
]

const SETTING_MENU_ORDER = ['appearance', 'parameter', 'variables', 'authentication', 'platform']

export function ensureOssSystemRoutes(router: Router) {
  OSS_SETTING_CHILDREN.forEach((route) => {
    if (!router.hasRoute(route.name as string)) {
      router.addRoute('setting', route)
    }
  })
  OSS_SYSTEM_CHILDREN.forEach((route) => {
    if (!router.hasRoute(route.name as string)) {
      router.addRoute('system', route)
    }
  })
}

/** LicenseGenerator mutates setting.children in-place; merge OSS entries for sidebar menu. */
export function mergeOssSystemMenu(children: any[] = []) {
  const merged = children.map((item) => {
    if (item.name !== 'setting') {
      return item
    }
    const basePath = item.path || '/system/setting'
    const existing = [...(item.children || [])]
    const names = new Set(existing.map((child: any) => child.name))
    OSS_SETTING_CHILDREN.forEach((route) => {
      if (names.has(route.name)) {
        return
      }
      existing.push({
        ...route,
        path: `${basePath}/${route.path}`.replace(/\/+/g, '/'),
        children: [],
      })
    })
    existing.sort((a, b) => {
      const ai = SETTING_MENU_ORDER.indexOf(a.name)
      const bi = SETTING_MENU_ORDER.indexOf(b.name)
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
    })
    return { ...item, children: existing }
  })

  if (merged.some((item) => item.name === 'audit')) {
    return merged
  }

  const auditRoute = OSS_SYSTEM_CHILDREN[0]
  return [
    ...merged,
    {
      ...auditRoute,
      path: `/system/${auditRoute.path}`,
      children: [],
    },
  ]
}
