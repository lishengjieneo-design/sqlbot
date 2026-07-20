import { request } from '@/utils/request'

export const professionalApi = {
  getList: (pageNum: any, pageSize: any, params: any) =>
    request.get(`/system/terminology/page/${pageNum}/${pageSize}${params}`),
  updateEmbedded: (data: any) => request.put('/system/terminology', data),
  deleteEmbedded: (params: any) => request.delete('/system/terminology', { data: params }),
  getOne: (id: any) => request.get(`/system/terminology/${id}`),
  enable: (id: any, enabled: any) => request.get(`/system/terminology/${id}/enable/${enabled}`),
  export2Excel: (params: any) =>
    request.get(`/system/terminology/export`, {
      params,
      responseType: 'blob',
      requestOptions: { customError: true },
    }),
  listMetricKindOptions: () => request.get('/system/terminology/metric-kinds/options'),
  listMetricKinds: () => request.get('/system/terminology/metric-kinds'),
  saveMetricKind: (data: any) => request.put('/system/terminology/metric-kinds', data),
  deleteMetricKinds: (ids: number[]) =>
    request.delete('/system/terminology/metric-kinds', { data: ids }),
}
