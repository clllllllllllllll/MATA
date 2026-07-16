export const GENERIC_LOGIN_ERROR = 'Unable to sign in. Check your details and try again.'
export const LOGIN_RATE_LIMIT_ERROR = 'Too many sign-in attempts. Please try again in 1 minute.'

const DEFAULT_LOGIN_RATE_LIMIT_RETRY_AFTER_SECONDS = 60

interface LoginErrorLike extends Error {
  status?: number
  retryAfterSeconds?: number
}

const formatRetryAfter = (seconds: number): string => {
  if (seconds <= 60) {
    return '1 minute'
  }
  const minutes = Math.ceil(seconds / 60)
  return `${minutes} minutes`
}

export const isRateLimitError = (error: unknown): error is LoginErrorLike =>
  error instanceof Error && (error as LoginErrorLike).status === 429

export const getRateLimitLoginErrorMessage = (error: unknown): string | null => {
  if (!isRateLimitError(error)) {
    return null
  }
  const retryAfterSeconds = error.retryAfterSeconds ?? DEFAULT_LOGIN_RATE_LIMIT_RETRY_AFTER_SECONDS
  return `Too many sign-in attempts. Please try again in ${formatRetryAfter(retryAfterSeconds)}.`
}

export const resolveResidentLoginError = (error: unknown): string =>
  getRateLimitLoginErrorMessage(error) ?? GENERIC_LOGIN_ERROR
