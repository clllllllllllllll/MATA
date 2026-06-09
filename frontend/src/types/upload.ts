import type { UploadType } from './app'

export type WarningSeverity = 'critical' | 'warning' | 'info'
export type UploadLogStatus = 'success' | 'partial' | 'failed'

export interface ReportingPeriodOption {
  id: string
  label: string
  startDate: string
  endDate: string
  status: 'open' | 'closed' | string
  createdAt?: string
  updatedAt?: string
}

export interface UploadCardState {
  file: File | null
  status: 'idle' | 'selected' | 'uploading' | 'parsing' | 'success' | 'error'
  errorMessage: string | null
  response: Record<string, unknown> | null
}

export interface UploadMeta {
  id: string
  uploadType: UploadType
  uploadLabel: string
  uploadedAtIso: string
  filename?: string
  reportingPeriodId?: string
  reportingPeriodLabel?: string
  programmeCode?: string
  response: Record<string, unknown>
  warningsCount: number
}

export interface NormalizedWarning {
  id: string
  scopeKey: string
  uploadType: UploadType
  uploadLabel: string
  severity: WarningSeverity
  type: string
  message: string
  filename?: string
  reportingPeriodId?: string
  reportingPeriodLabel?: string
  residentName?: string
  mcr?: string
  programmeCode?: string
  monthLabel?: string
  sheetName?: string
  rowNumber?: number
  cellRef?: string
  postingCodes?: string[]
  source?: string
  raw: unknown
  uploadMetaId: string
  suggestedAction?: string
}

export interface UploadWarning {
  warningId: string
  dedupeKey: string
  uploadLogId: string
  uploadType: UploadType
  uploadedAt: string
  uploadedBy?: string | null
  reportingPeriodId?: string | null
  programmeCode?: string | null
  warningType: string
  severity: WarningSeverity
  message: string
  residentName?: string | null
  mcr?: string | null
  monthLabel?: string | null
  sheetName?: string | null
  rowNumber?: number | null
  cellRef?: string | null
  postingCodes: string[]
  sessionType?: string | null
  count?: number | null
  sourceLabel?: string | null
  rawPayload?: unknown
  seenCount: number
  firstSeenAt: string
  lastSeenAt: string
  uploadLogIds: string[]
}

export interface UploadLogListItem {
  id: string
  upload_type: UploadType
  uploaded_at: string
  uploaded_by?: string | null
  uploaded_by_name?: string | null
  status: UploadLogStatus
  reporting_period_id?: string | null
  reporting_period_label?: string | null
  programme_code?: string | null
  warning_count: number
  error_count: number
  summary_counts: Record<string, number>
}

export interface UploadLogListResponse {
  items: UploadLogListItem[]
  total: number
  limit: number
  offset: number
}

export interface UploadLogDetail extends UploadLogListItem {
  summary: unknown
  original_filename?: string | null
}
