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
  hydrateSupabaseSession,
  me,
  readStoredAuthSession,
  saveAuthSession,
  updateStaffActorName as updateStaffActorNameApi,
} from '../api/auth'
import { signOutFromSupabase } from '../api/supabaseClient'
import { frontendConfig } from '../config/frontendConfig'
import type { AuthIdentity, AuthSessionState, StoredAuthSession } from '../types/auth'
import { clearMemoryCache } from '../utils/memoryReadCache'
import { AuthContext, type AuthContextValue } from './authContext'
import { useAppState } from './useAppState'

export const AuthProvider = ({ children }: PropsWithChildren) => {
  const { setRole } = useAppState()
  const [session, setSession] = useState<StoredAuthSession | null>(() =>
    frontendConfig.authMode === 'supabase' ? null : readStoredAuthSession(),
  )
  const [isLoading, setIsLoading] = useState(() =>
    frontendConfig.authMode === 'supabase' || readStoredAuthSession() !== null,
  )

  const hydrateSession = useCallback(async () => {
    if (frontendConfig.authMode === 'supabase') {
      setIsLoading(true)
      try {
        const hydratedSession = await hydrateSupabaseSession()
        if (!hydratedSession) {
          clearAuthSession()
          setSession(null)
          return
        }
        saveAuthSession(hydratedSession)
        setSession(hydratedSession)
        setRole(hydratedSession.identity.role)
      } catch {
        try {
          await signOutFromSupabase()
        } catch {
          // Keep the local fail-closed state even if Supabase sign-out cannot complete.
        }
        clearAuthSession()
        setSession(null)
      } finally {
        setIsLoading(false)
      }
      return
    }

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
    let active = true
    ;(async () => {
      try {
        if (frontendConfig.authMode === 'supabase') {
          const hydratedSession = await hydrateSupabaseSession()
          if (!active) {
            return
          }
          if (!hydratedSession) {
            clearAuthSession()
            setSession(null)
            return
          }
          saveAuthSession(hydratedSession)
          setSession(hydratedSession)
          setRole(hydratedSession.identity.role)
          return
        }

        const storedSession = readStoredAuthSession()
        if (!storedSession) {
          return
        }

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
          if (frontendConfig.authMode === 'supabase') {
            try {
              await signOutFromSupabase()
            } catch {
              // Keep the local fail-closed state even if Supabase sign-out cannot complete.
            }
          }
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

  const logout = useCallback(async () => {
    if (frontendConfig.authMode === 'supabase') {
      try {
        await signOutFromSupabase()
      } catch {
        // A local logout must still clear the MATA session if the network is unavailable.
      }
    }
    clearAuthSession()
    setSession(null)
    clearMemoryCache()
  }, [])

  const updateStaffActorName = useCallback(
    async (fullName: string) => {
      if (!session) {
        throw new Error('No active staff session.')
      }
      const updatedIdentity = await updateStaffActorNameApi(session, fullName)
      const updatedSession: StoredAuthSession = {
        ...session,
        identity: updatedIdentity,
      }
      saveAuthSession(updatedSession)
      setSession(updatedSession)
      setRole(updatedIdentity.role)
      clearMemoryCache()
      return updatedIdentity
    },
    [session, setRole],
  )

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

  const staffActorNameRequired = Boolean(
    effectiveIdentity &&
      (effectiveIdentity.role === 'master_admin' ||
        effectiveIdentity.role === 'programme_pc' ||
        effectiveIdentity.role === 'secretary') &&
      effectiveIdentity.staffActorNameRequired,
  )

  const value = useMemo<AuthContextValue>(() => ({
    authState,
    identity: effectiveIdentity,
    session,
    hasExplicitSession: session !== null,
    isLoading,
    staffActorNameRequired,
    hydrateSession,
    loginWithSession,
    updateStaffActorName,
    logout,
  }), [
    authState,
    effectiveIdentity,
    session,
    isLoading,
    staffActorNameRequired,
    hydrateSession,
    loginWithSession,
    updateStaffActorName,
    logout,
  ])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
