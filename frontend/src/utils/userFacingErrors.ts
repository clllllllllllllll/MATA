const GENERIC_UNKNOWN_MESSAGE = 'Something went wrong. Try again or contact support.'
const GENERIC_SERVER_MESSAGE = 'The system could not complete the request. Try again later.'
const GENERIC_AUTH_MESSAGE = 'Your session could not be verified. Sign in again and retry.'
const GENERIC_VALIDATION_MESSAGE = 'Some information could not be saved. Review the form and try again.'

type ErrorLike = {
  message?: unknown
  status?: unknown
  details?: unknown
  isNetworkError?: unknown
}

interface UserFacingErrorOptions {
  fallbackMessage?: string
  authMessage?: string
  validationMessage?: string
  conflictMessage?: string
  serverMessage?: string
  unknownMessage?: string
}

const uuidLikePattern =
  /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/i

const rawFieldPattern =
  /\b(reporting_period_id|upload_log_id|warning_issue_id|entity_id|log_id|source_payload|metadata_json|before_json|after_json|workflow_status|fingerprint)\b/i

const internalErrorCodePattern = /\b[A-Z][A-Z0-9]*_[A-Z0-9_]*\b/

const technicalMessagePattern =
  /(request failed with status|stack trace|traceback|exception|error_code|metadata|raw json|sqlalchemy|psycopg|postgres|unique constraint|foreign key|integrityerror|cors|localhost|docker|backend|frontend proxy)/i

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null

const toErrorLike = (error: unknown): ErrorLike => {
  if (!error || typeof error !== 'object') {
    return {}
  }
  return error as ErrorLike
}

const normaliseMessage = (value: unknown) =>
  typeof value === 'string' ? value.trim() : ''

const numericStatus = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined

export const isSafeUserFacingMessage = (value: unknown): value is string => {
  const message = normaliseMessage(value)
  if (!message) {
    return false
  }
  if (uuidLikePattern.test(message) || rawFieldPattern.test(message)) {
    return false
  }
  if (/^\s*[{[]/.test(message) || /"\w+"\s*:/.test(message)) {
    return false
  }
  if (/\b(4\d\d|5\d\d)\b/.test(message) || technicalMessagePattern.test(message)) {
    return false
  }
  if (internalErrorCodePattern.test(message)) {
    return false
  }
  return true
}

const firstSafeDetailMessage = (value: unknown): string | null => {
  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = firstSafeDetailMessage(item)
      if (nested) {
        return nested
      }
    }
    return null
  }

  const record = asRecord(value)
  if (!record) {
    return isSafeUserFacingMessage(value) ? value : null
  }
  const candidates = [
    record.message,
    record.detail,
    ...(Array.isArray(record.errors) ? record.errors : []),
  ]
  for (const candidate of candidates) {
    if (isSafeUserFacingMessage(candidate)) {
      return candidate
    }
    const nested = firstSafeDetailMessage(candidate)
    if (nested) {
      return nested
    }
  }
  return null
}

export const formatUserFacingApiError = (
  error: unknown,
  options: UserFacingErrorOptions = {},
): string => {
  const source = toErrorLike(error)
  const status = numericStatus(source.status)
  const fallback = options.fallbackMessage ?? options.unknownMessage ?? GENERIC_UNKNOWN_MESSAGE

  if (source.isNetworkError === true) {
    return options.serverMessage ?? GENERIC_SERVER_MESSAGE
  }

  if (status === 401 || status === 403) {
    return options.authMessage ?? GENERIC_AUTH_MESSAGE
  }

  if (status === 422) {
    return (
      firstSafeDetailMessage(source.details) ??
      (isSafeUserFacingMessage(source.message) ? source.message : null) ??
      options.validationMessage ??
      GENERIC_VALIDATION_MESSAGE
    )
  }

  if (status === 409) {
    return (
      firstSafeDetailMessage(source.details) ??
      (isSafeUserFacingMessage(source.message) ? source.message : null) ??
      options.conflictMessage ??
      fallback
    )
  }

  if (status !== undefined && status >= 500) {
    return options.serverMessage ?? GENERIC_SERVER_MESSAGE
  }

  if (firstSafeDetailMessage(source.details)) {
    return firstSafeDetailMessage(source.details) ?? fallback
  }

  if (isSafeUserFacingMessage(source.message)) {
    return source.message
  }

  return fallback
}
