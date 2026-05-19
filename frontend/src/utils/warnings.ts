import { uploadLabels } from '../config/frontendConfig'
import type { UploadType } from '../types/app'
import type { NormalizedWarning, UploadMeta, WarningSeverity } from '../types/upload'

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

const objectWarningToItem = (
  warning: Record<string, unknown>,
  fallbackType: string,
  uploadMeta: UploadMeta,
  index: number,
): NormalizedWarning => {
  const warningType = toStringValue(warning.type) ?? fallbackType
  const message =
    toStringValue(warning.message) ??
    toStringValue(warning.detail) ??
    toStringValue(warning.error) ??
    JSON.stringify(warning)

  return {
    id: `${uploadMeta.id}-${warningType}-${index}`,
    uploadType: uploadMeta.uploadType,
    uploadLabel: uploadMeta.uploadLabel,
    severity: severityFromWarningType(warningType.toLowerCase()),
    warningType,
    message,
    residentName: toStringValue(warning.resident_name) ?? toStringValue(warning.residentName),
    mcr: toStringValue(warning.mcr),
    programmeCode:
      toStringValue(warning.programme_code) ??
      toStringValue(warning.programmeCode) ??
      uploadMeta.programmeCode,
    monthLabel:
      toStringValue(warning.month_label) ??
      toStringValue(warning.month) ??
      toStringValue(warning.monthLabel),
    sheetName: toStringValue(warning.sheet_name),
    rowNumber:
      typeof warning.row_number === 'number'
        ? warning.row_number
        : Number.isFinite(Number(warning.row_number))
          ? Number(warning.row_number)
          : undefined,
    cellRef:
      toStringValue(warning.cell_ref) ??
      toStringValue(warning.cell) ??
      toStringValue(warning.cellRef),
    source: toStringValue(warning.source),
    raw: warning,
    status: 'unresolved',
    uploadMetaId: uploadMeta.id,
  }
}

const scalarWarningToItem = (
  warning: string,
  warningType: string,
  uploadMeta: UploadMeta,
  index: number,
): NormalizedWarning => ({
  id: `${uploadMeta.id}-${warningType}-${index}`,
  uploadType: uploadMeta.uploadType,
  uploadLabel: uploadMeta.uploadLabel,
  severity: severityFromWarningType(warningType.toLowerCase()),
  warningType,
  message: warning,
  programmeCode: uploadMeta.programmeCode,
  raw: warning,
  status: 'unresolved',
  uploadMetaId: uploadMeta.id,
})

const warningBuckets: Array<{ key: string; warningType: string }> = [
  { key: 'warnings', warningType: 'warning' },
  { key: 'unknown_loa_types', warningType: 'unknown_loa_types' },
  { key: 'unknown_loa_type', warningType: 'unknown_loa_type' },
  { key: 'mcr_not_found_warnings', warningType: 'mcr_not_found' },
  { key: 'skipped_mcr_warnings', warningType: 'skipped_mcr' },
  { key: 'duplicate_mcr_errors', warningType: 'duplicate_mcr_error' },
  { key: 'promotion_date_warnings', warningType: 'promotion_date_warning' },
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

    value.forEach((entry, index) => {
      if (typeof entry === 'string') {
        output.push(scalarWarningToItem(entry, bucket.warningType, uploadMeta, index))
        return
      }
      if (typeof entry === 'object' && entry !== null) {
        output.push(
          objectWarningToItem(
            entry as Record<string, unknown>,
            bucket.warningType,
            uploadMeta,
            index,
          ),
        )
      }
    })
  })

  return output
}

const countFromArrayKey = (response: Record<string, unknown>, key: string): number =>
  Array.isArray(response[key]) ? (response[key] as unknown[]).length : 0

export const getWarningsCount = (response: Record<string, unknown>): number =>
  countFromArrayKey(response, 'warnings') +
  countFromArrayKey(response, 'unknown_loa_types') +
  countFromArrayKey(response, 'unknown_loa_type') +
  countFromArrayKey(response, 'mcr_not_found_warnings') +
  countFromArrayKey(response, 'skipped_mcr_warnings') +
  countFromArrayKey(response, 'duplicate_mcr_errors') +
  countFromArrayKey(response, 'promotion_date_warnings') +
  countFromArrayKey(response, 'errors')

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

export const makeUploadMeta = (params: {
  uploadType: UploadType
  response: Record<string, unknown>
  reportingPeriodId?: string
  programmeCode?: string
}): UploadMeta => {
  const uploadedAtIso = new Date().toISOString()
  const id = `${params.uploadType}-${uploadedAtIso}-${Math.random().toString(16).slice(2, 8)}`

  return {
    id,
    uploadType: params.uploadType,
    uploadLabel: uploadLabels[params.uploadType],
    uploadedAtIso,
    reportingPeriodId: params.reportingPeriodId,
    programmeCode: params.programmeCode,
    response: params.response,
    warningsCount: getWarningsCount(params.response),
  }
}
