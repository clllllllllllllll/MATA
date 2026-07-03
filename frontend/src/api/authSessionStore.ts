import type { StoredAuthSession } from '../types/auth'

const AUTH_SESSION_KEY = 'mata.auth.session.v1'
const AUTH_SESSION_CHANGED_EVENT = 'mata-auth-session-change'

const isBrowser = () => typeof window !== 'undefined'

const notifySessionChanged = () => {
  if (isBrowser()) {
    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT))
  }
}

export const authSessionChangedEvent = AUTH_SESSION_CHANGED_EVENT

export const readStoredAuthSession = (): StoredAuthSession | null => {
  if (!isBrowser()) {
    return null
  }
  const rawValue = window.sessionStorage.getItem(AUTH_SESSION_KEY)
  if (!rawValue) {
    return null
  }
  try {
    const parsed = JSON.parse(rawValue) as StoredAuthSession
    if (!parsed?.identity?.role || !parsed.accessToken) {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export const saveAuthSession = (session: StoredAuthSession) => {
  if (isBrowser()) {
    window.sessionStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(session))
  }
  notifySessionChanged()
}

export const clearAuthSession = () => {
  if (isBrowser()) {
    window.sessionStorage.removeItem(AUTH_SESSION_KEY)
  }
  notifySessionChanged()
}
