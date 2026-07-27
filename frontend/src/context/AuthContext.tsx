import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react'
import {
  announceAuthSessionEstablished,
  authSessionChangedEvent,
  authSessionRevalidationEvent,
  captureAuthSessionFence,
  hydrateAuthSession,
  isAuthSessionFenceCurrent,
  logoutAuthSession,
  readAuthSessionEpoch,
  readAuthSessionRevision,
  readStoredAuthSession,
  refreshAuthSession,
  saveAuthSession,
  saveHydratedAuthSession,
  updateStaffActorName as updateStaffActorNameApi,
} from '../api/auth'
import {
  announceAuthSessionRotated,
  clearAuthSessionIfPresent,
  createAuthSessionRevalidationCoordinator,
  type ClearAuthSessionOptions,
} from '../api/authSessionStore'
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

  const clearLocalAuthState = useCallback((
    options?: ClearAuthSessionOptions,
  ) => {
    clearAuthSessionIfPresent(options)
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

  const commitHydratedSession = useCallback((nextSession: StoredAuthSession) => {
    if (saveHydratedAuthSession(nextSession)) {
      setSession(nextSession)
      setRole(nextSession.identity.role)
      clearMemoryCache()
    }
    if (readAuthSessionEpoch() === null) {
      announceAuthSessionEstablished()
    }
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
      return { session: hydratedSession, rotated: false }
    }

    // Stage the synchronizer token only after this hydration request wins.
    saveAuthSession(hydratedSession)
    const stagedSessionRevision = readAuthSessionRevision()
    const refreshedSession = await refreshAuthSession()
    const refreshedResult = (
      isCurrentAuthRequest(generation) &&
      readAuthSessionRevision() === stagedSessionRevision
    )
      ? refreshedSession
      : null
    return refreshedResult
      ? { session: refreshedResult, rotated: true }
      : null
  }, [isCurrentAuthRequest])

  const hydrateSession = useCallback(async () => {
    const generation = nextAuthRequestGeneration()
    const sessionRevision = readAuthSessionRevision()
    setIsLoading(true)
    try {
      const hydratedResult = await loadHydratedSession(generation, sessionRevision)
      if (hydratedResult && isCurrentAuthRequest(generation)) {
        commitHydratedSession(hydratedResult.session)
        if (hydratedResult.rotated) {
          announceAuthSessionRotated()
        }
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
    commitHydratedSession,
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
        const hydratedResult = await loadHydratedSession(generation, sessionRevision)
        if (hydratedResult && active && isCurrentAuthRequest(generation)) {
          commitHydratedSession(hydratedResult.session)
          if (hydratedResult.rotated) {
            announceAuthSessionRotated()
          }
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
    commitHydratedSession,
    isCurrentAuthRequest,
    loadHydratedSession,
    nextAuthRequestGeneration,
  ])

  useEffect(() => {
    const onSessionChanged = () => {
      const nextSession = readStoredAuthSession()
      setSession(nextSession)
      setRole(nextSession?.identity.role ?? frontendConfig.defaultRole)
      if (!nextSession) {
        clearMemoryCache()
      }
    }
    window.addEventListener(authSessionChangedEvent, onSessionChanged)
    return () => window.removeEventListener(authSessionChangedEvent, onSessionChanged)
  }, [setRole])

  useEffect(() => {
    const revalidation = createAuthSessionRevalidationCoordinator(
      hydrateSession,
      () => Boolean(readStoredAuthSession()),
    )
    const onFocus = () => revalidation.request(true)
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        revalidation.request(true)
      }
    }
    const onCrossTabRevalidation = () => revalidation.request(true)

    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibilityChange)
    window.addEventListener(authSessionRevalidationEvent, onCrossTabRevalidation)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      window.removeEventListener(authSessionRevalidationEvent, onCrossTabRevalidation)
      revalidation.dispose()
    }
  }, [hydrateSession])

  const loginWithSession = useCallback(
    (nextSession: StoredAuthSession) => {
      nextAuthRequestGeneration()
      announceAuthSessionEstablished()
      commitSession(nextSession)
    },
    [commitSession, nextAuthRequestGeneration],
  )

  const logout = useCallback(async () => {
    const currentSession = readStoredAuthSession()
    const sessionFence = captureAuthSessionFence()
    nextAuthRequestGeneration()
    const logoutRequest = currentSession && sessionFence
      ? logoutAuthSession(currentSession, sessionFence)
      : Promise.resolve()
    clearLocalAuthState({
      broadcast: 'logout',
      sessionEpoch: sessionFence?.sessionEpoch,
    })
    try {
      await logoutRequest
    } catch {
      // Local termination is immediate; server logout remains best effort.
    }
  }, [clearLocalAuthState, nextAuthRequestGeneration])

  const updateStaffActorName = useCallback(
    async (fullName: string) => {
      const operationSession = readStoredAuthSession()
      const operationFence = captureAuthSessionFence()
      const operationGeneration = authRequestGenerationRef.current
      if (!operationSession || !operationFence) {
        throw new Error('No active staff session.')
      }
      const updatedIdentity = await updateStaffActorNameApi(fullName)
      if (
        !isCurrentAuthRequest(operationGeneration)
        || !isAuthSessionFenceCurrent(operationFence)
      ) {
        return updatedIdentity
      }
      const updatedSession: StoredAuthSession = {
        ...operationSession,
        identity: updatedIdentity,
      }
      commitSession(updatedSession)
      return updatedIdentity
    },
    [commitSession, isCurrentAuthRequest],
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
