export const AUTH_COOKIE_COORDINATION_HEADER_NAME =
  'X-MATA-Session-Coordination'
export const AUTH_COOKIE_COORDINATION_PROTOCOL = 'web-locks-v1'
export const AUTH_COOKIE_RESPONSE_LOCK_NAME = 'mata-session-cookie-v1'

export type AuthCookieLockManager = {
  request: <T>(
    name: string,
    options: { mode: 'exclusive' },
    callback: () => Promise<T>,
  ) => Promise<T>
}

export type AuthCookieCoordinationEnvironment = {
  secureContext: boolean
  lockManager: AuthCookieLockManager | null
}

export class AuthCookieCoordinationUnavailableError extends Error {
  constructor() {
    super('Secure browser session coordination is unavailable.')
    this.name = 'AuthCookieCoordinationUnavailableError'
  }
}

const readBrowserCoordinationEnvironment =
  (): AuthCookieCoordinationEnvironment => {
    if (
      typeof window === 'undefined'
      || typeof navigator === 'undefined'
      || window.isSecureContext !== true
    ) {
      return { secureContext: false, lockManager: null }
    }

    const lockManager = navigator.locks
      ? navigator.locks as unknown as AuthCookieLockManager
      : null
    return { secureContext: true, lockManager }
  }

const requireLockManager = (
  environment: AuthCookieCoordinationEnvironment,
): AuthCookieLockManager => {
  if (!environment.secureContext || !environment.lockManager) {
    throw new AuthCookieCoordinationUnavailableError()
  }
  return environment.lockManager
}

export const assertAuthCookieCoordinationAvailable = (
  environment: AuthCookieCoordinationEnvironment =
    readBrowserCoordinationEnvironment(),
): void => {
  requireLockManager(environment)
}

export const withAuthCookieResponseLock = async <T>(
  operation: () => Promise<T>,
  environment: AuthCookieCoordinationEnvironment =
    readBrowserCoordinationEnvironment(),
): Promise<T> => {
  const lockManager = requireLockManager(environment)
  return lockManager.request(
    AUTH_COOKIE_RESPONSE_LOCK_NAME,
    { mode: 'exclusive' },
    operation,
  )
}
