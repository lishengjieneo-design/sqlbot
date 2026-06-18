<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatInfo } from '@/api/chat'

const props = defineProps<{
  currentChat?: ChatInfo
}>()

const emit = defineEmits<{
  pick: [question: string]
}>()

const { t } = useI18n()

const recentQuestions = computed(() => {
  const records = props.currentChat?.records || []
  const seen = new Set<string>()
  const result: string[] = []
  for (let i = records.length - 1; i >= 0 && result.length < 3; i--) {
    const q = records[i]?.question?.trim()
    if (!q || records[i]?.first_chat) continue
    if (seen.has(q)) continue
    seen.add(q)
    result.push(q)
  }
  return result
})
</script>

<template>
  <div v-if="recentQuestions.length" class="recent-questions-bar">
    <span class="label">{{ t('qa.recent_questions') }}</span>
    <el-tag
      v-for="(q, idx) in recentQuestions"
      :key="idx"
      class="question-tag"
      effect="plain"
      :title="q"
      @click="emit('pick', q)"
    >
      {{ q.length > 40 ? q.slice(0, 40) + '…' : q }}
    </el-tag>
  </div>
</template>

<style scoped lang="less">
.recent-questions-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  padding: 0 2px;
}
.label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
.question-tag {
  cursor: pointer;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
