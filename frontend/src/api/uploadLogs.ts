import type { UploadType } from '../types/app'
import type {
  UploadLogDetail,
  UploadLogListItem,
  UploadLogListResponse,
  UploadLogStatus,
} from '../types/upload'
import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface ListUploadLogsParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  uploadType?: UploadType | 'all'
  status?: UploadLogStatus | 'all'
  programmeCode?: string
  reportingPeriodId?: string
  search?: string
  limit?: number
  offset?: number
}

export interface GetUploadLogParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  uploadLogId: string
}

const optionalString = (value: unknown): string | null => {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || null
}

const numberRecord = (value: unknown): Record<string, number> => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return {}
  }
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, number] => {
      const [, count] = entry
      return typeof count === 'number' && Number.isFinite(count)
    }),
  )
}

const toUploadType = (value: unknown): UploadType => {
  if (value === 'rdb' || value === 'ttf' || value === 'form_f1' || value === 'public_holidays') {
    return value
  }
  return 'rdb'
}

const toUploadStatus = (value: unknown): UploadLogStatus => {
  if (value === 'partial' || value === 'failed') {
    return value
  }
  return 'success'
}

const finiteNumber = (value: unknown, fallback = 0): number => {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

const toUploadLogListItem = (value: Record<string, unknown>): UploadLogListItem => ({
  id: String(value.id ?? ''),
  upload_type: toUploadType(value.upload_type),
  uploaded_at: String(value.uploaded_at ?? ''),
  uploaded_by: optionalString(value.uploaded_by),
  uploaded_by_name: optionalString(value.uploaded_by_name),
  status: toUploadStatus(value.status),
  reporting_period_id: optionalString(value.reporting_period_id),
  reporting_period_label: optionalString(value.reporting_period_label),
  programme_code: optionalString(value.programme_code),
  warning_count: finiteNumber(value.warning_count),
  error_count: finiteNumber(value.error_count),
  summary_counts: numberRecord(value.summary_counts),
})

const toUploadLogDetail = (value: Record<string, unknown>): UploadLogDetail => ({
  ...toUploadLogListItem(value),
  summary: value.summary,
  original_filename: optionalString(value.original_filename),
})

const headersFor = (
  adminId: string,
  adminProgrammes: string[],
  adminLevel: AdminDemoLevel = 'master',
) => buildAdminDemoHeaders(adminId, adminProgrammes, adminLevel)

export const listUploadLogs = async (
  params: ListUploadLogsParams,
): Promise<UploadLogListResponse> => {
  const queryParams: Record<string, string | number> = {}
  if (params.uploadType && params.uploadType !== 'all') {
    queryParams.upload_type = params.uploadType
  }
  if (params.status && params.status !== 'all') {
    queryParams.status = params.status
  }
  if (params.programmeCode && params.programmeCode !== 'all') {
    queryParams.programme_code = params.programmeCode
  }
  if (params.reportingPeriodId) {
    queryParams.reporting_period_id = params.reportingPeriodId
  }
  if (params.search?.trim()) {
    queryParams.search = params.search.trim()
  }
  if (params.limit) {
    queryParams.limit = params.limit
  }
  if (params.offset) {
    queryParams.offset = params.offset
  }

  try {
    const response = await httpClient.get('/admin/upload-logs', {
      headers: headersFor(params.adminId, params.adminProgrammes, params.adminLevel),
      params: queryParams,
    })
    const payload = response.data as Record<string, unknown>
    const rows = Array.isArray(payload.items) ? payload.items : []
    return {
      items: rows
        .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
        .map(toUploadLogListItem),
      total: finiteNumber(payload.total),
      limit: finiteNumber(payload.limit, params.limit ?? 20),
      offset: finiteNumber(payload.offset, params.offset ?? 0),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const getUploadLog = async ({
  adminId,
  adminProgrammes,
  adminLevel = 'master',
  uploadLogId,
}: GetUploadLogParams): Promise<UploadLogDetail> => {
  try {
    const response = await httpClient.get(`/admin/upload-logs/${uploadLogId}`, {
      headers: headersFor(adminId, adminProgrammes, adminLevel),
    })
    const payload = response.data as Record<string, unknown>
    return toUploadLogDetail(payload)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
