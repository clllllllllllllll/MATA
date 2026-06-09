import type { UploadType } from '../types/app'
import type { UploadWarning, WarningSeverity } from '../types/upload'
import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface ListUploadWarningsParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel: AdminDemoLevel
  uploadType?: UploadType | 'all'
  severity?: WarningSeverity | 'all'
  programmeCode?: string
  warningType?: string
  reportingPeriodId?: string
  search?: string
  mode?: 'active' | 'history'
}

const optionalString = (value: unknown): string | null => {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || null
}

const optionalNumber = (value: unknown): number | null => {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

const toPostingCodes = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : String(item ?? '').trim()))
    .filter(Boolean)
}

const toStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => String(item ?? '').trim()).filter(Boolean)
}

const toWarningSeverity = (value: unknown): WarningSeverity => {
  return value === 'critical' || value === 'info' ? value : 'warning'
}

const toUploadType = (value: unknown): UploadType => {
  if (value === 'rdb' || value === 'ttf' || value === 'form_f1' || value === 'public_holidays') {
    return value
  }
  return 'rdb'
}

const toUploadWarning = (value: Record<string, unknown>): UploadWarning => ({
  warningId: String(value.warning_id ?? ''),
  dedupeKey: String(value.dedupe_key ?? ''),
  uploadLogId: String(value.upload_log_id ?? ''),
  uploadType: toUploadType(value.upload_type),
  uploadedAt: String(value.uploaded_at ?? ''),
  uploadedBy: optionalString(value.uploaded_by),
  reportingPeriodId: optionalString(value.reporting_period_id),
  programmeCode: optionalString(value.programme_code),
  warningType: String(value.warning_type ?? 'warning'),
  severity: toWarningSeverity(value.severity),
  message: String(value.message ?? ''),
  residentName: optionalString(value.resident_name),
  mcr: optionalString(value.mcr),
  monthLabel: optionalString(value.month_label),
  sheetName: optionalString(value.sheet_name),
  rowNumber: optionalNumber(value.row_number),
  cellRef: optionalString(value.cell_ref),
  postingCodes: toPostingCodes(value.posting_codes),
  sessionType: optionalString(value.session_type),
  count: optionalNumber(value.count),
  sourceLabel: optionalString(value.source_label),
  rawPayload: value.raw_payload,
  seenCount:
    typeof value.seen_count === 'number' && Number.isFinite(value.seen_count)
      ? value.seen_count
      : 1,
  firstSeenAt: String(value.first_seen_at ?? value.uploaded_at ?? ''),
  lastSeenAt: String(value.last_seen_at ?? value.uploaded_at ?? ''),
  uploadLogIds: toStringArray(value.upload_log_ids),
})

export const listUploadWarnings = async (
  params: ListUploadWarningsParams,
): Promise<UploadWarning[]> => {
  const queryParams: Record<string, string> = {}
  if (params.uploadType && params.uploadType !== 'all') {
    queryParams.upload_type = params.uploadType
  }
  if (params.severity && params.severity !== 'all') {
    queryParams.severity = params.severity
  }
  if (params.programmeCode && params.programmeCode !== 'all') {
    queryParams.programme_code = params.programmeCode
  }
  if (params.warningType) {
    queryParams.warning_type = params.warningType
  }
  if (params.reportingPeriodId) {
    queryParams.reporting_period_id = params.reportingPeriodId
  }
  if (params.search?.trim()) {
    queryParams.search = params.search.trim()
  }
  if (params.mode) {
    queryParams.mode = params.mode
  }

  try {
    const response = await httpClient.get('/admin/upload-warnings', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
      params: queryParams,
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toUploadWarning)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
