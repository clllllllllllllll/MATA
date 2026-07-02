import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react'
import {
  authSessionChangedEvent,
  clearAuthSession,
  me,
  readStoredAuthSession,
  saveAuthSession,
} from '../api/auth'
import { frontendConfig } from '../config/frontendConfig'
import type { AuthIdentity, AuthSessionState, StoredAuthSession } from '../types/auth'
import { clearMemoryCache } from '../utils/memoryReadCache'
import { AuthContext, type AuthContextValue } from './authContext'
import { useAppState } from './useAppState'

export const AuthProvider = ({ children }: PropsWithChildren) => {
  const { setRole } = useAppState()
  const [session, setSession] = useState<StoredAuthSession | null>(() => readStoredAuthSession())
  const [isLoading, setIsLoading] = useState(() => readStoredAuthSession() !== null)

  const hydrateSession = useCallback(async () => {
    const storedSession = readStoredAuthSession()
    if (!storedSession) {
      setSession(null)
      setIsLoading(false)
      return
    }

    setIsLoading(true)
    try {
      const hydratedIdentity = await me(storedSession)
      const hydratedSession: StoredAuthSession = {
        ...storedSession,
        identity: hydratedIdentity,
      }
      saveAuthSession(hydratedSession)
      setSession(hydratedSession)
      setRole(hydratedIdentity.role)
    } catch {
      clearAuthSession()
      setSession(null)
    } finally {
      setIsLoading(false)
    }
  }, [setRole])

  useEffect(() => {
    const storedSession = readStoredAuthSession()
    if (!storedSession) {
      return
    }

    let active = true
    ;(async () => {
      try {
        const hydratedIdentity = await me(storedSession)
        if (!active) {
          return
        }
        const hydratedSession: StoredAuthSession = {
          ...storedSession,
          identity: hydratedIdentity,
        }
        saveAuthSession(hydratedSession)
        setSession(hydratedSession)
        setRole(hydratedIdentity.role)
      } catch {
        if (active) {
          clearAuthSession()
          setSession(null)
        }
      } finally {
        if (active) {
          setIsLoading(false)
        }
      }
    })()

    return () => {
      active = false
    }
  }, [setRole])

  useEffect(() => {
    const onSessionChanged = () => {
      setSession(readStoredAuthSession())
    }
    window.addEventListener(authSessionChangedEvent, onSessionChanged)
    return () => window.removeEventListener(authSessionChangedEvent, onSessionChanged)
  }, [])

  const loginWithSession = useCallback(
    (nextSession: StoredAuthSession) => {
      saveAuthSession(nextSession)
      setSession(nextSession)
      setRole(nextSession.identity.role)
      clearMemoryCache()
    },
    [setRole],
  )

  const logout = useCallback(() => {
    clearAuthSession()
    setSession(null)
    clearMemoryCache()
  }, [])

  const effectiveIdentity = useMemo<AuthIdentity | null>(() => {
    if (session?.identity) {
      return session.identity
    }
    return null
  }, [session])

  const authState = useMemo<AuthSessionState>(() => ({
    mode: frontendConfig.authMode,
    identity: effectiveIdentity,
    role: effectiveIdentity?.role ?? null,
    isAuthenticated: effectiveIdentity !== null,
  }), [effectiveIdentity])

  const value = useMemo<AuthContextValue>(() => ({
    authState,
    identity: effectiveIdentity,
    session,
    hasExplicitSession: session !== null,
    isLoading,
    hydrateSession,
    loginWithSession,
    logout,
  }), [
    authState,
    effectiveIdentity,
    session,
    isLoading,
    hydrateSession,
    loginWithSession,
    logout,
  ])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
