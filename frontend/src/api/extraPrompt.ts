import { request } from '@/utils/request'

export const extraPromptApi = {
  getList: (pageNum: any, pageSize: any, params: any) =>
    request.get(`/system/extra_prompt/page/${pageNum}/${pageSize}${params}`),
  upsert: (data: any) => request.put('/system/extra_prompt', data),
  delete: (params: any) => request.delete('/system/extra_prompt', { data: params }),
  getOne: (id: any) => request.get(`/system/extra_prompt/${id}`),
  enable: (id: any, enabled: any) => request.get(`/system/extra_prompt/${id}/enable/${enabled}`),
}

