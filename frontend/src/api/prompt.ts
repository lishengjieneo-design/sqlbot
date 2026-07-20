import { request } from '@/utils/request'

export const promptApi = {
  getList: (pageNum: any, pageSize: any, type: any, params: any) =>
    request.get(`/system/custom_prompt/${type}/page/${pageNum}/${pageSize}${params}`),
  updateEmbedded: (data: any) => request.put(`/system/custom_prompt`, data),
  deleteEmbedded: (params: any) => request.delete('/system/custom_prompt', { data: params }),
  getOne: (id: any) => request.get(`/system/custom_prompt/${id}`),
  export2Excel: (type: any, params: any) =>
    request.get(`/system/custom_prompt/${type}/export`, {
      params,
      responseType: 'blob',
      requestOptions: { customError: true },
    }),
  getVersioning: (id: number | string) => request.get(`/system/custom_prompt/${id}/versioning`),
  listVersions: (id: number | string) => request.get(`/system/custom_prompt/${id}/versions`),
  saveDraft: (id: number | string, data: { prompt: string; change_note?: string }) =>
    request.put(`/system/custom_prompt/${id}/draft`, data),
  publishDraft: (id: number | string) => request.post(`/system/custom_prompt/${id}/publish`),
  publishVersion: (id: number | string, versionId: number | string) =>
    request.post(`/system/custom_prompt/${id}/versions/${versionId}/publish`),
}
