import type { NormalizedWarning, UploadMeta } from '../types/upload'

const UPLOADS_KEY = 'mata.admin.uploads.v1'
const WARNINGS_KEY = 'mata.admin.warnings.v1'
const WARNING_CONTEXT_KEY = 'mata.warning.context.v1'

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

export const loadUploadHistory = (): UploadMeta[] =>
  safeParse<UploadMeta[]>(sessionStorage.getItem(UPLOADS_KEY)) ?? []

export const saveUploadHistory = (history: UploadMeta[]): void => {
  sessionStorage.setItem(UPLOADS_KEY, JSON.stringify(history))
}

export const loadWarnings = (): NormalizedWarning[] =>
  safeParse<NormalizedWarning[]>(sessionStorage.getItem(WARNINGS_KEY)) ?? []

export const saveWarnings = (warnings: NormalizedWarning[]): void => {
  sessionStorage.setItem(WARNINGS_KEY, JSON.stringify(warnings))
}

export const saveWarningContext = (warning: NormalizedWarning): void => {
  sessionStorage.setItem(WARNING_CONTEXT_KEY, JSON.stringify(warning))
}

export const loadWarningContext = (): NormalizedWarning | null =>
  safeParse<NormalizedWarning>(sessionStorage.getItem(WARNING_CONTEXT_KEY))
