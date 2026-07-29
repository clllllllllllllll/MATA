import axios from 'axios'
import { frontendConfig } from '../config/frontendConfig'
import { clearMemoryCache } from '../utils/memoryReadCache'
import {
  clearAuthSession,
  clearAuthSessionIfPresent,
  readAuthSessionEpoch,
  readAuthSessionRevision,
  readStoredAuthSession,
} from './authSessionStore'
import {
  assertAuthCookieCoordinationAvailable,
  AUTH_COOKIE_COORDINATION_HEADER_NAME,
  AUTH_COOKIE_COORDINATION_PROTOCOL,
} from './authCookieCoordination'
import {
  applySessionRequestHeaders,
  handleUnauthorizedSessionResponse,
  isUnsafeRequestMethod,
  shouldBlockRequestDuringLogoutPending,
} from './httpTransport'
import {
  isLogoutPendingBlocked,
  readLogoutPendingSnapshot,
} from './logoutReliability'

declare module 'axios' {
  interface AxiosRequestConfig {
    skipMemoryCacheClear?: boolean
    authSessionCsrfToken?: string
    authSessionEpoch?: string | null
    authSessionRevision?: number
    authSessionWasAuthenticated?: boolean
    allowDuringLogoutPending?: boolean
  }
}

export class ApiRequestError extends Error {
  status?: number
  details?: unknown
  isNetworkError: boolean
  retryAfterSeconds?: number

  constructor(
    message: string,
    options?: { status?: number; details?: unknown; isNetworkError?: boolean; retryAfterSeconds?: number },
  ) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = options?.status
    this.details = options?.details
    this.isNetworkError = options?.isNetworkError ?? false
    this.retryAfterSeconds = options?.retryAfterSeconds
  }
}

export const httpClient = axios.create({
  baseURL: frontendConfig.apiBaseUrl,
  timeout: 60000,
  withCredentials: true,
})

const headerValue = (headers: unknown, name: string): unknown => {
  if (!headers || typeof headers !== 'object') {
    return undefined
  }

  const getter = (headers as { get?: unknown }).get
  if (typeof getter === 'function') {
    const value = getter.call(headers, name)
    if (value !== null && value !== undefined) {
      return value
    }
  }

  const lowerName = name.toLowerCase()
  for (const [key, value] of Object.entries(headers as Record<string, unknown>)) {
    if (key.toLowerCase() === lowerName) {
      return value
    }
  }
  return undefined
}

httpClient.interceptors.request.use((request) => {
  request.headers = request.headers ?? {}
  if (shouldBlockRequestDuringLogoutPending(
    isLogoutPendingBlocked(readLogoutPendingSnapshot()),
    request.allowDuringLogoutPending,
  )) {
    throw new ApiRequestError(
      'Server logout is not confirmed. Protected requests remain blocked.',
      { status: 409 },
    )
  }
  if (frontendConfig.authMode === 'supabase') {
    try {
      assertAuthCookieCoordinationAvailable()
    } catch (error) {
      clearAuthSessionIfPresent({
        broadcast: 'unauthorized',
        sessionEpoch: readAuthSessionEpoch(),
      })
      clearMemoryCache()
      throw error
    }
    request.headers.set(
      AUTH_COOKIE_COORDINATION_HEADER_NAME,
      AUTH_COOKIE_COORDINATION_PROTOCOL,
    )
  }
  const storedSession = readStoredAuthSession()
  request.authSessionWasAuthenticated = storedSession !== null
  if (request.authSessionRevision === undefined) {
    request.authSessionRevision = readAuthSessionRevision()
  }
  if (request.authSessionEpoch === undefined) {
    request.authSessionEpoch = readAuthSessionEpoch()
  }

  const csrfToken = request.authSessionCsrfToken ?? storedSession?.csrfToken
  delete request.authSessionCsrfToken
  applySessionRequestHeaders(request.headers, {
    method: request.method,
    csrfToken,
    stripLegacyCredentials: frontendConfig.authMode === 'supabase',
  })

  return request
})

httpClient.interceptors.response.use((response) => {
  const method = response.config.method?.toUpperCase()
  if (
    isUnsafeRequestMethod(method) &&
    response.status >= 200 &&
    response.status < 300 &&
    !response.config.skipMemoryCacheClear
  ) {
    clearMemoryCache()
  }
  return response
}, (error: unknown) => {
  if (axios.isAxiosError(error)) {
    handleUnauthorizedSessionResponse(
      error.response?.status,
      error.config?.authSessionWasAuthenticated,
      error.config?.authSessionRevision,
      readStoredAuthSession() !== null,
      readAuthSessionRevision(),
      () => {
        clearAuthSession({
          broadcast: 'unauthorized',
          sessionEpoch: error.config?.authSessionEpoch,
        })
        clearMemoryCache()
      },
    )
  }
  return Promise.reject(error)
})

export const parseRetryAfterSeconds = (value: unknown): number | undefined => {
  const rawValue = Array.isArray(value) ? value[0] : value
  if (typeof rawValue === 'number' && Number.isFinite(rawValue)) {
    return Math.max(1, Math.ceil(rawValue))
  }
  if (typeof rawValue !== 'string') {
    return undefined
  }

  const trimmedValue = rawValue.trim()
  if (!trimmedValue) {
    return undefined
  }

  const numericValue = Number(trimmedValue)
  if (Number.isFinite(numericValue)) {
    return Math.max(1, Math.ceil(numericValue))
  }

  const retryAt = Date.parse(trimmedValue)
  if (!Number.isNaN(retryAt)) {
    return Math.max(1, Math.ceil((retryAt - Date.now()) / 1000))
  }
  return undefined
}

export const toApiRequestError = (error: unknown): ApiRequestError => {
  if (error instanceof ApiRequestError) {
    return error
  }

  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return new ApiRequestError(
        'Cannot reach backend API. Verify backend is running and CORS allows http://localhost:5173.',
        { isNetworkError: true },
      )
    }

    const message =
      typeof error.response.data === 'string'
        ? error.response.data
        : (error.response.data as { detail?: string })?.detail ??
          `Request failed with status ${error.response.status}`

    return new ApiRequestError(message, {
      status: error.response.status,
      details: error.response.data,
      retryAfterSeconds: parseRetryAfterSeconds(headerValue(error.response.headers, 'retry-after')),
    })
  }

  if (error && typeof error === 'object') {
    const candidate = error as { __isAuthError?: unknown; message?: unknown; status?: unknown }
    const isAuthError = candidate.__isAuthError === true
    if (typeof candidate.message === 'string') {
      const numericStatus =
        typeof candidate.status === 'number' && Number.isFinite(candidate.status)
          ? candidate.status
          : undefined
      if (isAuthError || numericStatus !== undefined) {
        return new ApiRequestError(candidate.message, {
          status: numericStatus,
          details: error,
        })
      }
    }
  }

  return new ApiRequestError('Unexpected API error occurred.', { details: error })
}
