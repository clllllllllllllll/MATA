import type { StoredAuthSession } from '../types/auth'

const AUTH_SESSION_CHANGED_EVENT = 'mata-auth-session-change'
let memoryAuthSession: StoredAuthSession | null = null
let memoryAuthSessionRevision = 0

const isBrowser = () => typeof window !== 'undefined'

const notifySessionChanged = () => {
  if (isBrowser()) {
    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT))
  }
}

export const authSessionChangedEvent = AUTH_SESSION_CHANGED_EVENT

export const readStoredAuthSession = (): StoredAuthSession | null => memoryAuthSession
export const readAuthSessionRevision = (): number => memoryAuthSessionRevision

export const saveAuthSession = (session: StoredAuthSession) => {
  memoryAuthSession = session
  memoryAuthSessionRevision += 1
  notifySessionChanged()
}

export const clearAuthSession = () => {
  memoryAuthSession = null
  memoryAuthSessionRevision += 1
  notifySessionChanged()
}
