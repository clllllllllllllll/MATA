export const GENERIC_UPLOAD_VALIDATION_MESSAGE =
  'Upload failed validation or parser checks. Check the workbook type, required fields, and reporting period.'

type UploadErrorLike = {
  message?: string
  status?: number
  details?: unknown
  isNetworkError?: boolean
}

const genericValidationMessages = new Set([
  'Validation failed',
  'Upload failed validation',
  'Upload file validation failed',
  'Request failed with status 422',
  GENERIC_UPLOAD_VALIDATION_MESSAGE,
])

const uuidLikePattern = /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/i

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null

const collectMessageStrings = (value: unknown): string[] => {
  if (typeof value === 'string') {
    return [value]
  }
  if (Array.isArray(value)) {
    return value.flatMap(collectMessageStrings)
  }
  const record = asRecord(value)
  if (!record) {
    return []
  }
  return [
    ...collectMessageStrings(record.message),
    ...collectMessageStrings(record.detail),
  ]
}

const isSafeUserFacingMessage = (value: string) => {
  const message = value.trim()
  if (!message || genericValidationMessages.has(message)) {
    return false
  }
  if (/^[A-Z][A-Z0-9_]{2,}$/.test(message)) {
    return false
  }
  if (/^Request failed with status \d+$/i.test(message)) {
    return false
  }
  if (uuidLikePattern.test(message)) {
    return false
  }
  if (/^\s*[{[]/.test(message) || /"\w+"\s*:/.test(message)) {
    return false
  }
  return !/(stack trace|traceback|exception|error_code|metadata|raw json)/i.test(message)
}

const firstUsefulValidationMessage = (error: UploadErrorLike) => {
  const detailsRecord = asRecord(error.details)
  const candidates = [
    ...collectMessageStrings(detailsRecord?.errors),
    ...collectMessageStrings(detailsRecord?.detail),
    ...collectMessageStrings(detailsRecord?.message),
    ...collectMessageStrings(error.message),
  ]
  return candidates.map((candidate) => candidate.trim()).find(isSafeUserFacingMessage)
}

export const resolveUploadErrorMessage = (error: UploadErrorLike) => {
  if (error.status === 401 || error.status === 403) {
    return 'Upload was rejected because the demo admin is not authorised for this action.'
  }
  if (error.status === 422) {
    return firstUsefulValidationMessage(error) ?? GENERIC_UPLOAD_VALIDATION_MESSAGE
  }
  if (error.status === 409) {
    return 'Another upload is already running for this scope. Try again shortly.'
  }
  if (error.status && error.status >= 500) {
    return 'The server hit an error while processing this upload.'
  }
  if (error.isNetworkError) {
    return 'The system could not complete the upload. Try again later.'
  }
  return error.message && isSafeUserFacingMessage(error.message)
    ? error.message
    : 'Upload failed. Please try again.'
}
