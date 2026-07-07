import type { UploadType } from './app'
import type { DataRevalidationImpact } from './dataRevalidation'

export type WarningSeverity = 'critical' | 'warning' | 'info'
export type UploadLogStatus = 'success' | 'partial' | 'failed'

export interface ReportingPeriodOption {
  id: string
  label: string
  startDate: string
  endDate: string
  status: 'active' | 'inactive' | string
  createdAt?: string
  updatedAt?: string
  dataRevalidation?: DataRevalidationImpact | null
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
  issueId?: string | null
  warningIssueId?: string | null
  status?: string | null
  warningId: string
  uploadWarningId?: string | null
  latestUploadWarningId?: string | null
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
  suggestedAction?: string | null
  seenCount: number
  firstSeenAt: string
  lastSeenAt: string
  uploadLogIds: string[]
  firstSeenUploadLogId?: string | null
  lastSeenUploadLogId?: string | null
  latestSourceTrace?: WarningSourceTrace | null
  reappeared: boolean
}

export type WarningIssueStatus =
  | 'unresolved'
  | 'resolved'
  | 'dismissed'
  | 'superseded'
  | 'reappeared'
  | string

export interface WarningSourceTrace {
  reporting_period_id?: string | null
  programme_code?: string | null
  resident_id?: string | null
  mcr?: string | null
  resident_name?: string | null
  month_label?: string | null
  sheet_name?: string | null
  row_number?: number | null
  cell_ref?: string | null
  source_payload?: unknown
  [key: string]: unknown
}

export interface UploadWarningOccurrence {
  id: string
  issueId: string
  uploadLogId: string
  uploadType?: string | null
  uploadedAt?: string | null
  warningType: string
  severity: WarningSeverity
  reportingPeriodId?: string | null
  programmeCode?: string | null
  residentId?: string | null
  mcr?: string | null
  residentName?: string | null
  monthLabel?: string | null
  sheetName?: string | null
  rowNumber?: number | null
  cellRef?: string | null
  sourceTrace?: WarningSourceTrace | null
  sourcePayload?: unknown
  message: string
  suggestedAction?: string | null
  fingerprint: string
  createdAt: string
}

export interface UploadWarningIssueDetail {
  issueId: string
  warningIssueId: string
  fingerprint: string
  warningType: string
  severity: WarningSeverity
  status: WarningIssueStatus
  reappeared: boolean
  firstSeenUploadLogId?: string | null
  lastSeenUploadLogId?: string | null
  firstSeenAt: string
  lastSeenAt: string
  latestUploadWarningId?: string | null
  latestSourceTrace?: WarningSourceTrace | null
  latestSourcePayload?: unknown
  message?: string | null
  suggestedAction?: string | null
  residentName?: string | null
  reportingPeriodId?: string | null
  programmeCode?: string | null
  residentId?: string | null
  mcr?: string | null
  monthLabel?: string | null
  resolutionNote?: string | null
  resolutionSourceType?: string | null
  resolutionSourceId?: string | null
  resolvedBy?: string | null
  resolvedAt?: string | null
  createdAt?: string | null
  updatedAt?: string | null
  occurrences: UploadWarningOccurrence[]
}

export interface UploadWarningActionResponse {
  issueId: string
  status: WarningIssueStatus
  previousStatus: WarningIssueStatus
  newStatus: WarningIssueStatus
  resolutionNote?: string | null
  note?: string | null
  resolvedBy?: string | null
  actorUserId?: string | null
  resolvedAt?: string | null
  updatedAt?: string | null
}

export interface WarningSourceCellReplaceRequest {
  replacement_raw_cell_value: unknown
  upload_warning_id?: string | null
  expected_latest_upload_warning_id?: string | null
  expected_fingerprint?: string | null
}

export interface WarningSourceCellApplyRequest extends WarningSourceCellReplaceRequest {
  correction_reason: string
}

export interface WarningSourceCellPreviewResponse {
  warningIssueId: string
  uploadWarningId?: string | null
  latestUploadWarningId?: string | null
  fingerprint: string
  sourceTrace: WarningSourceTrace
  sourcePayload?: unknown
  originalWarningType: string
  originalWarningStatus: WarningIssueStatus
  replacementRawCellValue: unknown
  normalizedCellValue: string
  parsedCandidateRows: Record<string, unknown>[]
  parserWarnings: unknown[]
  parserErrors: unknown[]
  applyAllowed: boolean
  dataRevalidation?: DataRevalidationImpact | null
  suggestedNextAction: string
  nextActions: string[]
}

export interface WarningSourceCellApplyResponse {
  warningIssueId: string
  uploadWarningId?: string | null
  latestUploadWarningId?: string | null
  fingerprint: string
  sourceTrace: WarningSourceTrace
  sourcePayload?: unknown
  originalWarningType: string
  warningIssueStatus: WarningIssueStatus
  replacementRawCellValue: unknown
  normalizedCellValue: string
  beforeRows: Record<string, unknown>[]
  afterRows: Record<string, unknown>[]
  replacementSummary: Record<string, number>
  parserWarnings: unknown[]
  parserErrors: unknown[]
  auditLogId: string
  entityType: string
  entityId?: string | null
  updatedFields: string[]
  dataRevalidation?: DataRevalidationImpact | null
  suggestedNextAction: string
  nextActions: string[]
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
