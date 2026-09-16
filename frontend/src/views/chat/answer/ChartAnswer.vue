<script setup lang="ts">
import BaseAnswer from './BaseAnswer.vue'
import { Chat, chatApi, ChatInfo, type ChatMessage, ChatRecord, questionApi } from '@/api/chat.ts'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import ChartBlock from '@/views/chat/chat-block/ChartBlock.vue'
import JSONBig from 'json-bigint'

const props = withDefaults(
  defineProps<{
    recordId?: number
    chatList?: Array<ChatInfo>
    currentChatId?: number
    currentChat?: ChatInfo
    message?: ChatMessage
    loading?: boolean
    reasoningName: 'sql_answer' | 'chart_answer' | Array<'sql_answer' | 'chart_answer'>
  }>(),
  {
    recordId: undefined,
    chatList: () => [],
    currentChatId: undefined,
    currentChat: () => new ChatInfo(),
    message: undefined,
    loading: false,
  }
)

const emits = defineEmits([
  'finish',
  'error',
  'stop',
  'scrollBottom',
  'update:loading',
  'update:chatList',
  'update:currentChat',
  'update:currentChatId',
])

const index = computed(() => {
  if (props.message?.index) {
    return props.message.index
  }
  if (props.message?.index === 0) {
    return 0
  }
  return -1
})

const _currentChatId = computed({
  get() {
    return props.currentChatId
  },
  set(v) {
    emits('update:currentChatId', v)
  },
})

const _currentChat = computed({
  get() {
    return props.currentChat
  },
  set(v) {
    emits('update:currentChat', v)
  },
})

const _chatList = computed({
  get() {
    return props.chatList
  },
  set(v) {
    emits('update:chatList', v)
  },
})

const _loading = computed({
  get() {
    return props.loading
  },
  set(v) {
    emits('update:loading', v)
  },
})

const stopFlag = ref(false)

function isPendingClarification(record: ChatRecord) {
  return (
    record?.clarification?.current &&
    !record?.clarification_resolved &&
    !record?.clarification_abandoned
  )
}

async function consumeStream(
  response: Response,
  currentRecord: ChatRecord,
  sql_answer_ref: { value: string },
  chart_answer_ref: { value: string }
) {
  const reader = response.body!.getReader()
  const decoder = new TextDecoder('utf-8')
  let tempResult = ''

  while (true) {
    if (stopFlag.value) {
      break
    }
    const { done, value } = await reader.read()
    if (done) {
      break
    }
    let chunk = decoder.decode(value, { stream: true })
    tempResult += chunk
    const split = tempResult.match(/data:.*}\n\n/g)
    if (split) {
      chunk = split.join('')
      tempResult = tempResult.replace(chunk, '')
    } else {
      continue
    }
    if (chunk && chunk.startsWith('data:{')) {
      for (const str of split) {
        let data
        try {
          data = JSONBig.parse(str.replace('data:{', '{'))
        } catch (err) {
          console.error('JSON string:', str)
          throw err
        }
        if (data.code && data.code !== 200) {
          ElMessage({ message: data.msg, type: 'error', showClose: true })
          return
        }
        switch (data.type) {
          case 'id':
            currentRecord.id = data.id
            _currentChat.value.records[index.value].id = data.id
            break
          case 'regenerate_record_id':
            currentRecord.regenerate_record_id = data.regenerate_record_id
            _currentChat.value.records[index.value].regenerate_record_id = data.regenerate_record_id
            break
          case 'question':
            currentRecord.question = data.question
            _currentChat.value.records[index.value].question = data.question
            break
          case 'info':
            console.info(data.msg)
            break
          case 'brief':
            _currentChat.value.brief = data.brief
            _chatList.value.forEach((c: Chat) => {
              if (c.id === _currentChat.value.id) {
                c.brief = _currentChat.value.brief
              }
            })
            break
          case 'error':
            currentRecord.error = data.content
            emits('error', currentRecord.id)
            break
          case 'clarification':
            _currentChat.value.records[index.value].clarification = data.content
            _currentChat.value.records[index.value].clarification_resolved = false
            _currentChat.value.records[index.value].clarification_abandoned = false
            break
          case 'clarification-resolved':
            _currentChat.value.records[index.value].clarification = data.content
            _currentChat.value.records[index.value].clarification_resolved = false
            _currentChat.value.records[index.value].clarification_abandoned = false
            break
          case 'clarification-pending':
            if (isPendingClarification(_currentChat.value.records[index.value])) {
              emits('finish', currentRecord.id)
              return
            }
            break
          case 'sql-result':
            sql_answer_ref.value += data.reasoning_content
            _currentChat.value.records[index.value].sql_answer = sql_answer_ref.value
            break
          case 'sql':
            _currentChat.value.records[index.value].sql = data.content
            break
          case 'sql-data':
            getChatData(_currentChat.value.records[index.value].id)
            break
          case 'field-aliases':
            if (Array.isArray(data.content)) {
              _currentChat.value.records[index.value].field_aliases = data.content
            }
            break
          case 'layout':
            // BlueCard P2: backend layout decision (optional FE consumption)
            if (data.layout) {
              ;(_currentChat.value.records[index.value] as any).layout = data.layout
            }
            break
          case 'summary-result':
            if (data.content) {
              const prev = _currentChat.value.records[index.value].summary || ''
              _currentChat.value.records[index.value].summary = prev + data.content
            }
            break
          case 'summary':
            if (data.content) {
              _currentChat.value.records[index.value].summary = data.content
            }
            break
          case 'chart-result':
            chart_answer_ref.value += data.reasoning_content
            _currentChat.value.records[index.value].chart_answer = chart_answer_ref.value
            break
          case 'chart':
            _currentChat.value.records[index.value].chart = data.content
            break
          case 'datasource':
            if (!_currentChat.value.datasource) {
              _currentChat.value.datasource = data.id
            }
            break
          case 'finish':
            if (isPendingClarification(_currentChat.value.records[index.value])) {
              return
            }
            _currentChat.value.records[index.value].clarification_resolved = true
            emits('finish', currentRecord.id)
            break
        }
        await nextTick()
      }
    }
  }
  const record = _currentChat.value.records[index.value]
  if (record && !isPendingClarification(record) && !record.finish) {
    emits('finish', currentRecord.id)
  }
}

const runStream = async (fetcher: (controller: AbortController) => Promise<Response>) => {
  stopFlag.value = false
  _loading.value = true
  if (index.value < 0 || _currentChatId.value === undefined) {
    _loading.value = false
    return
  }
  const currentRecord: ChatRecord = _currentChat.value.records[index.value]
  const sql_answer = { value: '' }
  const chart_answer = { value: '' }
  try {
    const controller = new AbortController()
    const response = await fetcher(controller)
    if (!response.ok) {
      const errText = await response.text().catch(() => response.statusText)
      throw new Error(errText || `HTTP ${response.status}`)
    }
    await consumeStream(response, currentRecord, sql_answer, chart_answer)
  } catch (error) {
    if (!currentRecord.error) {
      currentRecord.error = ''
    }
    if (currentRecord.error.trim().length !== 0) {
      currentRecord.error = currentRecord.error + '\n'
    }
    currentRecord.error = currentRecord.error + 'Error:' + error
    console.error('Error:', error)
    emits('error')
  } finally {
    _loading.value = false
  }
}

const sendMessage = async (opts?: { new_question?: boolean }) => {
  await runStream((controller) =>
    questionApi.add(
      {
        question: _currentChat.value.records[index.value].question,
        chat_id: _currentChatId.value,
        new_question: opts?.new_question,
      },
      controller
    )
  )
}

const clarifyMessage = async (payload: { selection?: { field: string; label: string }; free_text?: string }) => {
  const recordId = _currentChat.value.records[index.value]?.id
  if (!recordId) return
  await runStream((controller) => questionApi.clarify(recordId, payload, controller))
}

const loadingData = ref(false)

function getChatData(recordId?: number) {
  loadingData.value = true
  chatApi
    .get_chart_data(recordId)
    .then((response) => {
      _currentChat.value.records.forEach((record) => {
        if (record.id === recordId) {
          record.data = response
        }
      })
    })
    .finally(() => {
      loadingData.value = false
      emits('scrollBottom')
    })
}

function stop() {
  stopFlag.value = true
  _loading.value = false
  emits('stop')
}

onBeforeUnmount(() => {
  stop()
})

onMounted(() => {
  if (props.message?.record?.id && props.message?.record?.finish) {
    getChatData(props.message.record.id)
  }
})

defineExpose({ sendMessage, clarifyMessage, index: () => index.value, stop })
</script>

<template>
  <BaseAnswer v-if="message" :message="message" :reasoning-name="reasoningName" :loading="_loading">
    <ChartBlock
      style="margin-top: 6px"
      :message="message"
      :record-id="recordId"
      :loading-data="loadingData"
    />
    <slot></slot>
    <template #tool>
      <slot name="tool"></slot>
    </template>
    <template #footer>
      <slot name="footer"></slot>
    </template>
  </BaseAnswer>
</template>

<style scoped lang="less"></style>
