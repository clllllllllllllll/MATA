import type { UploadType } from '../types/app'
import { buildAdminDemoHeaders } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface UploadLogEntry {
  id: string
  uploadType: string
  uploadedBy: string
  uploadedAtIso: string
  reportingPeriodId?: string
  programmeCode?: string
  status: string
  summary: Record<string, unknown>
}

export interface ListUploadLogsParams {
  adminId: string
  adminProgrammes: string[]
  uploadType?: UploadType
  programmeCode?: string
  reportingPeriodId?: string
  limit?: number
}

const optionalString = (value: unknown): string | undefined => {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || undefined
}

const toUploadLogEntry = (value: Record<string, unknown>): UploadLogEntry => ({
  id: String(value.id ?? ''),
  uploadType: String(value.upload_type ?? ''),
  uploadedBy: String(value.uploaded_by ?? ''),
  uploadedAtIso: String(value.uploaded_at ?? ''),
  reportingPeriodId: optionalString(value.reporting_period_id),
  programmeCode: optionalString(value.programme_code),
  status: String(value.status ?? ''),
  summary:
    typeof value.summary === 'object' && value.summary !== null && !Array.isArray(value.summary)
      ? (value.summary as Record<string, unknown>)
      : {},
})

export const listUploadLogs = async (
  params: ListUploadLogsParams,
): Promise<UploadLogEntry[]> => {
  const queryParams: Record<string, string | number> = {}
  if (params.uploadType) {
    queryParams.upload_type = params.uploadType
  }
  if (params.programmeCode) {
    queryParams.programme_code = params.programmeCode
  }
  if (params.reportingPeriodId) {
    queryParams.reporting_period_id = params.reportingPeriodId
  }
  if (params.limit) {
    queryParams.limit = params.limit
  }

  try {
    const response = await httpClient.get('/admin/upload-logs', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes),
      params: queryParams,
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toUploadLogEntry)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
