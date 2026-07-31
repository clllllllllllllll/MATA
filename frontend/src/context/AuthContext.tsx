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
  authSessionEstablishedEvent,
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
  type LogoutAuthSessionProof,
} from '../api/auth'
import {
  announceAuthSessionRotated,
  clearAuthSessionIfPresent,
  createAuthSessionRevalidationCoordinator,
  readAuthSessionEstablishedLogoutRequestId,
  type ClearAuthSessionOptions,
} from '../api/authSessionStore'
import {
  createLogoutPendingStore,
  createLogoutRetryCoordinator,
  isLogoutPendingBlocked,
  logoutPendingRequestId,
  type LogoutPendingSnapshot,
  type LogoutRetryCoordinator,
  type LogoutRetrySnapshot,
} from '../api/logoutReliability'
import { ApiRequestError } from '../api/http'
import { frontendConfig } from '../config/frontendConfig'
import type { AuthIdentity, AuthSessionState, StoredAuthSession } from '../types/auth'
import { clearMemoryCache } from '../utils/memoryReadCache'
import { AuthContext, type AuthContextValue } from './authContext'
import { useAppState } from './useAppState'

type PendingLogoutProof = LogoutAuthSessionProof & {
  authGeneration: number
}

const logoutPendingStore = createLogoutPendingStore()

const emptyLogoutRetrySnapshot = (
  pendingSnapshot: LogoutPendingSnapshot,
): LogoutRetrySnapshot => ({
  status: isLogoutPendingBlocked(pendingSnapshot) ? 'unconfirmed' : 'idle',
  requestId:
    logoutPendingRequestId(pendingSnapshot),
  retryCount:
    pendingSnapshot.status === 'pending'
      ? pendingSnapshot.tombstone.retryCount
      : 0,
  inFlight: false,
  proofAvailable: false,
  canRetry: false,
  nextRetryDelayMs: null,
  reason: isLogoutPendingBlocked(pendingSnapshot) ? 'no-proof' : null,
})

const createLogoutRequestId = (): string => {
  const entropy = typeof globalThis.crypto?.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : Math.random().toString(16).slice(2)
  return `${Date.now()}-${entropy}`
}

const isConclusiveUnauthenticatedHydrationError = (error: unknown): boolean =>
  error instanceof ApiRequestError && error.status === 401

export const AuthProvider = ({ children }: PropsWithChildren) => {
  const { setRole } = useAppState()
  const initialLogoutPendingSnapshot = logoutPendingStore.read()
  const [session, setSession] = useState<StoredAuthSession | null>(() =>
    isLogoutPendingBlocked(initialLogoutPendingSnapshot)
      ? null
      : readStoredAuthSession())
  const [isLoading, setIsLoading] = useState(
    !isLogoutPendingBlocked(initialLogoutPendingSnapshot),
  )
  const [logoutStatus, setLogoutStatus] = useState<'none' | 'pending' | 'confirmed'>(
    isLogoutPendingBlocked(initialLogoutPendingSnapshot) ? 'pending' : 'none',
  )
  const [logoutRetryState, setLogoutRetryState] = useState<LogoutRetrySnapshot>(
    () => emptyLogoutRetrySnapshot(initialLogoutPendingSnapshot),
  )
  const authRequestGenerationRef = useRef(0)
  const logoutRetryCoordinatorRef = useRef<LogoutRetryCoordinator | null>(null)
  const loginAttemptRef = useRef<{
    generation: number
    pendingSnapshot: LogoutPendingSnapshot
    knownAbsentBeforeAttempt: boolean
  } | null>(null)
  const deferredAuthRevalidationRef = useRef(false)
  const loginCommitInProgressRef = useRef(false)
  const crossTabLoginCommitInProgressRef = useRef(false)
  const logoutConfirmationInProgressRef = useRef<string | null>(null)
  const authSessionKnownAbsentRef = useRef(
    isLogoutPendingBlocked(initialLogoutPendingSnapshot),
  )
  const initialAuthHydrationPendingRef = useRef(
    !isLogoutPendingBlocked(initialLogoutPendingSnapshot),
  )

  const nextAuthRequestGeneration = useCallback(() => {
    loginAttemptRef.current = null
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
    authSessionKnownAbsentRef.current = true
    clearAuthSessionIfPresent(options)
    setSession(null)
    setRole(frontendConfig.defaultRole)
    setIsLoading(false)
    clearMemoryCache()
  }, [setRole])

  const commitSession = useCallback((nextSession: StoredAuthSession) => {
    authSessionKnownAbsentRef.current = false
    saveAuthSession(nextSession)
    setSession(nextSession)
    setRole(nextSession.identity.role)
    setIsLoading(false)
    clearMemoryCache()
  }, [setRole])

  const commitHydratedSession = useCallback((nextSession: StoredAuthSession) => {
    authSessionKnownAbsentRef.current = false
    if (saveHydratedAuthSession(nextSession)) {
      setSession(nextSession)
      setRole(nextSession.identity.role)
      clearMemoryCache()
    }
    if (readAuthSessionEpoch() === null) {
      announceAuthSessionEstablished()
    }
  }, [setRole])

  const replayDeferredAuthRevalidation = useCallback(() => {
    if (!deferredAuthRevalidationRef.current) {
      return
    }
    deferredAuthRevalidationRef.current = false
    if (
      typeof window === 'undefined'
      || isLogoutPendingBlocked(logoutPendingStore.read())
    ) {
      return
    }
    queueMicrotask(() => {
      window.dispatchEvent(new Event(authSessionRevalidationEvent))
    })
  }, [])

  const beginLoginAttempt = useCallback(() => {
    const knownAbsentBeforeAttempt = authSessionKnownAbsentRef.current
    const generation = nextAuthRequestGeneration()
    const pendingSnapshot = logoutPendingStore.read()
    const activeLogoutRequestId = logoutRetryCoordinatorRef.current
      ?.getSnapshot().requestId
    if (activeLogoutRequestId) {
      logoutRetryCoordinatorRef.current?.cancel(activeLogoutRequestId, 'cancelled')
    }
    loginAttemptRef.current = {
      generation,
      pendingSnapshot,
      knownAbsentBeforeAttempt,
    }
    clearLocalAuthState()
    return generation
  }, [clearLocalAuthState, nextAuthRequestGeneration])

  const clearCurrentAuthRequest = useCallback(
    async (generation: number) => {
      if (!isCurrentAuthRequest(generation)) {
        return false
      }
      const loginAttempt = loginAttemptRef.current?.generation === generation
        ? loginAttemptRef.current
        : null
      if (loginAttempt) {
        loginAttemptRef.current = null
      }
      clearLocalAuthState()
      if (loginAttempt) {
        authSessionKnownAbsentRef.current = loginAttempt.knownAbsentBeforeAttempt
      }
      replayDeferredAuthRevalidation()
      return true
    },
    [
      clearLocalAuthState,
      isCurrentAuthRequest,
      replayDeferredAuthRevalidation,
    ],
  )

  const loadHydratedSession = useCallback(async (
    generation: number,
    expectedSessionRevision: number,
  ) => {
    const hydratedSession = await hydrateAuthSession()
    if (
      !isCurrentAuthRequest(generation) ||
      readAuthSessionRevision() !== expectedSessionRevision ||
      isLogoutPendingBlocked(logoutPendingStore.read())
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
      readAuthSessionRevision() === stagedSessionRevision &&
      !isLogoutPendingBlocked(logoutPendingStore.read())
    )
      ? refreshedSession
      : null
    return refreshedResult
      ? { session: refreshedResult, rotated: true }
      : null
  }, [isCurrentAuthRequest])

  const hydrateSession = useCallback(async () => {
    if (loginAttemptRef.current) {
      deferredAuthRevalidationRef.current = true
      return
    }
    if (isLogoutPendingBlocked(logoutPendingStore.read())) {
      setIsLoading(false)
      return
    }
    const generation = nextAuthRequestGeneration()
    const sessionRevision = readAuthSessionRevision()
    const shouldShowLoading = readStoredAuthSession() === null
    if (shouldShowLoading) {
      setIsLoading(true)
    }
    try {
      const hydratedResult = await loadHydratedSession(generation, sessionRevision)
      if (hydratedResult && isCurrentAuthRequest(generation)) {
        commitHydratedSession(hydratedResult.session)
        if (hydratedResult.rotated) {
          announceAuthSessionRotated()
        }
      }
    } catch (error) {
      if (isCurrentAuthRequest(generation)) {
        clearLocalAuthState()
        authSessionKnownAbsentRef.current =
          isConclusiveUnauthenticatedHydrationError(error)
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
    const pendingSnapshot = logoutPendingStore.read()
    if (isLogoutPendingBlocked(pendingSnapshot)) {
      queueMicrotask(() => {
        if (!active) {
          return
        }
        setLogoutStatus('pending')
        setLogoutRetryState(emptyLogoutRetrySnapshot(pendingSnapshot))
        clearLocalAuthState()
      })
      return () => {
        active = false
      }
    }
    queueMicrotask(() => {
      if (!active) {
        return
      }
      setLogoutStatus('none')
      setLogoutRetryState(emptyLogoutRetrySnapshot({ status: 'clear' }))
    })
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
      } catch (error) {
        if (active && isCurrentAuthRequest(generation)) {
          clearLocalAuthState()
          authSessionKnownAbsentRef.current =
            isConclusiveUnauthenticatedHydrationError(error)
        }
      } finally {
        initialAuthHydrationPendingRef.current = false
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
      if (
        isLogoutPendingBlocked(logoutPendingStore.read())
        && !loginCommitInProgressRef.current
      ) {
        clearAuthSessionIfPresent()
        setSession(null)
        setRole(frontendConfig.defaultRole)
        clearMemoryCache()
        return
      }
      const nextSession = readStoredAuthSession()
      authSessionKnownAbsentRef.current = nextSession === null
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
    let active = true
    let observedResolution = false
    let previousSnapshot = logoutPendingStore.read()
    if (isLogoutPendingBlocked(previousSnapshot)) {
      nextAuthRequestGeneration()
    }
    queueMicrotask(() => {
      if (!active || observedResolution) {
        return
      }
      const currentSnapshot = logoutPendingStore.read()
      if (isLogoutPendingBlocked(currentSnapshot)) {
        setLogoutStatus('pending')
        setLogoutRetryState(emptyLogoutRetrySnapshot(currentSnapshot))
        clearLocalAuthState()
      } else {
        setLogoutStatus('none')
        setLogoutRetryState(emptyLogoutRetrySnapshot(currentSnapshot))
      }
    })
    const unsubscribe = logoutPendingStore.subscribe((
      observedSnapshot,
      changeContext,
    ) => {
      observedResolution ||= changeContext !== undefined
      const wasBlocked = isLogoutPendingBlocked(previousSnapshot)
      const previousRequestId = logoutPendingRequestId(previousSnapshot)
      const pendingLoginRequestId = loginAttemptRef.current
        ? logoutPendingRequestId(loginAttemptRef.current.pendingSnapshot)
        : null
      const confirmationClear =
        previousRequestId !== null
        && logoutConfirmationInProgressRef.current === previousRequestId
      const queuedReplacementLoginClear =
        previousRequestId !== null
        && pendingLoginRequestId === previousRequestId
      const matchingResolvedClear =
        previousRequestId !== null
        && observedSnapshot.status === 'clear'
        && changeContext?.resolvedRequestId === previousRequestId
      const controlledLocalClear =
        wasBlocked
        && observedSnapshot.status === 'clear'
        && (
          loginCommitInProgressRef.current
          || crossTabLoginCommitInProgressRef.current
          || confirmationClear
          || queuedReplacementLoginClear
          || matchingResolvedClear
        )
      const shouldRetainRuntimeFence =
        wasBlocked
        && observedSnapshot.status === 'clear'
        && !loginCommitInProgressRef.current
        && !crossTabLoginCommitInProgressRef.current
        && !confirmationClear
        && !matchingResolvedClear
      let nextSnapshot = observedSnapshot
      if (shouldRetainRuntimeFence) {
        nextSnapshot = logoutPendingStore.retainRuntimeFence(
          previousRequestId ?? createLogoutRequestId(),
        )
      }
      const nextRequestId = logoutPendingRequestId(nextSnapshot)
      const transitionedToDifferentPendingState =
        isLogoutPendingBlocked(nextSnapshot)
        && (
          !wasBlocked
          || previousRequestId !== nextRequestId
        )
      const uncontrolledClear =
        wasBlocked
        && observedSnapshot.status === 'clear'
        && !controlledLocalClear
      previousSnapshot = nextSnapshot
      const retrySnapshot = logoutRetryCoordinatorRef.current?.getSnapshot()

      if (uncontrolledClear) {
        nextAuthRequestGeneration()
        if (retrySnapshot?.requestId) {
          logoutRetryCoordinatorRef.current?.cancel(
            retrySnapshot.requestId,
            'stale',
          )
        }
      }
      if (isLogoutPendingBlocked(nextSnapshot)) {
        if (transitionedToDifferentPendingState) {
          nextAuthRequestGeneration()
        }
        if (
          retrySnapshot?.requestId
          && retrySnapshot.requestId !== nextRequestId
        ) {
          logoutRetryCoordinatorRef.current?.cancel(
            retrySnapshot.requestId,
            'stale',
          )
        }
        setLogoutStatus('pending')
        if (
          !retrySnapshot
          || retrySnapshot.requestId !== nextRequestId
        ) {
          setLogoutRetryState(emptyLogoutRetrySnapshot(nextSnapshot))
        }
        clearLocalAuthState()
        return
      }

      if (!wasBlocked) {
        return
      }
      if (matchingResolvedClear) {
        const locallyControlledResolution =
          confirmationClear
          || loginCommitInProgressRef.current
          || crossTabLoginCommitInProgressRef.current
          || queuedReplacementLoginClear
        if (!locallyControlledResolution) {
          nextAuthRequestGeneration()
          if (retrySnapshot?.requestId === previousRequestId) {
            logoutRetryCoordinatorRef.current?.cancel(
              previousRequestId,
              'stale',
            )
          }
        }
        setLogoutStatus(
          changeContext.resolution === 'confirmed' ? 'confirmed' : 'none',
        )
        setLogoutRetryState(emptyLogoutRetrySnapshot({ status: 'clear' }))
        if (
          changeContext.resolution === 'replacement-login'
          && !locallyControlledResolution
        ) {
          queueMicrotask(() => {
            if (active && logoutPendingStore.read().status === 'clear') {
              void hydrateSession()
            }
          })
        }
        return
      }
      if (!controlledLocalClear && !uncontrolledClear) {
        nextAuthRequestGeneration()
        if (retrySnapshot?.requestId) {
          logoutRetryCoordinatorRef.current?.cancel(
            retrySnapshot.requestId,
            'stale',
          )
        }
      }
      if (readStoredAuthSession()) {
        setLogoutStatus('none')
        setLogoutRetryState(emptyLogoutRetrySnapshot(nextSnapshot))
        return
      }
      if (controlledLocalClear) {
        return
      }
      setLogoutStatus('pending')
      setLogoutRetryState({
        ...emptyLogoutRetrySnapshot(nextSnapshot),
        status: 'unconfirmed',
        requestId: previousRequestId ?? retrySnapshot?.requestId ?? null,
        retryCount: retrySnapshot?.retryCount ?? 0,
        reason: 'no-proof',
      })
    })
    return () => {
      active = false
      unsubscribe()
    }
  }, [clearLocalAuthState, hydrateSession, nextAuthRequestGeneration])

  useEffect(() => {
    const revalidation = createAuthSessionRevalidationCoordinator(
      hydrateSession,
      () =>
        !initialAuthHydrationPendingRef.current
        && (
          Boolean(readStoredAuthSession())
          || !authSessionKnownAbsentRef.current
        ),
    )
    const onFocus = () => revalidation.request(false)
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        revalidation.request(false)
      }
    }
    const onCrossTabSessionEstablished = (event: Event) => {
      const clearedLogoutRequestId =
        readAuthSessionEstablishedLogoutRequestId(event)
      if (!clearedLogoutRequestId) {
        return
      }
      const loginAttemptActive = loginAttemptRef.current !== null
      crossTabLoginCommitInProgressRef.current = true
      try {
        const released = logoutPendingStore.releaseRuntimeFenceAfterLogin(
          clearedLogoutRequestId,
        )
        if (
          (released.status === 'applied' || released.status === 'unchanged')
          && logoutPendingStore.read().status === 'clear'
        ) {
          const retrySnapshot = logoutRetryCoordinatorRef.current?.getSnapshot()
          if (retrySnapshot?.requestId === clearedLogoutRequestId) {
            logoutRetryCoordinatorRef.current?.cancel(
              clearedLogoutRequestId,
              'stale',
            )
          }
          setLogoutStatus('none')
          setLogoutRetryState(emptyLogoutRetrySnapshot({ status: 'clear' }))
          if (loginAttemptActive) {
            deferredAuthRevalidationRef.current = true
            return
          }
          nextAuthRequestGeneration()
          revalidation.request(true)
        }
      } finally {
        crossTabLoginCommitInProgressRef.current = false
      }
    }
    const onCrossTabRevalidation = () => {
      if (loginAttemptRef.current) {
        deferredAuthRevalidationRef.current = true
        return
      }
      revalidation.request(true)
    }

    window.addEventListener('focus', onFocus)
    document.addEventListener('visibilitychange', onVisibilityChange)
    window.addEventListener(
      authSessionEstablishedEvent,
      onCrossTabSessionEstablished,
    )
    window.addEventListener(authSessionRevalidationEvent, onCrossTabRevalidation)
    return () => {
      window.removeEventListener('focus', onFocus)
      document.removeEventListener('visibilitychange', onVisibilityChange)
      window.removeEventListener(
        authSessionEstablishedEvent,
        onCrossTabSessionEstablished,
      )
      window.removeEventListener(authSessionRevalidationEvent, onCrossTabRevalidation)
      revalidation.dispose()
    }
  }, [hydrateSession, nextAuthRequestGeneration])

  const startLogoutRetry = useCallback((
    requestId: string,
    proof: PendingLogoutProof | null,
  ) => {
    logoutRetryCoordinatorRef.current?.dispose()
    const authGeneration = proof?.authGeneration ?? null
    const coordinator = createLogoutRetryCoordinator<PendingLogoutProof>({
      isCurrent: (candidateRequestId) =>
        candidateRequestId === requestId
        && authGeneration !== null
        && isCurrentAuthRequest(authGeneration),
      isOnline: () =>
        typeof navigator === 'undefined' || navigator.onLine !== false,
      classifyError: (error) => {
        const candidate = error as {
          isNetworkError?: unknown
          status?: unknown
        }
        return candidate?.isNetworkError === true
          || (
            typeof candidate?.status === 'number'
            && candidate.status >= 500
          )
          ? 'retryable'
          : 'unconfirmed'
      },
      attempt: async ({
        requestId: candidateRequestId,
        proof: attemptProof,
        retryCount,
        signal,
      }) => {
        try {
          return await logoutAuthSession(attemptProof, {
            signal,
            prepareDispatch: () => {
              const pendingSnapshot = logoutPendingStore.read()
              if (
                signal.aborted
                || logoutPendingRequestId(pendingSnapshot)
                  !== candidateRequestId
                || !isCurrentAuthRequest(attemptProof.authGeneration)
              ) {
                return false
              }
              if (pendingSnapshot.status === 'blocked') {
                return true
              }
              if (pendingSnapshot.status !== 'pending') {
                return false
              }
              const recorded = logoutPendingStore.recordRetry(
                candidateRequestId,
                retryCount,
              )
              if (
                recorded.status !== 'applied'
                && recorded.status !== 'unchanged'
              ) {
                return false
              }
              const verified = logoutPendingStore.read()
              return (
                !signal.aborted
                && verified.status === 'pending'
                && verified.tombstone.requestId === candidateRequestId
                && verified.tombstone.retryCount === retryCount
                && isCurrentAuthRequest(attemptProof.authGeneration)
              )
            },
            confirmRevocation: () => {
              if (
                signal.aborted
                || !isCurrentAuthRequest(attemptProof.authGeneration)
              ) {
                return false
              }
              logoutConfirmationInProgressRef.current = candidateRequestId
              logoutPendingStore.retainRuntimeFence(candidateRequestId)
              const cleared = logoutPendingStore.clearIfMatching(
                candidateRequestId,
              )
              if (cleared.status !== 'applied') {
                if (cleared.status === 'stale') {
                  logoutPendingStore.releaseRuntimeFenceIfMatching(
                    candidateRequestId,
                  )
                }
                logoutConfirmationInProgressRef.current = null
                return false
              }
              const released =
                logoutPendingStore.releaseRuntimeFenceIfMatching(
                  candidateRequestId,
                )
              return (
                released.status === 'applied'
                || released.status === 'unchanged'
              )
            },
          })
        } finally {
          if (
            logoutConfirmationInProgressRef.current === candidateRequestId
          ) {
            logoutConfirmationInProgressRef.current = null
          }
        }
      },
      onStateChange: (nextState) => {
        setLogoutRetryState(nextState)
        if (nextState.status !== 'confirmed' || !nextState.requestId) {
          return
        }
        if (
          !readStoredAuthSession()
        ) {
          setLogoutStatus('confirmed')
          return
        }
        setLogoutStatus('pending')
        setLogoutRetryState({
          ...nextState,
          status: 'unconfirmed',
          canRetry: false,
          reason: 'server-unconfirmed',
        })
      },
    })
    logoutRetryCoordinatorRef.current = coordinator
    coordinator.start({ requestId, proof })
  }, [isCurrentAuthRequest])

  const loginWithSession = useCallback(
    (nextSession: StoredAuthSession, generation: number) => {
      const loginAttempt = loginAttemptRef.current
      if (
        !isCurrentAuthRequest(generation)
        || !loginAttempt
        || loginAttempt.generation !== generation
      ) {
        return false
      }

      const clearedLogoutRequestId = logoutPendingRequestId(
        loginAttempt.pendingSnapshot,
      )
      loginCommitInProgressRef.current = true
      try {
        commitSession(nextSession)
        const cleared = logoutPendingStore.clearAfterSuccessfulLogin(
          loginAttempt.pendingSnapshot,
        )
        if (
          cleared.status === 'blocked'
          || cleared.status === 'stale'
          || isLogoutPendingBlocked(logoutPendingStore.read())
        ) {
          nextAuthRequestGeneration()
          clearLocalAuthState()
          replayDeferredAuthRevalidation()
          return false
        }
        announceAuthSessionEstablished(clearedLogoutRequestId)
        deferredAuthRevalidationRef.current = false
        setLogoutStatus('none')
        setLogoutRetryState(emptyLogoutRetrySnapshot({ status: 'clear' }))
        loginAttemptRef.current = null
        return true
      } finally {
        loginCommitInProgressRef.current = false
      }
    },
    [
      clearLocalAuthState,
      commitSession,
      isCurrentAuthRequest,
      nextAuthRequestGeneration,
      replayDeferredAuthRevalidation,
    ],
  )

  const logout = useCallback(async () => {
    const currentSession = readStoredAuthSession()
    const sessionFence = captureAuthSessionFence()
    const existingPendingSnapshot = logoutPendingStore.read()
    if (isLogoutPendingBlocked(existingPendingSnapshot)) {
      const existingRequestId =
        logoutPendingRequestId(existingPendingSnapshot)
      const activeRetry = logoutRetryCoordinatorRef.current?.getSnapshot()
      const activeRetryMatches =
        existingRequestId !== null
        && activeRetry?.requestId === existingRequestId
      if (currentSession) {
        nextAuthRequestGeneration()
        loginAttemptRef.current = null
      }
      setLogoutStatus('pending')
      if (!activeRetryMatches) {
        setLogoutRetryState(
          emptyLogoutRetrySnapshot(existingPendingSnapshot),
        )
      }
      clearLocalAuthState({
        broadcast: 'logout',
        sessionEpoch: sessionFence?.sessionEpoch,
      })
      return
    }
    const requestId = createLogoutRequestId()
    const pendingResult = logoutPendingStore.begin(requestId, Date.now())
    const generation = nextAuthRequestGeneration()
    loginAttemptRef.current = null
    setLogoutStatus('pending')
    clearLocalAuthState({
      broadcast: 'logout',
      sessionEpoch: sessionFence?.sessionEpoch,
    })
    if (
      logoutPendingRequestId(pendingResult.snapshot) !== requestId
      || (
        pendingResult.snapshot.status === 'pending'
        &&
        pendingResult.status !== 'applied'
        && pendingResult.status !== 'unchanged'
      )
    ) {
      setLogoutRetryState(emptyLogoutRetrySnapshot(pendingResult.snapshot))
      return
    }

    const proof = currentSession && sessionFence
      ? {
          csrfToken: currentSession.csrfToken,
          sessionEpoch: sessionFence.sessionEpoch,
          sessionRevision: sessionFence.revision,
          authGeneration: generation,
        }
      : null
    startLogoutRetry(requestId, proof)
  }, [
    clearLocalAuthState,
    nextAuthRequestGeneration,
    startLogoutRetry,
  ])

  const retryLogout = useCallback(() => {
    const pendingSnapshot = logoutPendingStore.read()
    const pendingRequestId = logoutPendingRequestId(pendingSnapshot)
    if (!pendingRequestId) {
      return false
    }
    return logoutRetryCoordinatorRef.current?.requestExplicitRetry(
      pendingRequestId,
    ) ?? false
  }, [])

  useEffect(() => {
    const onOnline = () => {
      const pendingSnapshot = logoutPendingStore.read()
      const pendingRequestId = logoutPendingRequestId(pendingSnapshot)
      if (pendingRequestId) {
        logoutRetryCoordinatorRef.current?.notifyOnline(
          pendingRequestId,
        )
      }
    }
    window.addEventListener('online', onOnline)
    return () => {
      window.removeEventListener('online', onOnline)
      logoutRetryCoordinatorRef.current?.dispose()
      logoutRetryCoordinatorRef.current = null
    }
  }, [])

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
    logoutStatus,
    isLogoutRetrying: logoutRetryState.inFlight,
    canRetryLogout: logoutRetryState.canRetry,
    logoutRetryCount: logoutRetryState.retryCount,
    logoutRetryReason: logoutRetryState.reason,
    staffActorNameRequired,
    hydrateSession,
    beginLoginAttempt,
    isAuthRequestCurrent: isCurrentAuthRequest,
    clearCurrentAuthRequest,
    loginWithSession,
    updateStaffActorName,
    logout,
    retryLogout,
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
    logoutRetryState,
    logoutStatus,
    retryLogout,
    session,
    staffActorNameRequired,
    updateStaffActorName,
  ])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
