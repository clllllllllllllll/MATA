import type { UploadType } from './app'

export type WarningSeverity = 'critical' | 'warning' | 'info'
export type WarningStatus = 'unresolved' | 'resolved' | 'dismissed'

export interface ReportingPeriodOption {
  id: string
  label: string
  startDate: string
  endDate: string
  status: 'open' | 'closed' | string
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
  status: WarningStatus
  uploadMetaId: string
  suggestedAction?: string
}
