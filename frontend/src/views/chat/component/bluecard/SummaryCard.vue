<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import MdComponent from '@/views/chat/component/MdComponent.vue'

const props = defineProps<{
  summary?: string
  loading?: boolean
  /** Local fallback when LLM summary missing */
  fallbackText?: string
  /** Right-column key metric (set-04) */
  keyMetricValue?: string
  keyMetricLabel?: string
}>()

const { t } = useI18n()

const hasSummary = computed(() => !!(props.summary && String(props.summary).trim()))
const hasFallback = computed(() => !!(props.fallbackText && String(props.fallbackText).trim()))
const displayText = computed(() =>
  hasSummary.value ? String(props.summary).trim() : String(props.fallbackText || '').trim()
)
const hasContent = computed(() => hasSummary.value || hasFallback.value)
const showKeyMetric = computed(
  () => !!(props.keyMetricValue && String(props.keyMetricValue).trim())
)
const visible = computed(() => hasContent.value || props.loading || showKeyMetric.value)
</script>

<template>
  <div v-if="visible" class="bluecard-summary" :class="{ 'has-metric': showKeyMetric }">
    <div class="bluecard-summary-main">
      <div class="bluecard-summary-icon" aria-hidden="true" />
      <div class="bluecard-summary-body">
        <div class="bluecard-summary-title">{{ t('chat.bluecard.summary_title') }}</div>
        <div v-if="loading && !hasContent" class="bluecard-summary-loading">
          {{ t('chat.bluecard.summary_loading') }}
        </div>
        <MdComponent
          v-else-if="hasSummary"
          :message="summary"
          class="bluecard-summary-md"
        />
        <div v-else-if="hasFallback" class="bluecard-summary-fallback">
          {{ displayText }}
        </div>
      </div>
    </div>
    <div v-if="showKeyMetric" class="bluecard-summary-metric">
      <div class="bluecard-summary-metric-title">
        {{ t('chat.bluecard.key_metric_title') }}
      </div>
      <div class="bluecard-summary-metric-value">{{ keyMetricValue }}</div>
      <div v-if="keyMetricLabel" class="bluecard-summary-metric-label">
        {{ keyMetricLabel }}
      </div>
    </div>
  </div>
</template>

<style scoped lang="less">
@blue: #3b82f6;
@border: #e5e6eb;
@text: #1f2329;
@muted: #646a73;

.bluecard-summary {
  display: flex;
  gap: 0;
  align-items: stretch;
  padding: 16px 18px;
  margin-bottom: 12px;
  background: #fff;
  border: 1px solid @border;
  border-radius: 12px;
  box-shadow: 0 4px 16px rgba(31, 35, 41, 0.06);
  &.has-metric {
    padding-right: 0;
  }
}

.bluecard-summary-main {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  flex: 1;
  min-width: 0;
}

.bluecard-summary-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(59, 130, 246, 0.12);
  position: relative;
  &::after {
    content: '';
    position: absolute;
    left: 50%;
    top: 50%;
    width: 12px;
    height: 16px;
    transform: translate(-50%, -52%);
    border-radius: 50% 50% 40% 40%;
    background: @blue;
    opacity: 0.85;
  }
}

.bluecard-summary-body {
  flex: 1;
  min-width: 0;
}

.bluecard-summary-title {
  font-size: 14px;
  font-weight: 600;
  color: @text;
  margin-bottom: 6px;
}

.bluecard-summary-loading,
.bluecard-summary-fallback {
  font-size: 13px;
  line-height: 1.6;
  color: @muted;
}

.bluecard-summary-md {
  font-size: 13px;
  line-height: 1.6;
  color: @text;
}

.bluecard-summary-metric {
  flex-shrink: 0;
  width: 160px;
  margin-left: 16px;
  padding: 4px 18px 4px 16px;
  border-left: 1px solid #f0f1f3;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.bluecard-summary-metric-title {
  font-size: 12px;
  color: @muted;
  margin-bottom: 6px;
}

.bluecard-summary-metric-value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.2;
  color: @blue;
  word-break: break-all;
}

.bluecard-summary-metric-label {
  margin-top: 6px;
  font-size: 12px;
  color: @muted;
  line-height: 1.4;
}

@media (max-width: 640px) {
  .bluecard-summary.has-metric {
    flex-direction: column;
    padding-right: 18px;
  }
  .bluecard-summary-metric {
    width: auto;
    margin-left: 0;
    margin-top: 12px;
    padding: 12px 0 0;
    border-left: none;
    border-top: 1px solid #f0f1f3;
  }
}
</style>
