import type { UploadMeta } from '../types/upload'

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

export const loadUploadHistory = (): UploadMeta[] =>
  safeParse<UploadMeta[]>(sessionStorage.getItem(UPLOADS_KEY)) ?? []

export const saveUploadHistory = (history: UploadMeta[]): void => {
  sessionStorage.setItem(UPLOADS_KEY, JSON.stringify(history))
}
