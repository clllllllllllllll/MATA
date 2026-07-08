import { uploadLabels } from '../config/frontendConfig'
import type { UploadType } from '../types/app'
import type { NormalizedWarning, UploadMeta, WarningSeverity } from '../types/upload'

export const UNKNOWN_WARNING_MESSAGE =
  'This upload produced a warning that could not be summarized. Review the workbook row and try again.'

const normalizeToken = (value: string | undefined): string =>
  (value ?? '').trim().toLowerCase()

const normalizePostingCodes = (codes: string[] | undefined): string =>
  (codes ?? []).map((item) => item.trim().toLowerCase()).sort().join(',')

export const makeUploadScopeKey = (params: {
  uploadType: UploadType
  reportingPeriodId?: string
  programmeCode?: string
}): string => {
  if (params.uploadType === 'public_holidays') {
    return 'public_holidays'
  }
  if (params.uploadType === 'ttf') {
    return `ttf|${normalizeToken(params.reportingPeriodId)}|${normalizeToken(params.programmeCode)}`
  }
  return `${params.uploadType}|${normalizeToken(params.reportingPeriodId)}`
}

export const makeWarningDedupeKey = (warning: {
  uploadType: UploadType
  reportingPeriodId?: string
  programmeCode?: string
  type: string
  mcr?: string
  residentName?: string
  monthLabel?: string
  sheetName?: string
  rowNumber?: number
  cellRef?: string
  postingCodes?: string[]
  message: string
}): string => {
  const scopeKey = makeUploadScopeKey({
    uploadType: warning.uploadType,
    reportingPeriodId: warning.reportingPeriodId,
    programmeCode: warning.programmeCode,
  })
  return [
    scopeKey,
    normalizeToken(warning.type),
    normalizeToken(warning.mcr),
    normalizeToken(warning.residentName),
    normalizeToken(warning.monthLabel),
    normalizeToken(warning.sheetName),
    String(warning.rowNumber ?? ''),
    normalizeToken(warning.cellRef),
    normalizePostingCodes(warning.postingCodes),
    normalizeToken(warning.message),
  ].join('|')
}

const toStringValue = (value: unknown): string | undefined => {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed.length > 0 ? trimmed : undefined
  }
  if (typeof value === 'number') {
    return String(value)
  }
  return undefined
}

const severityFromWarningType = (warningType: string): WarningSeverity => {
  if (warningType.includes('error') || warningType.includes('duplicate')) {
    return 'critical'
  }
  if (
    warningType.includes('unmatched') ||
    warningType.includes('unknown') ||
    warningType.includes('orphaned') ||
    warningType.includes('skipped') ||
    warningType.includes('promotion')
  ) {
    return 'warning'
  }
  return 'info'
}

const toRowNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && Number.isFinite(Number(value))) {
    return Number(value)
  }
  return undefined
}

const toPostingCodes = (value: unknown): string[] | undefined => {
  if (!Array.isArray(value)) {
    return undefined
  }
  const parsed = value.map(toStringValue).filter((item): item is string => Boolean(item))
  return parsed.length > 0 ? parsed : undefined
}

const objectWarningToItem = (
  warning: Record<string, unknown>,
  fallbackType: string,
  uploadMeta: UploadMeta,
): NormalizedWarning => {
  const warningType = toStringValue(warning.type) ?? fallbackType
  const reportingPeriodId =
    toStringValue(warning.reporting_period_id) ??
    toStringValue(warning.reportingPeriodId) ??
    uploadMeta.reportingPeriodId
  const programmeCode =
    toStringValue(warning.programme_code) ??
    toStringValue(warning.programmeCode) ??
    uploadMeta.programmeCode
  const residentName = toStringValue(warning.resident_name) ?? toStringValue(warning.residentName)
  const monthLabel =
    toStringValue(warning.month_label) ??
    toStringValue(warning.month) ??
    toStringValue(warning.monthLabel)
  const rowNumber = toRowNumber(warning.row_number)
  const cellRef =
    toStringValue(warning.cell_ref) ??
    toStringValue(warning.cell) ??
    toStringValue(warning.cellRef)
  const postingCodes =
    toPostingCodes(warning.posting_codes) ??
    toPostingCodes(warning.postingCodes)
  const message =
    toStringValue(warning.message) ??
    toStringValue(warning.detail) ??
    toStringValue(warning.error) ??
    UNKNOWN_WARNING_MESSAGE
  const scopeKey = makeUploadScopeKey({
    uploadType: uploadMeta.uploadType,
    reportingPeriodId,
    programmeCode,
  })
  const id = makeWarningDedupeKey({
    uploadType: uploadMeta.uploadType,
    reportingPeriodId,
    programmeCode,
    type: warningType,
    mcr: toStringValue(warning.mcr),
    residentName,
    monthLabel,
    sheetName: toStringValue(warning.sheet_name),
    rowNumber,
    cellRef,
    postingCodes,
    message,
  })

  return {
    id,
    scopeKey,
    uploadType: uploadMeta.uploadType,
    uploadLabel: uploadMeta.uploadLabel,
    severity: severityFromWarningType(warningType.toLowerCase()),
    type: warningType,
    message,
    filename: uploadMeta.filename,
    reportingPeriodId,
    reportingPeriodLabel:
      toStringValue(warning.reporting_period_label) ??
      toStringValue(warning.reportingPeriodLabel) ??
      uploadMeta.reportingPeriodLabel,
    residentName,
    mcr: toStringValue(warning.mcr),
    programmeCode,
    monthLabel,
    sheetName: toStringValue(warning.sheet_name),
    rowNumber,
    cellRef,
    source: toStringValue(warning.source),
    postingCodes,
    raw: warning,
    uploadMetaId: uploadMeta.id,
    suggestedAction:
      warningType === 'unmatched_multi_posting'
        ? 'Review or add a rule in Multi-Posting Rules, then re-upload the RDB if needed.'
        : undefined,
  }
}

const scalarWarningToItem = (
  warning: string,
  warningType: string,
  uploadMeta: UploadMeta,
): NormalizedWarning => ({
  id: makeWarningDedupeKey({
    uploadType: uploadMeta.uploadType,
    reportingPeriodId: uploadMeta.reportingPeriodId,
    programmeCode: uploadMeta.programmeCode,
    type: warningType,
    message: warning,
  }),
  scopeKey: makeUploadScopeKey({
    uploadType: uploadMeta.uploadType,
    reportingPeriodId: uploadMeta.reportingPeriodId,
    programmeCode: uploadMeta.programmeCode,
  }),
  uploadType: uploadMeta.uploadType,
  uploadLabel: uploadMeta.uploadLabel,
  severity: severityFromWarningType(warningType.toLowerCase()),
  type: warningType,
  message: warning,
  filename: uploadMeta.filename,
  reportingPeriodId: uploadMeta.reportingPeriodId,
  reportingPeriodLabel: uploadMeta.reportingPeriodLabel,
  programmeCode: uploadMeta.programmeCode,
  raw: warning,
  uploadMetaId: uploadMeta.id,
  suggestedAction:
    warningType === 'unmatched_multi_posting'
      ? 'Review or add a rule in Multi-Posting Rules, then re-upload the RDB if needed.'
      : undefined,
})

const warningBuckets: Array<{ key: string; warningType: string }> = [
  { key: 'warnings', warningType: 'warning' },
  { key: 'unknown_loa_types', warningType: 'unknown_loa_types' },
  { key: 'unknown_loa_type', warningType: 'unknown_loa_type' },
  { key: 'mcr_not_found_warnings', warningType: 'mcr_not_found' },
  { key: 'skipped_mcr_warnings', warningType: 'skipped_mcr' },
  { key: 'duplicate_mcr_errors', warningType: 'duplicate_mcr_error' },
  { key: 'promotion_date_warnings', warningType: 'promotion_date_warning' },
  { key: 'orphaned_attendance', warningType: 'orphaned_attendance' },
  { key: 'unmatched_multi_posting', warningType: 'unmatched_multi_posting' },
  { key: 'errors', warningType: 'error' },
]

export const normalizeWarningsFromUploadResponse = (
  uploadMeta: UploadMeta,
): NormalizedWarning[] => {
  const output: NormalizedWarning[] = []

  warningBuckets.forEach((bucket) => {
    const value = uploadMeta.response[bucket.key]
    if (!Array.isArray(value)) {
      return
    }

    value.forEach((entry) => {
      if (typeof entry === 'string') {
        output.push(scalarWarningToItem(entry, bucket.warningType, uploadMeta))
        return
      }
      if (typeof entry === 'object' && entry !== null) {
        output.push(
          objectWarningToItem(
            entry as Record<string, unknown>,
            bucket.warningType,
            uploadMeta,
          ),
        )
      }
    })
  })

  return output
}

const countFromArrayKey = (response: Record<string, unknown>, key: string): number =>
  Array.isArray(response[key]) ? (response[key] as unknown[]).length : 0

const countFromNumericKey = (response: Record<string, unknown>, key: string): number => {
  const value = response[key]
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : 0
}

export const getWarningsCount = (response: Record<string, unknown>): number =>
  countFromNumericKey(response, 'warning_count') +
  countFromNumericKey(response, 'warnings_count') +
  countFromArrayKey(response, 'warnings') +
  countFromArrayKey(response, 'unknown_loa_types') +
  countFromArrayKey(response, 'unknown_loa_type') +
  countFromArrayKey(response, 'mcr_not_found_warnings') +
  countFromArrayKey(response, 'skipped_mcr_warnings') +
  countFromArrayKey(response, 'duplicate_mcr_errors') +
  countFromArrayKey(response, 'promotion_date_warnings') +
  countFromArrayKey(response, 'orphaned_attendance') +
  countFromArrayKey(response, 'unmatched_multi_posting') +
  countFromArrayKey(response, 'errors')

export const getErrorsCount = (response: Record<string, unknown>): number =>
  countFromNumericKey(response, 'error_count') +
  countFromNumericKey(response, 'errors_count') +
  countFromArrayKey(response, 'errors') +
  countFromArrayKey(response, 'duplicate_mcr_errors')

const sumNumericByKeys = (
  response: Record<string, unknown>,
  keys: string[],
): number | undefined => {
  let sum = 0
  let hasNumber = false
  keys.forEach((key) => {
    const value = response[key]
    if (typeof value === 'number' && Number.isFinite(value)) {
      sum += value
      hasNumber = true
    }
  })
  return hasNumber ? sum : undefined
}

export const getSummaryCounts = (response: Record<string, unknown>) => {
  const created = sumNumericByKeys(response, [
    'residents_created',
    'postings_created',
    'targets_created',
    'records_created',
    'public_holidays_created',
    'academic_month_boundaries_created',
    'catalogue_rows_seeded',
  ])

  const updated = sumNumericByKeys(response, [
    'residents_updated',
    'records_updated',
    'session_types_upserted',
  ])

  return { created, updated, warnings: getWarningsCount(response) }
}

const compactResponseKeys = [
  'residents_created',
  'residents_updated',
  'postings_created',
  'posting_codes_added_count',
  'loa_records',
  'unknown_loa_types_count',
  'employed_residents_flagged',
  'multi_posting_rules_applied',
  'raw_multi_posting_fragment_count',
  'raw_multi_posting_fragments_truncated',
  'rows_skipped',
  'targets_created',
  'session_types_upserted',
  'posting_codes_added',
  'catalogue_rows_seeded',
  'rows_exploded',
  'records_created',
  'records_updated',
  'active_count',
  'inactive_count',
  'public_holidays_created',
  'academic_month_boundaries_created',
  'academic_year_label',
  'upload_type',
  'status',
] as const

const arrayCountKeys = [
  'warnings',
  'errors',
  'unknown_loa_types',
  'unknown_loa_type',
  'mcr_not_found_warnings',
  'skipped_mcr_warnings',
  'duplicate_mcr_errors',
  'promotion_date_warnings',
  'orphaned_attendance',
  'unmatched_multi_posting',
] as const

export const compactUploadResponseForHistory = (
  response: Record<string, unknown>,
): Record<string, unknown> => {
  const compact: Record<string, unknown> = {}

  compactResponseKeys.forEach((key) => {
    const value = response[key]
    if (
      typeof value === 'number' ||
      typeof value === 'boolean' ||
      (typeof value === 'string' && value.trim().length > 0)
    ) {
      compact[key] = value
    }
  })

  arrayCountKeys.forEach((key) => {
    const value = response[key]
    if (Array.isArray(value)) {
      compact[`${key}_count`] = value.length
    }
  })

  compact.warning_count = getWarningsCount(response)
  compact.error_count = getErrorsCount(response)

  return compact
}

export const makeUploadMeta = (params: {
  uploadType: UploadType
  response: Record<string, unknown>
  filename?: string
  reportingPeriodId?: string
  reportingPeriodLabel?: string
  programmeCode?: string
}): UploadMeta => {
  const uploadedAtIso = new Date().toISOString()
  const id = `${params.uploadType}-${uploadedAtIso}-${Math.random().toString(16).slice(2, 8)}`
  const errorsCount = getErrorsCount(params.response)

  return {
    id,
    uploadType: params.uploadType,
    uploadLabel: uploadLabels[params.uploadType],
    uploadedAtIso,
    filename: params.filename,
    reportingPeriodId: params.reportingPeriodId,
    reportingPeriodLabel: params.reportingPeriodLabel,
    programmeCode: params.programmeCode,
    status: errorsCount > 0 ? 'partial' : 'success',
    response: compactUploadResponseForHistory(params.response),
    warningsCount: getWarningsCount(params.response),
    errorsCount,
  }
}
