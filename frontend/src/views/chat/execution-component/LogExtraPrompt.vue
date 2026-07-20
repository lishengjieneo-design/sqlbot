<script setup lang="ts">
import BaseContent from './BaseContent.vue'
import { type ChatLogHistoryItem } from '@/api/chat.ts'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const props = withDefaults(
  defineProps<{
    item?: ChatLogHistoryItem
    error?: string
  }>(),
  {
    item: undefined,
    error: '',
  }
)

const { t } = useI18n()

const list = computed(() => {
  return (props.item?.message as Array<any>) ?? []
})
const title = computed(() => {
  return t('chat.find_extra_prompt_title', [list.value.length])
})

function isStructured(ele: any) {
  return ele && typeof ele === 'object' && !Array.isArray(ele) && ('prompt' in ele || 'name' in ele)
}

function escapeHtml(s: any) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function displayHtml(ele: any) {
  if (isStructured(ele)) {
    const name = escapeHtml(ele.name || '')
    const ver =
      ele.version_no != null
        ? ` v${escapeHtml(ele.version_no)}`
        : ele.version_id != null
          ? ` #${escapeHtml(ele.version_id)}`
          : ''
    const body = escapeHtml(ele.prompt || '').replace(/\n/g, '<br/>')
    return `<div><strong>${name}${ver}</strong></div><div style="margin-top:8px">${body}</div>`
  }
  return ele
}
</script>

<template>
  <BaseContent class="base-container">
    <template v-if="item?.error">
      {{ error }}
    </template>
    <template v-else>
      <div class="inner-title">{{ title }}</div>
      <div v-if="list.length > 0" style="margin-top: 8px" class="item-list">
        <div v-for="(ele, index) in list" :key="index" class="inner-item">
          <div v-dompurify-html="displayHtml(ele)" class="inner-item-description" />
        </div>
      </div>
    </template>
  </BaseContent>
</template>

<style scoped lang="less">
.inner-title {
  color: #646a73;
  font-size: 12px;
  line-height: 20px;
  font-weight: 500;
  vertical-align: middle;
  white-space: pre-wrap;
  word-break: break-all;
}
.item-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: stretch;
  flex-wrap: nowrap;
  .inner-item {
    border: 1px solid #dee0e3;
    display: flex;
    flex-direction: column;
    gap: 8px;
    border-radius: 12px;
    padding: 16px;
    background: #ffffff;

    .inner-item-description {
      color: #1f2329;
      font-weight: 400;
      line-height: 22px;
      font-size: 14px;
      vertical-align: middle;
      white-space: pre-wrap;
      word-break: break-all;
    }
  }
}
</style>
