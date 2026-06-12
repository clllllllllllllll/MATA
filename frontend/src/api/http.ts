import axios from 'axios'
import { frontendConfig } from '../config/frontendConfig'
import { clearMemoryCache } from '../utils/memoryReadCache'

export class ApiRequestError extends Error {
  status?: number
  details?: unknown
  isNetworkError: boolean

  constructor(
    message: string,
    options?: { status?: number; details?: unknown; isNetworkError?: boolean },
  ) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = options?.status
    this.details = options?.details
    this.isNetworkError = options?.isNetworkError ?? false
  }
}

export const httpClient = axios.create({
  baseURL: frontendConfig.apiBaseUrl,
  timeout: 60000,
})

httpClient.interceptors.response.use((response) => {
  const method = response.config.method?.toUpperCase()
  if (method && method !== 'GET' && response.status >= 200 && response.status < 300) {
    clearMemoryCache()
  }
  return response
})

export const toApiRequestError = (error: unknown): ApiRequestError => {
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
    })
  }

  return new ApiRequestError('Unexpected API error occurred.', { details: error })
}
