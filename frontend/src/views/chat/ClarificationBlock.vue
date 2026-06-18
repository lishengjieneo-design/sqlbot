<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatRecord } from '@/api/chat'
import { enrichTimeCandidates, formatPresetRange } from '@/utils/timeRangePresets'

export type TimeRangeSelection = {
  field: string
  label: string
  date_start?: string
  date_end?: string
}

const props = defineProps<{
  record?: ChatRecord
}>()

const emit = defineEmits<{
  select: [candidate: TimeRangeSelection | { field: string; label: string }]
  newQuestion: []
}>()

const { t, locale } = useI18n()

const clarification = computed(() => props.record?.clarification)
const current = computed(() => clarification.value?.current)
const maxRounds = computed(() => clarification.value?.max_rounds ?? 5)
const askCount = computed(() => clarification.value?.ask_count ?? 1)

const progress = computed(() => {
  const p = clarification.value?.progress
  if (p && (p.total_steps ?? 0) > 0) {
    return {
      total: p.total_steps as number,
      completed: p.completed_steps as number,
      current: p.current_step as number,
      remaining: p.remaining_steps as number,
    }
  }
  const resolved = clarification.value?.resolved?.length ?? 0
  const hasCurrent = !!current.value
  const total = Math.max(resolved + (hasCurrent ? 1 : 0), hasCurrent ? 1 : 0)
  return {
    total,
    completed: resolved,
    current: hasCurrent ? resolved + 1 : resolved,
    remaining: Math.max(0, total - resolved),
  }
})

const progressPercent = computed(() => {
  if (!progress.value.total) return 0
  return Math.round((progress.value.completed / progress.value.total) * 100)
})

const plannedSteps = computed(() => clarification.value?.plan?.steps ?? [])

const isTimeRange = computed(
  () =>
    current.value?.factor_type === 'time_range' || current.value?.factor_key === 'time_range'
)

const rawId = computed(() => current.value?.raw_value || '')
const earliestDate = computed(() => current.value?.earliest_data_date || '2024-01-01')

const candidates = computed(() => {
  const raw = current.value?.candidates || []
  if (!isTimeRange.value) return raw
  return enrichTimeCandidates(raw, earliestDate.value, current.value?.current_date)
})
const TIME_PRESET_I18N_KEYS: Record<string, string> = {
  all_time: 'qa.clarification_time_preset_all',
  today: 'qa.clarification_time_preset_today',
  yesterday: 'qa.clarification_time_preset_yesterday',
  this_week: 'qa.clarification_time_preset_this_week',
  this_month: 'qa.clarification_time_preset_this_month',
  last_7_days: 'qa.clarification_time_preset_last_7_days',
  last_30_days: 'qa.clarification_time_preset_last_30_days',
}

function presetTitle(field?: string, fallback?: string) {
  if (!field) return (fallback || '').trim()
  const key = TIME_PRESET_I18N_KEYS[field]
  return key ? t(key) : (fallback || field).trim()
}

const rangeSep = computed(() => (locale.value?.startsWith('zh') ? '至' : 'to'))

function formatRange(dateStart?: string, dateEnd?: string) {
  return formatPresetRange(dateStart, dateEnd, rangeSep.value)
}

type PresetRow = {
  item: TimeRangeSelection
  index: number
  title: string
  rangeText: string
}

const presetRows = computed((): PresetRow[] =>
  candidates.value
    .map((item: TimeRangeSelection, index: number) => {
      const title = presetTitle(item.field, item.label)
      const rangeText = formatRange(item.date_start, item.date_end)
      if (!title && !rangeText) return null
      return { item, index, title, rangeText }
    })
    .filter((row: PresetRow | null): row is PresetRow => row != null)
)

const customMode = ref<'single' | 'range'>('range')
const customSingle = ref<string>('')
const customRange = ref<[string, string] | null>(null)

watch(
  () => [isTimeRange.value, earliestDate.value] as const,
  () => {
    customMode.value = 'range'
    customSingle.value = ''
    customRange.value = null
  },
  { immediate: true }
)

const pickerDisabledDate = (time: Date) => {
  const min = new Date(earliestDate.value)
  min.setHours(0, 0, 0, 0)
  return time.getTime() < min.getTime()
}

function onPresetClick(row: PresetRow) {
  emit('select', {
    field: row.item.field,
    label: row.item.label || row.title,
    date_start: row.item.date_start,
    date_end: row.item.date_end,
  })
}

function onCustomConfirm() {
  if (customMode.value === 'single') {
    if (!customSingle.value) return
    emit('select', {
      field: 'custom',
      label: t('qa.clarification_time_custom_single'),
      date_start: customSingle.value,
      date_end: customSingle.value,
    })
    return
  }
  if (!customRange.value || customRange.value.length !== 2) return
  const [start, end] = customRange.value
  emit('select', {
    field: 'custom',
    label: t('qa.clarification_time_custom_range'),
    date_start: start,
    date_end: end,
  })
}

function displayLabel(item: { field?: string; label?: string }) {
  return (item.label || '').trim()
}

const visibleIdCandidates = computed(() =>
  candidates.value
    .map((item: { field?: string; label?: string }, index: number) => ({
      item,
      index,
      label: displayLabel(item),
    }))
    .filter((row: { label: string }) => row.label)
)
</script>

<template>
  <div v-if="current" class="clarification-block">
    <div class="clarification-header">
      <span class="clarification-title">
        {{ isTimeRange ? t('qa.clarification_time_title') : t('qa.clarification_title') }}
      </span>
      <span v-if="isTimeRange" class="clarification-round">
        {{ t('qa.clarification_time_hint') }}
      </span>
      <span v-else class="clarification-round">
        {{ t('qa.clarification_round', { current: askCount, max: maxRounds }) }}
      </span>
    </div>

    <div v-if="progress.total > 0" class="clarification-progress">
      <div class="progress-text">
        {{
          t('qa.clarification_progress', {
            current: progress.current,
            total: progress.total,
            remaining: progress.remaining,
          })
        }}
      </div>
      <el-progress
        :percentage="progressPercent"
        :stroke-width="6"
        :show-text="false"
        class="progress-bar"
      />
      <ul v-if="plannedSteps.length" class="progress-steps">
        <li
          v-for="(step, idx) in plannedSteps"
          :key="step.step_key || idx"
          class="progress-step"
          :class="{
            'progress-step--done': idx < progress.completed,
            'progress-step--active': idx === progress.completed && current,
          }"
        >
          <span class="step-index">{{ idx + 1 }}</span>
          <span class="step-label">
            <template v-if="step.factor_type === 'time_range'">
              {{ t('qa.clarification_progress_step_time') }}
            </template>
            <template v-else>
              {{ t('qa.clarification_progress_step_id', { value: step.raw_value }) }}
            </template>
          </span>
        </li>
      </ul>
    </div>

    <p v-if="isTimeRange" class="clarification-summary">
      {{ t('qa.clarification_time_prompt') }}
    </p>
    <p v-else-if="rawId" class="clarification-summary">
      {{ t('qa.clarification_summary', { value: rawId }) }}
    </p>

    <p v-if="isTimeRange" class="clarification-earliest-hint">
      {{ t('qa.clarification_earliest_data_hint', { date: earliestDate }) }}
    </p>

    <!-- Time range presets -->
    <div v-if="isTimeRange && presetRows.length" class="clarification-candidates time-presets">
      <button
        v-for="row in presetRows"
        :key="row.item.field || row.index"
        type="button"
        class="time-preset-btn"
        @click="onPresetClick(row)"
      >
        <span class="preset-title">{{ row.title }}</span>
        <span class="preset-range">{{ row.rangeText }}</span>
      </button>
    </div>

    <!-- Custom date range -->
    <div v-if="isTimeRange && current?.allow_custom_range !== false" class="custom-range-section">
      <div class="custom-range-label">{{ t('qa.clarification_time_custom_title') }}</div>
      <el-radio-group v-model="customMode" class="custom-mode-group" size="small">
        <el-radio-button value="single">{{ t('qa.clarification_time_mode_single') }}</el-radio-button>
        <el-radio-button value="range">{{ t('qa.clarification_time_mode_range') }}</el-radio-button>
      </el-radio-group>
      <div class="custom-picker-row">
        <el-date-picker
          v-if="customMode === 'single'"
          v-model="customSingle"
          type="date"
          value-format="YYYY-MM-DD"
          :placeholder="t('qa.clarification_time_pick_single')"
          :disabled-date="pickerDisabledDate"
          class="custom-picker"
        />
        <el-date-picker
          v-else
          v-model="customRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          :start-placeholder="t('qa.clarification_time_pick_start')"
          :end-placeholder="t('qa.clarification_time_pick_end')"
          :range-separator="rangeSep"
          :disabled-date="pickerDisabledDate"
          class="custom-picker"
        />
        <el-button type="primary" :disabled="customMode === 'single' ? !customSingle : !customRange" @click="onCustomConfirm">
          {{ t('qa.clarification_time_confirm') }}
        </el-button>
      </div>
    </div>

    <!-- ID field presets -->
    <div v-if="!isTimeRange && visibleIdCandidates.length" class="clarification-candidates">
      <el-button
        v-for="row in visibleIdCandidates"
        :key="row.index"
        class="clarification-option-btn"
        :title="row.label"
        @click="emit('select', candidates[row.index])"
      >
        <span class="candidate-label">{{ row.label }}</span>
      </el-button>
    </div>

    <div class="new-question-wrap">
      <el-button class="new-question-btn" plain @click="emit('newQuestion')">
        {{ t('qa.clarification_new_question') }}
      </el-button>
    </div>
  </div>
</template>

<style scoped lang="less">
@text-primary: rgba(31, 35, 41, 1);
@text-secondary: rgba(100, 106, 115, 1);
@border-color: #d9dcdf;
@surface-muted: #f8f9fa;
@surface-card: #fff;

.clarification-block {
  margin: 0;
  padding: 12px 14px 10px;
  position: relative;
  z-index: 1;
  border-radius: 16px;
  border: 1px solid @border-color;
  background: @surface-muted;
}

.clarification-progress {
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: @surface-card;
  border: 1px solid @border-color;
}

.progress-text {
  margin-bottom: 8px;
  font-size: 13px;
  line-height: 20px;
  font-weight: 500;
  color: @text-primary;
}

.progress-bar {
  margin-bottom: 8px;
}

.progress-steps {
  margin: 0;
  padding: 0;
  list-style: none;
}

.progress-step {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
  line-height: 18px;
  color: @text-secondary;

  &--done {
    color: var(--ed-color-primary, rgba(28, 186, 144, 1));

    .step-index {
      background: var(--ed-color-primary-1a, #1cba901a);
      border-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
    }
  }

  &--active {
    color: @text-primary;
    font-weight: 500;

    .step-index {
      background: var(--ed-color-primary, rgba(28, 186, 144, 1));
      border-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
      color: #fff;
    }
  }
}

.step-index {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1px solid @border-color;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 600;
}

.clarification-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.clarification-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 22px;
  color: @text-primary;
}

.clarification-round {
  flex-shrink: 0;
  font-size: 12px;
  line-height: 20px;
  color: @text-secondary;
}

.clarification-summary,
.clarification-earliest-hint {
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 20px;
  color: @text-secondary;
}

.clarification-earliest-hint {
  font-size: 12px;
  line-height: 18px;
}

.clarification-candidates {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

.time-presets {
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
}

.time-preset-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  width: 100%;
  min-height: 52px;
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid @border-color;
  background: @surface-card;
  cursor: pointer;
  text-align: left;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  transition: border-color 0.15s, box-shadow 0.15s;

  &:hover {
    border-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
  }
}

.preset-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
  color: @text-primary;
}

.preset-range {
  font-size: 12px;
  line-height: 18px;
  color: @text-secondary;
  word-break: break-all;
}

.custom-range-section {
  margin-bottom: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px dashed @border-color;
  background: @surface-card;
}

.custom-range-label {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 500;
  color: @text-primary;
}

.custom-mode-group {
  margin-bottom: 10px;
}

.custom-picker-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.custom-picker {
  flex: 1;
  min-width: 200px;
  max-width: 100%;
}

.clarification-option-btn {
  width: 100%;
  height: auto;
  min-height: 44px;
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  white-space: normal;

  --ed-button-text-color: @text-primary;
  --ed-button-hover-text-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
  --ed-button-active-text-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
  --ed-button-bg-color: @surface-card;
  --ed-button-hover-bg-color: var(--ed-color-primary-1a, #1cba901a);
  --ed-button-active-bg-color: var(--ed-color-primary-33, #1cba9033);
  --ed-button-border-color: @border-color;
  --ed-button-hover-border-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
  --ed-button-active-border-color: var(--ed-color-primary, rgba(28, 186, 144, 1));

  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);

  :deep(> span) {
    width: 100%;
    justify-content: flex-start;
  }
}

.candidate-label {
  font-size: 14px;
  font-weight: 500;
  line-height: 22px;
  text-align: left;
  word-break: break-word;
}

.new-question-wrap {
  display: flex;
  justify-content: center;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid @border-color;
}

.new-question-btn {
  min-width: 148px;
  height: 36px;
  padding: 0 22px;
  border-radius: 20px;
  font-size: 14px;
  font-weight: 600;
  line-height: 22px;

  --ed-button-text-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
  --ed-button-border-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
  --ed-button-bg-color: @surface-card;
  --ed-button-hover-text-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
  --ed-button-hover-border-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
  --ed-button-hover-bg-color: var(--ed-color-primary-1a, #1cba901a);
  --ed-button-active-text-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
  --ed-button-active-border-color: var(--ed-color-primary, rgba(28, 186, 144, 1));
  --ed-button-active-bg-color: var(--ed-color-primary-33, #1cba9033);
}
</style>
