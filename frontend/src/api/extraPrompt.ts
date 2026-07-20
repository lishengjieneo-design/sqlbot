import { request } from '@/utils/request'

export const extraPromptApi = {
  getList: (pageNum: any, pageSize: any, params: any) =>
    request.get(`/system/extra_prompt/page/${pageNum}/${pageSize}${params}`),
  upsert: (data: any) => request.put('/system/extra_prompt', data),
  delete: (params: any) => request.delete('/system/extra_prompt', { data: params }),
  getOne: (id: any) => request.get(`/system/extra_prompt/${id}`),
  enable: (id: any, enabled: any) => request.get(`/system/extra_prompt/${id}/enable/${enabled}`),
  getVersioning: (id: number | string) => request.get(`/system/extra_prompt/${id}/versioning`),
  listVersions: (id: number | string) => request.get(`/system/extra_prompt/${id}/versions`),
  saveDraft: (id: number | string, data: { prompt: string; change_note?: string }) =>
    request.put(`/system/extra_prompt/${id}/draft`, data),
  publishDraft: (id: number | string) => request.post(`/system/extra_prompt/${id}/publish`),
  publishVersion: (id: number | string, versionId: number | string) =>
    request.post(`/system/extra_prompt/${id}/versions/${versionId}/publish`),
}
