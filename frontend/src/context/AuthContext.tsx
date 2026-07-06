import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react'
import {
  authSessionChangedEvent,
  clearAuthSession,
  hydrateMataResidentSession,
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
  const authRequestGenerationRef = useRef(0)

  const nextAuthRequestGeneration = useCallback(() => {
    authRequestGenerationRef.current += 1
    return authRequestGenerationRef.current
  }, [])

  const isCurrentAuthRequest = useCallback(
    (generation: number) => authRequestGenerationRef.current === generation,
    [],
  )

  const hydrateSession = useCallback(async () => {
    const generation = nextAuthRequestGeneration()
    if (frontendConfig.authMode === 'supabase') {
      setIsLoading(true)
      try {
        const hydratedSession = await hydrateSupabaseSession() ?? await hydrateMataResidentSession()
        if (!isCurrentAuthRequest(generation)) {
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
      } catch {
        if (!isCurrentAuthRequest(generation)) {
          return
        }
        try {
          await signOutFromSupabase()
        } catch {
          // Keep the local fail-closed state even if Supabase sign-out cannot complete.
        }
        if (!isCurrentAuthRequest(generation)) {
          return
        }
        clearAuthSession()
        setSession(null)
      } finally {
        if (isCurrentAuthRequest(generation)) {
          setIsLoading(false)
        }
      }
      return
    }

    const storedSession = readStoredAuthSession()
    if (!storedSession) {
      if (isCurrentAuthRequest(generation)) {
        setSession(null)
        setIsLoading(false)
      }
      return
    }

    setIsLoading(true)
    try {
      const hydratedIdentity = await me(storedSession)
      if (!isCurrentAuthRequest(generation)) {
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
      if (isCurrentAuthRequest(generation)) {
        clearAuthSession()
        setSession(null)
      }
    } finally {
      if (isCurrentAuthRequest(generation)) {
        setIsLoading(false)
      }
    }
  }, [isCurrentAuthRequest, nextAuthRequestGeneration, setRole])

  useEffect(() => {
    let active = true
    const generation = nextAuthRequestGeneration()
    ;(async () => {
      try {
        if (frontendConfig.authMode === 'supabase') {
          const hydratedSession = await hydrateSupabaseSession() ?? await hydrateMataResidentSession()
          if (!active || !isCurrentAuthRequest(generation)) {
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
        if (!active || !isCurrentAuthRequest(generation)) {
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
        if (active && isCurrentAuthRequest(generation)) {
          if (frontendConfig.authMode === 'supabase') {
            try {
              await signOutFromSupabase()
            } catch {
              // Keep the local fail-closed state even if Supabase sign-out cannot complete.
            }
          }
          if (!isCurrentAuthRequest(generation)) {
            return
          }
          clearAuthSession()
          setSession(null)
        }
      } finally {
        if (active && isCurrentAuthRequest(generation)) {
          setIsLoading(false)
        }
      }
    })()

    return () => {
      active = false
    }
  }, [isCurrentAuthRequest, nextAuthRequestGeneration, setRole])

  useEffect(() => {
    const onSessionChanged = () => {
      setSession(readStoredAuthSession())
    }
    window.addEventListener(authSessionChangedEvent, onSessionChanged)
    return () => window.removeEventListener(authSessionChangedEvent, onSessionChanged)
  }, [])

  const loginWithSession = useCallback(
    (nextSession: StoredAuthSession) => {
      nextAuthRequestGeneration()
      saveAuthSession(nextSession)
      setSession(nextSession)
      setIsLoading(false)
      setRole(nextSession.identity.role)
      clearMemoryCache()
    },
    [nextAuthRequestGeneration, setRole],
  )

  const logout = useCallback(async () => {
    nextAuthRequestGeneration()
    if (frontendConfig.authMode === 'supabase') {
      try {
        await signOutFromSupabase()
      } catch {
        // A local logout must still clear the MATA session if the network is unavailable.
      }
    }
    clearAuthSession()
    setSession(null)
    setIsLoading(false)
    clearMemoryCache()
  }, [nextAuthRequestGeneration])

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
