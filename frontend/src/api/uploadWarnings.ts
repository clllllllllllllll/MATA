import type { UploadType } from '../types/app'
import type {
  UploadWarning,
  UploadWarningActionResponse,
  UploadWarningIssueDetail,
  UploadWarningOccurrence,
  WarningSeverity,
  WarningSourceCellApplyRequest,
  WarningSourceCellApplyResponse,
  WarningSourceCellPreviewResponse,
  WarningSourceCellReplaceRequest,
  WarningSourceTrace,
} from '../types/upload'
import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { toDataRevalidationImpact } from './dataRevalidation'
import { httpClient, toApiRequestError } from './http'

export interface ListUploadWarningsParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel: AdminDemoLevel
  uploadType?: UploadType | 'all'
  severity?: WarningSeverity | 'all'
  status?: string
  uploadLogId?: string
  programmeCode?: string
  warningType?: string
  reportingPeriodId?: string
  mcr?: string
  monthLabel?: string
  search?: string
  limit?: number
  offset?: number
  mode?: 'active' | 'history'
}

interface AdminWarningRequestContext {
  adminId: string
  adminProgrammes: string[]
  adminLevel: AdminDemoLevel
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

const toRecordArray = (value: unknown): Record<string, unknown>[] => {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
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

const toSourceTrace = (value: unknown): WarningSourceTrace | null => {
  if (typeof value !== 'object' || value === null) {
    return null
  }
  const payload = value as Record<string, unknown>
  return {
    ...payload,
    reporting_period_id: optionalString(payload.reporting_period_id),
    programme_code: optionalString(payload.programme_code),
    resident_id: optionalString(payload.resident_id),
    mcr: optionalString(payload.mcr),
    resident_name: optionalString(payload.resident_name),
    month_label: optionalString(payload.month_label),
    sheet_name: optionalString(payload.sheet_name),
    row_number: optionalNumber(payload.row_number),
    cell_ref: optionalString(payload.cell_ref),
  }
}

const toUploadWarning = (value: Record<string, unknown>): UploadWarning => ({
  issueId: optionalString(value.issue_id),
  warningIssueId: optionalString(value.warning_issue_id),
  status: optionalString(value.status),
  warningId: String(value.warning_id ?? ''),
  uploadWarningId: optionalString(value.upload_warning_id),
  latestUploadWarningId: optionalString(value.latest_upload_warning_id),
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
  suggestedAction: optionalString(value.suggested_action),
  seenCount:
    typeof value.seen_count === 'number' && Number.isFinite(value.seen_count)
      ? value.seen_count
      : 1,
  firstSeenAt: String(value.first_seen_at ?? value.uploaded_at ?? ''),
  lastSeenAt: String(value.last_seen_at ?? value.uploaded_at ?? ''),
  uploadLogIds: toStringArray(value.upload_log_ids),
  firstSeenUploadLogId: optionalString(value.first_seen_upload_log_id),
  lastSeenUploadLogId: optionalString(value.last_seen_upload_log_id),
  latestSourceTrace: toSourceTrace(value.latest_source_trace),
  reappeared: value.reappeared === true,
})

const toUploadWarningOccurrence = (value: Record<string, unknown>): UploadWarningOccurrence => ({
  id: String(value.id ?? ''),
  issueId: String(value.issue_id ?? ''),
  uploadLogId: String(value.upload_log_id ?? ''),
  uploadType: optionalString(value.upload_type),
  uploadedAt: optionalString(value.uploaded_at),
  warningType: String(value.warning_type ?? 'warning'),
  severity: toWarningSeverity(value.severity),
  reportingPeriodId: optionalString(value.reporting_period_id),
  programmeCode: optionalString(value.programme_code),
  residentId: optionalString(value.resident_id),
  mcr: optionalString(value.mcr),
  residentName: optionalString(value.resident_name),
  monthLabel: optionalString(value.month_label),
  sheetName: optionalString(value.sheet_name),
  rowNumber: optionalNumber(value.row_number),
  cellRef: optionalString(value.cell_ref),
  sourceTrace: toSourceTrace(value.source_trace),
  sourcePayload: value.source_payload,
  message: String(value.message ?? ''),
  suggestedAction: optionalString(value.suggested_action),
  fingerprint: String(value.fingerprint ?? ''),
  createdAt: String(value.created_at ?? ''),
})

const toUploadWarningIssueDetail = (value: Record<string, unknown>): UploadWarningIssueDetail => ({
  issueId: String(value.issue_id ?? value.warning_issue_id ?? ''),
  warningIssueId: String(value.warning_issue_id ?? value.issue_id ?? ''),
  fingerprint: String(value.fingerprint ?? ''),
  warningType: String(value.warning_type ?? 'warning'),
  severity: toWarningSeverity(value.severity),
  status: String(value.status ?? 'unresolved'),
  reappeared: value.reappeared === true,
  firstSeenUploadLogId: optionalString(value.first_seen_upload_log_id),
  lastSeenUploadLogId: optionalString(value.last_seen_upload_log_id),
  firstSeenAt: String(value.first_seen_at ?? ''),
  lastSeenAt: String(value.last_seen_at ?? ''),
  latestUploadWarningId: optionalString(value.latest_upload_warning_id),
  latestSourceTrace: toSourceTrace(value.latest_source_trace),
  latestSourcePayload: value.latest_source_payload,
  message: optionalString(value.message),
  suggestedAction: optionalString(value.suggested_action),
  residentName: optionalString(value.resident_name),
  reportingPeriodId: optionalString(value.reporting_period_id),
  programmeCode: optionalString(value.programme_code),
  residentId: optionalString(value.resident_id),
  mcr: optionalString(value.mcr),
  monthLabel: optionalString(value.month_label),
  resolutionNote: optionalString(value.resolution_note),
  resolutionSourceType: optionalString(value.resolution_source_type),
  resolutionSourceId: optionalString(value.resolution_source_id),
  resolvedBy: optionalString(value.resolved_by),
  resolvedAt: optionalString(value.resolved_at),
  createdAt: optionalString(value.created_at),
  updatedAt: optionalString(value.updated_at),
  occurrences: toRecordArray(value.occurrences).map(toUploadWarningOccurrence),
})

const toActionResponse = (value: Record<string, unknown>): UploadWarningActionResponse => ({
  issueId: String(value.issue_id ?? ''),
  status: String(value.status ?? value.new_status ?? ''),
  previousStatus: String(value.previous_status ?? ''),
  newStatus: String(value.new_status ?? value.status ?? ''),
  resolutionNote: optionalString(value.resolution_note),
  note: optionalString(value.note),
  resolvedBy: optionalString(value.resolved_by),
  actorUserId: optionalString(value.actor_user_id),
  resolvedAt: optionalString(value.resolved_at),
  updatedAt: optionalString(value.updated_at),
})

const toSourceCellPreview = (
  value: Record<string, unknown>,
): WarningSourceCellPreviewResponse => ({
  warningIssueId: String(value.warning_issue_id ?? ''),
  uploadWarningId: optionalString(value.upload_warning_id),
  latestUploadWarningId: optionalString(value.latest_upload_warning_id),
  fingerprint: String(value.fingerprint ?? ''),
  sourceTrace: toSourceTrace(value.source_trace) ?? {},
  sourcePayload: value.source_payload,
  originalWarningType: String(value.original_warning_type ?? ''),
  originalWarningStatus: String(value.original_warning_status ?? ''),
  replacementRawCellValue: value.replacement_raw_cell_value,
  normalizedCellValue: String(value.normalized_cell_value ?? ''),
  parsedCandidateRows: toRecordArray(value.parsed_candidate_rows),
  parserWarnings: Array.isArray(value.parser_warnings) ? value.parser_warnings : [],
  parserErrors: Array.isArray(value.parser_errors) ? value.parser_errors : [],
  applyAllowed: value.apply_allowed === true,
  dataRevalidation: toDataRevalidationImpact(value.data_revalidation),
  suggestedNextAction: String(value.suggested_next_action ?? ''),
  nextActions: toStringArray(value.next_actions),
})

const toSourceCellApply = (
  value: Record<string, unknown>,
): WarningSourceCellApplyResponse => ({
  warningIssueId: String(value.warning_issue_id ?? ''),
  uploadWarningId: optionalString(value.upload_warning_id),
  latestUploadWarningId: optionalString(value.latest_upload_warning_id),
  fingerprint: String(value.fingerprint ?? ''),
  sourceTrace: toSourceTrace(value.source_trace) ?? {},
  sourcePayload: value.source_payload,
  originalWarningType: String(value.original_warning_type ?? ''),
  warningIssueStatus: String(value.warning_issue_status ?? ''),
  replacementRawCellValue: value.replacement_raw_cell_value,
  normalizedCellValue: String(value.normalized_cell_value ?? ''),
  beforeRows: toRecordArray(value.before_rows),
  afterRows: toRecordArray(value.after_rows),
  replacementSummary: typeof value.replacement_summary === 'object' && value.replacement_summary !== null
    ? Object.fromEntries(
      Object.entries(value.replacement_summary as Record<string, unknown>)
        .map(([key, entry]) => [key, typeof entry === 'number' && Number.isFinite(entry) ? entry : 0]),
    )
    : {},
  parserWarnings: Array.isArray(value.parser_warnings) ? value.parser_warnings : [],
  parserErrors: Array.isArray(value.parser_errors) ? value.parser_errors : [],
  auditLogId: String(value.audit_log_id ?? ''),
  entityType: String(value.entity_type ?? ''),
  entityId: optionalString(value.entity_id),
  updatedFields: toStringArray(value.updated_fields),
  dataRevalidation: toDataRevalidationImpact(value.data_revalidation),
  suggestedNextAction: String(value.suggested_next_action ?? ''),
  nextActions: toStringArray(value.next_actions),
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
  if (params.status) {
    queryParams.status = params.status
  }
  if (params.uploadLogId) {
    queryParams.upload_log_id = params.uploadLogId
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
  if (params.mcr) {
    queryParams.mcr = params.mcr
  }
  if (params.monthLabel) {
    queryParams.month_label = params.monthLabel
  }
  if (params.search?.trim()) {
    queryParams.search = params.search.trim()
  }
  if (params.limit) {
    queryParams.limit = String(params.limit)
  }
  if (params.offset) {
    queryParams.offset = String(params.offset)
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

export const getUploadWarningIssue = async (
  params: AdminWarningRequestContext & { warningIssueId: string },
): Promise<UploadWarningIssueDetail> => {
  try {
    const response = await httpClient.get(
      `/admin/upload-warnings/${encodeURIComponent(params.warningIssueId)}`,
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
      },
    )
    return toUploadWarningIssueDetail(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateUploadWarningIssueStatus = async (
  params: AdminWarningRequestContext & {
    warningIssueId: string
    action: 'resolve' | 'dismiss' | 'supersede'
    note?: string
  },
): Promise<UploadWarningActionResponse> => {
  try {
    const response = await httpClient.post(
      `/admin/upload-warnings/${encodeURIComponent(params.warningIssueId)}/${params.action}`,
      { note: params.note?.trim() || null },
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
      },
    )
    return toActionResponse(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const previewWarningSourceCellReplacement = async (
  params: AdminWarningRequestContext & {
    warningIssueId: string
    request: WarningSourceCellReplaceRequest
  },
): Promise<WarningSourceCellPreviewResponse> => {
  try {
    const response = await httpClient.post(
      `/admin/upload-warnings/${encodeURIComponent(params.warningIssueId)}/source-cell-replace/preview`,
      params.request,
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
        skipMemoryCacheClear: true,
      },
    )
    return toSourceCellPreview(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const applyWarningSourceCellReplacement = async (
  params: AdminWarningRequestContext & {
    warningIssueId: string
    request: WarningSourceCellApplyRequest
  },
): Promise<WarningSourceCellApplyResponse> => {
  try {
    const response = await httpClient.post(
      `/admin/upload-warnings/${encodeURIComponent(params.warningIssueId)}/source-cell-replace/apply`,
      params.request,
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
      },
    )
    return toSourceCellApply(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
