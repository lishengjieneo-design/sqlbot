<script lang="ts" setup>
import { nextTick, onMounted, reactive, ref, unref } from 'vue'
import icon_add_outlined from '@/assets/svg/icon_add_outlined.svg'
import IconOpeEdit from '@/assets/svg/icon_edit_outlined.svg'
import IconOpeDelete from '@/assets/svg/icon_delete.svg'
import icon_searchOutline_outlined from '@/assets/svg/icon_search-outline_outlined.svg'
import EmptyBackground from '@/views/dashboard/common/EmptyBackground.vue'
import { useI18n } from 'vue-i18n'
import { cloneDeep } from 'lodash-es'
import { formatTimestamp } from '@/utils/date'
import { datasourceApi } from '@/api/datasource'
import { extraPromptApi } from '@/api/extraPrompt'

interface Form {
  id?: string | null
  description: string | null
  prompt: string | null
  datasource_id: number | null
  datasource_name?: string[]
  enabled: boolean
  type: string
}

const { t } = useI18n()
const keywords = ref('')
const oldKeywords = ref('')
const searchLoading = ref(false)
const dialogFormVisible = ref<boolean>(false)
const dialogTitle = ref('')
const updateLoading = ref(false)

const options = ref<any[]>([])
const fieldList = ref<any>([])
const pageInfo = reactive({
  currentPage: 1,
  pageSize: 10,
  total: 0,
})

const defaultForm: Form = {
  id: null,
  description: null,
  prompt: null,
  datasource_id: null,
  enabled: true,
  type: 'GENERATE_SQL',
}
const pageForm = ref<Form>(cloneDeep(defaultForm))
const termFormRef = ref()

onMounted(() => {
  datasourceApi.list().then((res) => {
    options.value = res || []
  })
  search()
})

const configParams = () => {
  const parts: string[] = []
  if (keywords.value) parts.push(`description=${encodeURIComponent(keywords.value)}`)
  if (parts.length) return `?${parts.join('&')}`
  return ''
}

const search = ($event: any = {}) => {
  if ($event?.isComposing) return
  searchLoading.value = true
  oldKeywords.value = keywords.value
  extraPromptApi
    .getList(pageInfo.currentPage, pageInfo.pageSize, configParams())
    .then((res: any) => {
      fieldList.value = res.data
      pageInfo.total = res.total_count
      nextTick(() => {})
    })
    .finally(() => {
      searchLoading.value = false
    })
}

const rules = {
  datasource_id: [
    {
      required: true,
      message: t('datasource.Please_select') + t('common.empty') + t('ds.title'),
    },
  ],
  prompt: [
    {
      required: true,
      message: t('extra_prompt.prompt_required'),
    },
  ],
}

const editHandler = (row: any) => {
  pageForm.value = cloneDeep(defaultForm)
  if (row) pageForm.value = cloneDeep(row)
  dialogTitle.value = row?.id ? t('extra_prompt.edit') : t('extra_prompt.create')
  dialogFormVisible.value = true
}

const onFormClose = () => {
  pageForm.value = cloneDeep(defaultForm)
  dialogFormVisible.value = false
}

const saveHandler = () => {
  termFormRef.value.validate((res: any) => {
    if (!res) return
    const obj = unref(pageForm)
    if (!obj.id) delete obj.id
    updateLoading.value = true
    extraPromptApi
      .upsert(obj)
      .then(() => {
        ElMessage({ type: 'success', message: t('common.save_success') })
        search()
        onFormClose()
      })
      .finally(() => {
        updateLoading.value = false
      })
  })
}

const deleteHandler = (row: any) => {
  ElMessageBox.confirm(t('extra_prompt.delete_confirm'), {
    confirmButtonType: 'danger',
    confirmButtonText: t('dashboard.delete'),
    cancelButtonText: t('common.cancel'),
    customClass: 'confirm-no_icon',
    autofocus: false,
  }).then(() => {
    extraPromptApi.delete([row.id]).then(() => {
      ElMessage({ type: 'success', message: t('dashboard.delete_success') })
      search()
    })
  })
}

const changeStatus = (id: any, val: any) => {
  extraPromptApi
    .enable(id, val + '')
    .then(() => {
      ElMessage({ message: t('common.save_success'), type: 'success' })
    })
    .finally(() => {
      search()
    })
}

const handleSizeChange = (val: number) => {
  pageInfo.currentPage = 1
  pageInfo.pageSize = val
  search()
}
const handleCurrentChange = (val: number) => {
  pageInfo.currentPage = val
  search()
}
</script>

<template>
  <div v-loading="searchLoading" class="extra-prompt">
    <div class="tool-left">
      <span class="page-title">{{ $t('extra_prompt.title') }}</span>
      <div class="tool-row">
        <el-input
          v-model="keywords"
          style="width: 240px; margin-right: 12px"
          :placeholder="$t('extra_prompt.search_placeholder')"
          clearable
          @keydown.enter.exact.prevent="search"
        >
          <template #prefix>
            <el-icon>
              <icon_searchOutline_outlined />
            </el-icon>
          </template>
        </el-input>
        <el-button class="no-margin" type="primary" @click="editHandler(null)">
          <template #icon>
            <icon_add_outlined />
          </template>
          {{ $t('extra_prompt.create') }}
        </el-button>
      </div>
    </div>

    <div v-if="!searchLoading" class="table-content">
      <div class="preview-or-schema">
        <el-table :data="fieldList" style="width: 100%">
          <el-table-column prop="description" :label="$t('extra_prompt.description')" min-width="240">
            <template #default="scope">
              <div class="field-comment_d">
                <span :title="scope.row.description" class="notes-in_table">{{
                  scope.row.description
                }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="prompt" :label="$t('extra_prompt.prompt')" min-width="320">
            <template #default="scope">
              <div class="field-comment_d">
                <span :title="scope.row.prompt" class="notes-in_table">{{ scope.row.prompt }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="$t('training.effective_data_sources')" width="220">
            <template #default="scope">
              <span>{{ scope.row.datasource_name || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="t('ds.status')" width="140">
            <template #default="scope">
              <div style="display: flex; align-items: center" @click.stop>
                <el-switch
                  v-model="scope.row.enabled"
                  size="small"
                  @change="(val: any) => changeStatus(scope.row.id, val)"
                />
              </div>
            </template>
          </el-table-column>
          <el-table-column
            prop="create_time"
            sortable
            :label="$t('dashboard.create_time')"
            width="200"
          >
            <template #default="scope">
              <span>{{ formatTimestamp(scope.row.create_time, 'YYYY-MM-DD HH:mm:ss') }}</span>
            </template>
          </el-table-column>
          <el-table-column fixed="right" width="90" :label="t('ds.actions')">
            <template #default="scope">
              <div class="field-comment">
                <el-tooltip :offset="14" effect="dark" :content="$t('datasource.edit')" placement="top">
                  <el-icon class="action-btn" size="16" @click.stop="editHandler(scope.row)">
                    <IconOpeEdit />
                  </el-icon>
                </el-tooltip>
                <el-tooltip :offset="14" effect="dark" :content="$t('dashboard.delete')" placement="top">
                  <el-icon class="action-btn" size="16" @click.stop="deleteHandler(scope.row)">
                    <IconOpeDelete />
                  </el-icon>
                </el-tooltip>
              </div>
            </template>
          </el-table-column>
          <template #empty>
            <EmptyBackground
              v-if="!oldKeywords && !fieldList.length"
              :description="$t('extra_prompt.empty')"
              img-type="noneWhite"
            />
            <EmptyBackground
              v-else-if="!!oldKeywords && !fieldList.length"
              :description="$t('datasource.relevant_content_found')"
              img-type="tree"
            />
          </template>
        </el-table>
      </div>
    </div>

    <div v-if="fieldList.length" class="pagination-container">
      <el-pagination
        v-model:current-page="pageInfo.currentPage"
        v-model:page-size="pageInfo.pageSize"
        :page-sizes="[10, 20, 30]"
        :background="true"
        layout="total, sizes, prev, pager, next, jumper"
        :total="pageInfo.total"
        @size-change="handleSizeChange"
        @current-change="handleCurrentChange"
      />
    </div>
  </div>

  <el-drawer
    v-model="dialogFormVisible"
    :title="dialogTitle"
    destroy-on-close
    size="600px"
    :before-close="onFormClose"
    modal-class="extra-prompt-add_drawer"
  >
    <el-form
      ref="termFormRef"
      :model="pageForm"
      label-position="top"
      :rules="rules"
      class="form-content_error"
      @submit.prevent
    >
      <el-form-item prop="description" :label="t('extra_prompt.description')">
        <el-input v-model="pageForm.description" clearable maxlength="255" />
      </el-form-item>

      <el-form-item prop="datasource_id" :label="t('training.effective_data_sources')">
        <el-select
          v-model="pageForm.datasource_id"
          filterable
          :placeholder="$t('datasource.Please_select') + $t('common.empty') + $t('ds.title')"
          style="width: 100%"
        >
          <el-option v-for="item in options" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
      </el-form-item>

      <el-form-item prop="prompt" :label="t('extra_prompt.prompt')">
        <el-input v-model="pageForm.prompt" type="textarea" :autosize="{ minRows: 4, maxRows: 12 }" />
      </el-form-item>
    </el-form>
    <template #footer>
      <div v-loading="updateLoading" class="dialog-footer">
        <el-button secondary @click="onFormClose">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" @click="saveHandler">{{ $t('common.save') }}</el-button>
      </div>
    </template>
  </el-drawer>
</template>

<style lang="less" scoped>
.no-margin {
  margin: 0;
}
.extra-prompt {
  height: 100%;
  position: relative;

  .tool-left {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;

    .page-title {
      font-weight: 500;
      font-size: 20px;
      line-height: 28px;
    }
    .tool-row {
      display: flex;
      align-items: center;
      flex-direction: row;
      gap: 8px;
    }
  }

  .pagination-container {
    display: flex;
    justify-content: end;
    align-items: center;
    margin-top: 16px;
  }

  .table-content {
    max-height: calc(100% - 104px);
    overflow-y: auto;

    .preview-or-schema {
      .field-comment_d {
        display: flex;
        align-items: center;
        min-height: 24px;
      }
      .notes-in_table {
        max-width: 100%;
        display: -webkit-box;
        max-height: 66px;
        -webkit-box-orient: vertical;
        -webkit-line-clamp: 3;
        overflow: hidden;
        text-overflow: ellipsis;
        word-break: break-word;
        white-space: pre-wrap;
      }
      .field-comment {
        height: 24px;
        .ed-icon + .ed-icon {
          margin-left: 12px;
        }
      }
    }
  }
}
</style>

