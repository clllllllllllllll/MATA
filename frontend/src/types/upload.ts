import type { UploadType } from './app'

export type WarningSeverity = 'critical' | 'warning' | 'info' | 'resolved'

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
  reportingPeriodId?: string
  programmeCode?: string
  response: Record<string, unknown>
  warningsCount: number
}

export interface NormalizedWarning {
  id: string
  uploadType: UploadType
  uploadLabel: string
  severity: WarningSeverity
  warningType: string
  message: string
  residentName?: string
  mcr?: string
  programmeCode?: string
  monthLabel?: string
  sheetName?: string
  rowNumber?: number
  cellRef?: string
  source?: string
  raw: unknown
  status: 'unresolved' | 'resolved'
  uploadMetaId: string
}
