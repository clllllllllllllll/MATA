export const CSRF_HEADER_NAME = 'X-CSRF-Token'

const unsafeMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const legacyCredentialHeaders = [
  'X-User-Role',
  'X-User-Id',
  'X-User-Programme',
  'X-User-Site',
  'X-User-MCR',
  'X-Admin-Level',
  'Authorization',
] as const

export const isUnsafeRequestMethod = (method: string | undefined): boolean =>
  unsafeMethods.has((method ?? '').toUpperCase())

export const shouldBlockRequestDuringLogoutPending = (
  logoutPending: boolean,
  explicitlyAllowed: boolean | undefined,
): boolean => logoutPending && explicitlyAllowed !== true

export const csrfHeadersForRequest = (
  method: string | undefined,
  csrfToken: string | undefined,
): Record<string, string> => {
  if (!isUnsafeRequestMethod(method) || !csrfToken?.trim()) {
    return {}
  }
  return { [CSRF_HEADER_NAME]: csrfToken }
}

const setHeaderValue = (headers: unknown, name: string, value: string) => {
  if (!headers || typeof headers !== 'object') {
    return
  }
  const setter = (headers as { set?: unknown }).set
  if (typeof setter === 'function') {
    setter.call(headers, name, value)
    return
  }
  ;(headers as Record<string, unknown>)[name] = value
}

const deleteHeaderValue = (headers: unknown, name: string) => {
  if (!headers || typeof headers !== 'object') {
    return
  }
  const deleter = (headers as { delete?: unknown }).delete
  if (typeof deleter === 'function') {
    deleter.call(headers, name)
  }
  const lowerName = name.toLowerCase()
  for (const key of Object.keys(headers as Record<string, unknown>)) {
    if (key.toLowerCase() === lowerName) {
      delete (headers as Record<string, unknown>)[key]
    }
  }
}

export const applySessionRequestHeaders = (
  headers: unknown,
  options: {
    method?: string
    csrfToken?: string
    stripLegacyCredentials: boolean
  },
) => {
  if (options.stripLegacyCredentials) {
    for (const headerName of legacyCredentialHeaders) {
      deleteHeaderValue(headers, headerName)
    }
  }

  deleteHeaderValue(headers, CSRF_HEADER_NAME)
  const csrfToken = csrfHeadersForRequest(options.method, options.csrfToken)[
    CSRF_HEADER_NAME
  ]
  if (csrfToken) {
    setHeaderValue(headers, CSRF_HEADER_NAME, csrfToken)
  }
}

export const shouldClearSessionForUnauthorized = (
  status: number | undefined,
  requestWasAuthenticated: boolean | undefined,
  requestRevision: number | undefined,
  currentIsAuthenticated: boolean,
  currentRevision: number,
): boolean =>
  status === 401 &&
  requestWasAuthenticated === true &&
  typeof requestRevision === 'number' &&
  currentIsAuthenticated &&
  requestRevision === currentRevision

export const handleUnauthorizedSessionResponse = (
  status: number | undefined,
  requestWasAuthenticated: boolean | undefined,
  requestRevision: number | undefined,
  currentIsAuthenticated: boolean,
  currentRevision: number,
  terminateSession: () => void,
): boolean => {
  if (!shouldClearSessionForUnauthorized(
    status,
    requestWasAuthenticated,
    requestRevision,
    currentIsAuthenticated,
    currentRevision,
  )) {
    return false
  }
  terminateSession()
  return true
}
