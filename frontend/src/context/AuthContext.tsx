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

  const clearLocalAuthState = useCallback(() => {
    clearAuthSession()
    setSession(null)
    setIsLoading(false)
    clearMemoryCache()
  }, [])

  const beginLoginAttempt = useCallback(() => {
    const generation = nextAuthRequestGeneration()
    clearLocalAuthState()
    return generation
  }, [clearLocalAuthState, nextAuthRequestGeneration])

  const clearCurrentAuthRequest = useCallback(
    async (generation: number, options?: { signOutSupabase?: boolean }) => {
      if (!isCurrentAuthRequest(generation)) {
        return false
      }
      if (options?.signOutSupabase && frontendConfig.authMode === 'supabase') {
        try {
          await signOutFromSupabase()
        } catch {
          // A latest-request cleanup must still clear local MATA state if Supabase sign-out fails.
        }
        if (!isCurrentAuthRequest(generation)) {
          return false
        }
      }
      clearLocalAuthState()
      return true
    },
    [clearLocalAuthState, isCurrentAuthRequest],
  )

  const hydrateSession = useCallback(async () => {
    const generation = nextAuthRequestGeneration()
    if (frontendConfig.authMode === 'supabase') {
      setIsLoading(true)
      try {
        const hydratedSession =
          await hydrateSupabaseSession() ?? await hydrateMataResidentSession()
        if (!isCurrentAuthRequest(generation)) {
          return
        }
        if (!hydratedSession) {
          clearLocalAuthState()
          return
        }
        saveAuthSession(hydratedSession)
        setSession(hydratedSession)
        setRole(hydratedSession.identity.role)
      } catch {
        if (!isCurrentAuthRequest(generation)) {
          return
        }
        clearLocalAuthState()
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
        clearLocalAuthState()
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
        clearLocalAuthState()
      }
    } finally {
      if (isCurrentAuthRequest(generation)) {
        setIsLoading(false)
      }
    }
  }, [clearLocalAuthState, isCurrentAuthRequest, nextAuthRequestGeneration, setRole])

  useEffect(() => {
    let active = true
    const generation = nextAuthRequestGeneration()
    ;(async () => {
      try {
        if (frontendConfig.authMode === 'supabase') {
          const hydratedSession =
            await hydrateSupabaseSession() ??
            await hydrateMataResidentSession()
          if (!active || !isCurrentAuthRequest(generation)) {
            return
          }
          if (!hydratedSession) {
            clearLocalAuthState()
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
          clearLocalAuthState()
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
  }, [clearLocalAuthState, isCurrentAuthRequest, nextAuthRequestGeneration, setRole])

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
    beginLoginAttempt,
    isAuthRequestCurrent: isCurrentAuthRequest,
    clearCurrentAuthRequest,
    loginWithSession,
    updateStaffActorName,
    logout,
  }), [
    authState,
    beginLoginAttempt,
    clearCurrentAuthRequest,
    effectiveIdentity,
    session,
    isLoading,
    staffActorNameRequired,
    hydrateSession,
    isCurrentAuthRequest,
    loginWithSession,
    updateStaffActorName,
    logout,
  ])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
