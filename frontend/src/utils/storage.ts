import type { UploadMeta } from '../types/upload'

const UPLOADS_KEY = 'mata.admin.uploads.v1'
let memoryUploadHistory: UploadMeta[] = []

const storage = () => {
  if (typeof window === 'undefined') {
    return null
  }
  return window.localStorage
}

const removeLegacyUploadHistory = (): void => {
  try {
    storage()?.removeItem(UPLOADS_KEY)
  } catch {
    // Legacy browser residue is best-effort cleanup; current history is memory-only.
  }
}

const cloneUploadMeta = (entry: UploadMeta): UploadMeta => ({
  ...entry,
  response: { ...entry.response },
})

export const loadUploadHistory = (): UploadMeta[] => {
  removeLegacyUploadHistory()
  return memoryUploadHistory.map(cloneUploadMeta)
}

export const saveUploadHistory = (history: UploadMeta[]): void => {
  removeLegacyUploadHistory()
  memoryUploadHistory = history.map(cloneUploadMeta)
}

export const clearUploadHistory = (): void => {
  memoryUploadHistory = []
  removeLegacyUploadHistory()
}
