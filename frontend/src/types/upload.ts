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
  status: UploadLogStatus
  response: Record<string, unknown>
  warningsCount: number
  errorsCount: number
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

export type RawMultiPostingDecision =
  | 'collapsed_into_main'
  | 'persisted_independent'
  | 'combined'
  | 'half_month'
  | 'unmatched_warning'
  | 'excluded'
  | string

export interface RawMultiPostingFragment {
  id: string
  mcr: string | null
  resident_name: string | null
  programme_code: string | null
  r_year: string | null
  sheet_name: string | null
  row_number: number | null
  cell_ref: string | null
  month_label: string | null
  source_column_header: string | null
  source_cell_text: string | null
  fragment_index: number
  raw_posting_code: string | null
  normalized_posting_code: string | null
  fragment_start_date: string | null
  fragment_end_date: string | null
  day_part: string | null
  decision: RawMultiPostingDecision | null
  effective_posting_code: string | null
  rule_type: string | null
  rule_id: string | null
  warning_id: string | null
}
