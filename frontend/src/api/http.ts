import axios from 'axios'
import { frontendConfig } from '../config/frontendConfig'
import { clearMemoryCache } from '../utils/memoryReadCache'
import { readStoredAuthSession } from './authSessionStore'
import { getCurrentSupabaseAccessToken } from './supabaseClient'

declare module 'axios' {
  interface AxiosRequestConfig {
    skipMemoryCacheClear?: boolean
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
})

const isMataResidentSessionRole = (role: string) =>
  role === 'resident' || role === 'external_resident'

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

httpClient.interceptors.request.use(async (request) => {
  request.headers = request.headers ?? {}

  if (frontendConfig.authMode !== 'supabase') {
    return request
  }

  delete request.headers['X-User-Role']
  delete request.headers['X-User-Id']
  delete request.headers['X-User-Programme']
  delete request.headers['X-User-Site']
  delete request.headers['X-User-MCR']
  delete request.headers['X-Admin-Level']

  const explicitAuthorization = headerValue(request.headers, 'Authorization')
  const hasExplicitAuthorization =
    typeof explicitAuthorization === 'string' && explicitAuthorization.trim().length > 0
  if (hasExplicitAuthorization) {
    return request
  }

  const storedSession = readStoredAuthSession()
  if (
    storedSession?.mode === 'supabase' &&
    isMataResidentSessionRole(storedSession.identity.role) &&
    storedSession?.accessToken
  ) {
    setHeaderValue(request.headers, 'Authorization', `Bearer ${storedSession.accessToken}`)
    return request
  }

  const accessToken = await getCurrentSupabaseAccessToken()
  if (accessToken) {
    setHeaderValue(request.headers, 'Authorization', `Bearer ${accessToken}`)
  }

  return request
})

httpClient.interceptors.response.use((response) => {
  const method = response.config.method?.toUpperCase()
  if (
    method &&
    method !== 'GET' &&
    response.status >= 200 &&
    response.status < 300 &&
    !response.config.skipMemoryCacheClear
  ) {
    clearMemoryCache()
  }
  return response
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
