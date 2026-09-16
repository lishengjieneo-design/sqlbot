<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  formatCardValue,
  isNumericLike,
  sortProfileFields,
  type BluecardLayout,
} from './resultLayout'
import { resolveFieldDisplayName, type FieldAlias } from './fieldLabel'

const props = defineProps<{
  id?: string | number
  layout: Exclude<BluecardLayout, 'chart'>
  fields: string[]
  row: Record<string, unknown>
  title?: string
  fieldAliases?: FieldAlias[] | null
}>()

const { t, locale } = useI18n()

const orderedFields = computed(() => {
  if (props.fields?.length) return props.fields
  return Object.keys(props.row || {})
})

const numericFields = computed(() =>
  orderedFields.value.filter((f) => isNumericLike(props.row?.[f]))
)

const textFields = computed(() =>
  orderedFields.value.filter((f) => {
    const v = props.row?.[f]
    if (v === null || v === undefined) return false
    if (isNumericLike(v)) return false
    return String(v).trim() !== ''
  })
)

const heroField = computed(() => numericFields.value[0] || orderedFields.value[0])

const metricEntries = computed(() => {
  const nums = numericFields.value
  if (nums.length >= 2) return nums.slice(0, 5)
  // single numeric + optional one text → still show numeric as metrics if layout says metrics
  return (nums.length ? nums : orderedFields.value).slice(0, 5)
})

const profileEntries = computed(() => {
  const sorted = sortProfileFields(orderedFields.value, props.row || {})
  return sorted.map((field) => ({
    field,
    label: resolveFieldDisplayName(field, props.fieldAliases, locale.value),
    value: formatCardValue(props.row?.[field], field),
    emphasize: isNumericLike(props.row?.[field]),
  }))
})

const avatarLetter = computed(() => {
  const firstText = textFields.value[0]
  if (!firstText) return 'G'
  const raw = String(props.row?.[firstText] || '').trim()
  return (raw[0] || 'G').toUpperCase()
})

function labelOf(field: string): string {
  return resolveFieldDisplayName(field, props.fieldAliases, locale.value)
}
</script>

<template>
  <div :id="'bluecard-component-' + (id ?? 'default')" class="bluecard-root">
    <div v-if="layout === 'empty'" class="bluecard-empty">
      <div class="bluecard-empty-icon" />
      <div class="bluecard-empty-title">{{ t('chat.bluecard.empty_title') }}</div>
      <div class="bluecard-empty-hint">{{ t('chat.bluecard.empty_hint') }}</div>
    </div>

    <div v-else-if="layout === 'hero'" class="bluecard-hero">
      <div class="bluecard-hero-label">{{ labelOf(heroField) }}</div>
      <div class="bluecard-hero-value">{{ formatCardValue(row?.[heroField], heroField) }}</div>
      <div v-if="title" class="bluecard-hero-caption">{{ title }}</div>
    </div>

    <div v-else-if="layout === 'metrics'" class="bluecard-metrics">
      <div v-if="title" class="bluecard-metrics-title" :title="title">{{ title }}</div>
      <div class="bluecard-metrics-grid">
        <div
          v-for="field in metricEntries"
          :key="field"
          class="bluecard-metric-tile"
        >
          <div class="bluecard-metric-label">{{ labelOf(field) }}</div>
          <div class="bluecard-metric-value">{{ formatCardValue(row?.[field], field) }}</div>
        </div>
      </div>
    </div>

    <div v-else class="bluecard-profile">
      <div class="bluecard-profile-header">
        <div class="bluecard-avatar">{{ avatarLetter }}</div>
        <div class="bluecard-profile-title">
          {{ title || t('chat.bluecard.profile_title') }}
        </div>
      </div>
      <div class="bluecard-profile-list">
        <div
          v-for="item in profileEntries"
          :key="item.field"
          class="bluecard-profile-row"
        >
          <span class="bluecard-profile-key">{{ item.label }}</span>
          <span
            class="bluecard-profile-val"
            :class="{ emphasize: item.emphasize }"
          >{{ item.value }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
<style scoped lang="less">
@blue: #3b82f6;
@blue-soft: rgba(59, 130, 246, 0.12);
@text: #1f2329;
@muted: #646a73;
@border: #e5e6eb;
@card-shadow: 0 4px 16px rgba(31, 35, 41, 0.06);

.bluecard-root {
  width: 100%;
  min-height: 120px;
}

.bluecard-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 16px;
  background: #fff;
  border: 1px dashed @border;
  border-radius: 12px;
  .bluecard-empty-icon {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: @blue-soft;
    margin-bottom: 12px;
  }
  .bluecard-empty-title {
    font-size: 16px;
    font-weight: 600;
    color: @text;
  }
  .bluecard-empty-hint {
    margin-top: 6px;
    font-size: 13px;
    color: @muted;
  }
}

.bluecard-hero {
  position: relative;
  padding: 28px 28px 24px;
  background: #fff;
  border: 1px solid @border;
  border-radius: 12px;
  box-shadow: @card-shadow;
  overflow: hidden;
  &::before {
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 4px;
    background: @blue;
  }
  .bluecard-hero-label {
    font-size: 13px;
    color: @muted;
    margin-bottom: 8px;
  }
  .bluecard-hero-value {
    font-size: 36px;
    line-height: 1.2;
    font-weight: 700;
    color: @text;
    word-break: break-all;
  }
  .bluecard-hero-caption {
    margin-top: 10px;
    font-size: 12px;
    color: @muted;
  }
}

.bluecard-metrics {
  .bluecard-metrics-title {
    margin: 0 0 12px;
    font-size: 15px;
    font-weight: 600;
    line-height: 22px;
    color: @text;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .bluecard-metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
  }
  .bluecard-metric-tile {
    position: relative;
    padding: 16px 16px 16px 18px;
    background: #fff;
    border: 1px solid @border;
    border-radius: 12px;
    box-shadow: @card-shadow;
    overflow: hidden;
    &::before {
      content: '';
      position: absolute;
      left: 0;
      top: 0;
      bottom: 0;
      width: 3px;
      background: @blue;
    }
  }
  .bluecard-metric-label {
    font-size: 12px;
    color: @muted;
    margin-bottom: 8px;
  }
  .bluecard-metric-value {
    font-size: 22px;
    font-weight: 700;
    color: @text;
    word-break: break-all;
  }
}

.bluecard-profile {
  background: #fff;
  border: 1px solid @border;
  border-radius: 12px;
  box-shadow: @card-shadow;
  padding: 16px 20px 8px;
  .bluecard-profile-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
  }
  .bluecard-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: @blue;
    color: #fff;
    font-weight: 700;
    font-size: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .bluecard-profile-title {
    font-size: 15px;
    font-weight: 600;
    color: @text;
  }
  .bluecard-profile-row {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    padding: 10px 0;
    border-top: 1px solid #f0f1f3;
    font-size: 13px;
  }
  .bluecard-profile-key {
    color: @muted;
    flex-shrink: 0;
  }
  .bluecard-profile-val {
    color: @text;
    text-align: right;
    word-break: break-all;
    &.emphasize {
      font-weight: 600;
      color: @blue;
    }
  }
}
</style>
