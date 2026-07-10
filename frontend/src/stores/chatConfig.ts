import { defineStore } from 'pinia'
import { store } from '@/stores/index.ts'
import { request } from '@/utils/request.ts'
import { formatArg } from '@/utils/utils.ts'

export interface DefaultDatasourceInfo {
  id: number
  name: string
  type: string
  type_name?: string
}

interface ChatConfig {
  expand_thinking_block: boolean
  limit_rows: boolean
  default_datasource: DefaultDatasourceInfo | null
}

export const chatConfigStore = defineStore('chatConfigStore', {
  state: (): ChatConfig => {
    return {
      expand_thinking_block: false,
      limit_rows: true,
      default_datasource: null,
    }
  },
  getters: {
    getExpandThinkingBlock(): boolean {
      return this.expand_thinking_block
    },
    getLimitRows(): boolean {
      return this.limit_rows
    },
    getDefaultDatasource(): DefaultDatasourceInfo | null {
      return this.default_datasource
    },
    getDefaultDatasourceId(): number | null {
      return this.default_datasource?.id ?? null
    },
  },
  actions: {
    fetchGlobalConfig() {
      request.get('/system/parameter/chat').then((res: any) => {
        if (res) {
          res.forEach((item: any) => {
            if (item.pkey === 'chat.expand_thinking_block') {
              this.expand_thinking_block = formatArg(item.pval)
            }
            if (item.pkey === 'chat.limit_rows') {
              this.limit_rows = formatArg(item.pval)
            }
          })
        }
      })
      request.get('/system/parameter/chat/default-datasource').then((res: any) => {
        this.default_datasource = res?.id ? res : null
      })
    },
  },
})

export const useChatConfigStore = () => {
  return chatConfigStore(store)
}
