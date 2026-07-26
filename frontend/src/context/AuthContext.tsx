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
  hydrateAuthSession,
  logoutAuthSession,
  readAuthSessionRevision,
  readStoredAuthSession,
  refreshAuthSession,
  saveAuthSession,
  updateStaffActorName as updateStaffActorNameApi,
} from '../api/auth'
import { frontendConfig } from '../config/frontendConfig'
import type { AuthIdentity, AuthSessionState, StoredAuthSession } from '../types/auth'
import { clearMemoryCache } from '../utils/memoryReadCache'
import { AuthContext, type AuthContextValue } from './authContext'
import { useAppState } from './useAppState'

export const AuthProvider = ({ children }: PropsWithChildren) => {
  const { setRole } = useAppState()
  const [session, setSession] = useState<StoredAuthSession | null>(readStoredAuthSession)
  const [isLoading, setIsLoading] = useState(true)
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
    setRole(frontendConfig.defaultRole)
    setIsLoading(false)
    clearMemoryCache()
  }, [setRole])

  const commitSession = useCallback((nextSession: StoredAuthSession) => {
    saveAuthSession(nextSession)
    setSession(nextSession)
    setRole(nextSession.identity.role)
    setIsLoading(false)
    clearMemoryCache()
  }, [setRole])

  const beginLoginAttempt = useCallback(() => {
    const generation = nextAuthRequestGeneration()
    clearLocalAuthState()
    return generation
  }, [clearLocalAuthState, nextAuthRequestGeneration])

  const clearCurrentAuthRequest = useCallback(
    async (generation: number) => {
      if (!isCurrentAuthRequest(generation)) {
        return false
      }
      clearLocalAuthState()
      return true
    },
    [clearLocalAuthState, isCurrentAuthRequest],
  )

  const loadHydratedSession = useCallback(async (
    generation: number,
    expectedSessionRevision: number,
  ) => {
    const hydratedSession = await hydrateAuthSession()
    if (
      !isCurrentAuthRequest(generation) ||
      readAuthSessionRevision() !== expectedSessionRevision
    ) {
      return null
    }
    if (!hydratedSession.sessionRefreshRequired) {
      return hydratedSession
    }

    // Stage the synchronizer token only after this hydration request wins.
    saveAuthSession(hydratedSession)
    const stagedSessionRevision = readAuthSessionRevision()
    const refreshedSession = await refreshAuthSession()
    return (
      isCurrentAuthRequest(generation) &&
      readAuthSessionRevision() === stagedSessionRevision
    )
      ? refreshedSession
      : null
  }, [isCurrentAuthRequest])

  const hydrateSession = useCallback(async () => {
    const generation = nextAuthRequestGeneration()
    const sessionRevision = readAuthSessionRevision()
    setIsLoading(true)
    try {
      const hydratedSession = await loadHydratedSession(generation, sessionRevision)
      if (hydratedSession && isCurrentAuthRequest(generation)) {
        commitSession(hydratedSession)
      }
    } catch {
      if (isCurrentAuthRequest(generation)) {
        clearLocalAuthState()
      }
    } finally {
      if (isCurrentAuthRequest(generation)) {
        setIsLoading(false)
      }
    }
  }, [
    clearLocalAuthState,
    commitSession,
    isCurrentAuthRequest,
    loadHydratedSession,
    nextAuthRequestGeneration,
  ])

  useEffect(() => {
    let active = true
    const generation = nextAuthRequestGeneration()
    const sessionRevision = readAuthSessionRevision()
    ;(async () => {
      try {
        const hydratedSession = await loadHydratedSession(generation, sessionRevision)
        if (hydratedSession && active && isCurrentAuthRequest(generation)) {
          commitSession(hydratedSession)
        }
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
  }, [
    clearLocalAuthState,
    commitSession,
    isCurrentAuthRequest,
    loadHydratedSession,
    nextAuthRequestGeneration,
  ])

  useEffect(() => {
    const onSessionChanged = () => {
      const nextSession = readStoredAuthSession()
      setSession(nextSession)
      setRole(nextSession?.identity.role ?? frontendConfig.defaultRole)
    }
    window.addEventListener(authSessionChangedEvent, onSessionChanged)
    return () => window.removeEventListener(authSessionChangedEvent, onSessionChanged)
  }, [setRole])

  const loginWithSession = useCallback(
    (nextSession: StoredAuthSession) => {
      nextAuthRequestGeneration()
      commitSession(nextSession)
    },
    [commitSession, nextAuthRequestGeneration],
  )

  const logout = useCallback(async () => {
    nextAuthRequestGeneration()
    try {
      await logoutAuthSession()
    } catch {
      // Server expiry or a network failure must not leave protected UI mounted locally.
    } finally {
      clearLocalAuthState()
    }
  }, [clearLocalAuthState, nextAuthRequestGeneration])

  const updateStaffActorName = useCallback(
    async (fullName: string) => {
      if (!session) {
        throw new Error('No active staff session.')
      }
      const updatedIdentity = await updateStaffActorNameApi(fullName)
      const updatedSession: StoredAuthSession = {
        ...session,
        identity: updatedIdentity,
      }
      commitSession(updatedSession)
      return updatedIdentity
    },
    [commitSession, session],
  )

  const effectiveIdentity = useMemo<AuthIdentity | null>(
    () => session?.identity ?? null,
    [session],
  )

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
    hydrateSession,
    isCurrentAuthRequest,
    isLoading,
    loginWithSession,
    logout,
    session,
    staffActorNameRequired,
    updateStaffActorName,
  ])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
