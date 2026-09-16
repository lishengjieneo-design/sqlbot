<script setup lang="ts">
import ChartComponent from '@/views/chat/component/ChartComponent.vue'
import type { ChatMessage } from '@/api/chat.ts'
import { computed, nextTick, ref } from 'vue'
import type { ChartTypes } from '@/views/chat/component/BaseChart.ts'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  id?: number | string
  chartType: ChartTypes
  message: ChatMessage
  data: Array<{ [key: string]: any }>
  loadingData?: boolean
  showLabel?: boolean
  /** BlueCard P3: line skin + white card chrome */
  bluecardSkin?: boolean
  /** In-card title (chart title preferred over question) */
  cardTitle?: string
}>()

const { t } = useI18n()

const chartObject = computed<{
  type: ChartTypes
  title: string
  axis: {
    x: { name: string; value: string }
    y: { name: string; value: string } | Array<{ name: string; value: string }>
    series: { name: string; value: string }
    'multi-quota': {
      name: string
      value: Array<string>
    }
  }
  columns: Array<{ name: string; value: string }>
}>(() => {
  if (props.message?.record?.chart) {
    return JSON.parse(props.message.record.chart)
  }
  return {}
})

const xAxis = computed(() => {
  const axis = chartObject.value?.axis
  if (axis?.x) {
    return [axis.x]
  }
  return []
})
const yAxis = computed(() => {
  const axis = chartObject.value?.axis
  if (!axis?.y) {
    return []
  }

  const y = axis.y
  const multiQuotaValues = axis['multi-quota']?.value || []
  const yArray = Array.isArray(y) ? [...y] : [{ ...y }]

  return yArray.map((item) => ({
    ...item,
    'multi-quota': multiQuotaValues.includes(item.value),
  }))
})
const series = computed(() => {
  const axis = chartObject.value?.axis
  if (axis?.series) {
    return [axis.series]
  }
  return []
})

const multiQuotaName = computed(() => {
  return chartObject.value?.axis?.['multi-quota']?.name
})

const unitLabel = computed(() => {
  const y = yAxis.value?.[0]
  if (!y?.name) return ''
  const name = String(y.name).trim()
  if (!name || name === y.value) return ''
  return name
})

const innerTitle = computed(
  () => props.cardTitle || chartObject.value?.title || ''
)

const chartRef = ref()

function onTypeChange() {
  nextTick(() => {
    chartRef.value?.destroyChart()
    chartRef.value?.renderChart()
  })
}
function getViewInfo() {
  return {
    chart: {
      columns: chartObject.value?.columns,
      type: props.chartType,
      xAxis: xAxis.value,
      yAxis: yAxis.value,
      series: series.value,
      title: chartObject.value.title,
    },
    data: { data: props.data },
  }
}
function getExcelData() {
  return chartRef.value?.getExcelData()
}

defineExpose({
  onTypeChange,
  getViewInfo,
  getExcelData,
})
</script>

<template>
  <div
    v-if="message.record?.chart"
    class="chart-base-container"
    :class="{ 'bluecard-chart': bluecardSkin }"
  >
    <div v-if="bluecardSkin && (innerTitle || unitLabel)" class="bluecard-chart-header">
      <div v-if="innerTitle" class="bluecard-chart-title" :title="innerTitle">
        {{ innerTitle }}
      </div>
      <div v-if="unitLabel" class="bluecard-chart-unit">
        {{ t('chat.bluecard.unit_prefix') }}{{ unitLabel }}
      </div>
    </div>
    <ChartComponent
      v-if="message.record.id && data?.length > 0"
      :id="id ?? 'default_chat_id'"
      ref="chartRef"
      :type="chartType"
      :columns="chartObject?.columns"
      :x="xAxis"
      :y="yAxis"
      :series="series"
      :data="data"
      :multi-quota-name="multiQuotaName"
      :show-label="showLabel"
      :bluecard-skin="bluecardSkin && chartType === 'line'"
    />
    <el-empty v-else :description="loadingData ? t('chat.loading_data') : t('chat.no_data')" />
  </div>
</template>

<style scoped lang="less">
.chart-base-container {
  height: 100%;
  width: 100%;
  border-radius: 12px;
  background: rgba(224, 224, 226, 0.29);
  &.bluecard-chart {
    background: #fff;
    border: 1px solid #e5e6eb;
    box-shadow: 0 4px 16px rgba(31, 35, 41, 0.06);
    padding: 12px 12px 8px;
    box-sizing: border-box;
  }
}

.bluecard-chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  padding: 0 4px;
}

.bluecard-chart-title {
  flex: 1;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bluecard-chart-unit {
  flex-shrink: 0;
  font-size: 12px;
  line-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  color: #3b82f6;
  background: rgba(59, 130, 246, 0.12);
}
</style>
