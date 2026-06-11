import type { UploadMeta } from '../types/upload'
import {
  compactUploadResponseForHistory,
  getErrorsCount,
  getWarningsCount,
} from './warnings'

const UPLOADS_KEY = 'mata.admin.uploads.v1'

const safeParse = <T>(value: string | null): T | null => {
  if (!value) {
    return null
  }
  try {
    return JSON.parse(value) as T
  } catch {
    return null
  }
}

const storage = () => {
  if (typeof window === 'undefined') {
    return null
  }
  return window.localStorage
}

const compactUploadMeta = (entry: UploadMeta): UploadMeta => {
  const response = compactUploadResponseForHistory(entry.response ?? {})
  return {
    id: entry.id,
    uploadType: entry.uploadType,
    uploadLabel: entry.uploadLabel,
    uploadedAtIso: entry.uploadedAtIso,
    filename: entry.filename,
    reportingPeriodId: entry.reportingPeriodId,
    reportingPeriodLabel: entry.reportingPeriodLabel,
    programmeCode: entry.programmeCode,
    status: entry.status ?? (getErrorsCount(response) > 0 ? 'partial' : 'success'),
    response,
    warningsCount: entry.warningsCount ?? getWarningsCount(response),
    errorsCount: entry.errorsCount ?? getErrorsCount(response),
  }
}

export const loadUploadHistory = (): UploadMeta[] => {
  try {
    const parsed = safeParse<UploadMeta[]>(storage()?.getItem(UPLOADS_KEY) ?? null)
    return Array.isArray(parsed) ? parsed.map(compactUploadMeta) : []
  } catch {
    return []
  }
}

export const saveUploadHistory = (history: UploadMeta[]): void => {
  try {
    storage()?.setItem(UPLOADS_KEY, JSON.stringify(history.map(compactUploadMeta)))
  } catch {
    // Upload success state is kept in React; local history persistence is best-effort.
  }
}
