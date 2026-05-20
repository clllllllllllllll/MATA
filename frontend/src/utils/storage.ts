import type { NormalizedWarning, UploadMeta } from '../types/upload'

const UPLOADS_KEY = 'mata.admin.uploads.v1'
const WARNINGS_KEY = 'mata.admin.warnings.v1'
const WARNING_CONTEXT_KEY = 'mata.warning.context.v1'
const WARNINGS_BY_SCOPE_KEY = 'mata.admin.warnings_by_scope.v1'

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

export const loadWarningsByScope = (): Record<string, NormalizedWarning[]> => {
  const scoped = safeParse<Record<string, NormalizedWarning[]>>(sessionStorage.getItem(WARNINGS_BY_SCOPE_KEY))
  if (scoped && typeof scoped === 'object') {
    return scoped
  }

  const flatWarnings = loadWarnings()
  if (flatWarnings.length === 0) {
    return {}
  }

  const migrated: Record<string, NormalizedWarning[]> = {}
  flatWarnings.forEach((warning) => {
    const scopeKey = warning.scopeKey ?? warning.uploadType
    if (!migrated[scopeKey]) {
      migrated[scopeKey] = []
    }
    migrated[scopeKey].push(warning)
  })
  return migrated
}

export const saveWarningsByScope = (warningsByScope: Record<string, NormalizedWarning[]>): void => {
  sessionStorage.setItem(WARNINGS_BY_SCOPE_KEY, JSON.stringify(warningsByScope))
  const flattened = Object.values(warningsByScope).flat()
  saveWarnings(flattened)
}

export const saveWarningContext = (warning: NormalizedWarning): void => {
  sessionStorage.setItem(WARNING_CONTEXT_KEY, JSON.stringify(warning))
}

export const loadWarningContext = (): NormalizedWarning | null =>
  safeParse<NormalizedWarning>(sessionStorage.getItem(WARNING_CONTEXT_KEY))
