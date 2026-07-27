import type { AuthIdentity, StoredAuthSession } from '../types/auth'

const AUTH_SESSION_CHANGED_EVENT = 'mata-auth-session-change'
const AUTH_SESSION_REVALIDATION_EVENT = 'mata-auth-session-revalidation'
const AUTH_SESSION_CHANNEL_NAME = 'mata-auth-session-lifecycle'
let memoryAuthSession: StoredAuthSession | null = null
let memoryAuthSessionRevision = 0
let memoryAuthSessionEpoch: string | null = null

export type AuthSessionLossReason = 'logout' | 'unauthorized'

export type AuthSessionFence = {
  revision: number
  subjectId: string
  role: StoredAuthSession['identity']['role']
  sessionEpoch: string | null
}

export type ClearAuthSessionOptions = {
  broadcast?: AuthSessionLossReason
  sessionEpoch?: string | null
}

export type AuthSessionRevalidationCoordinator = {
  request: (force: boolean) => void
  dispose: () => void
}

type AuthSessionChannelMessage =
  | {
      type: 'session-cleared'
      reason: AuthSessionLossReason
      sessionEpoch: string | null
    }
  | {
      type: 'session-established'
      sessionEpoch: string
    }
  | {
      type: 'session-rotated'
      sessionEpoch: string
    }

const isBrowser = () => typeof window !== 'undefined'

const notifySessionChanged = () => {
  if (isBrowser()) {
    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT))
  }
}

const notifySessionRevalidationRequired = () => {
  if (isBrowser()) {
    window.dispatchEvent(new Event(AUTH_SESSION_REVALIDATION_EVENT))
  }
}

const isAuthSessionLossReason = (value: unknown): value is AuthSessionLossReason =>
  value === 'logout' || value === 'unauthorized'

const parseAuthSessionChannelMessage = (value: unknown): AuthSessionChannelMessage | null => {
  if (!value || typeof value !== 'object') {
    return null
  }
  const candidate = value as Record<string, unknown>
  if (
    candidate.type === 'session-cleared'
    && isAuthSessionLossReason(candidate.reason)
    && (typeof candidate.sessionEpoch === 'string' || candidate.sessionEpoch === null)
  ) {
    return {
      type: candidate.type,
      reason: candidate.reason,
      sessionEpoch: candidate.sessionEpoch,
    }
  }
  if (
    (candidate.type === 'session-established' || candidate.type === 'session-rotated')
    && typeof candidate.sessionEpoch === 'string'
    && candidate.sessionEpoch.length > 0
  ) {
    return {
      type: candidate.type,
      sessionEpoch: candidate.sessionEpoch,
    }
  }
  return null
}

const createSessionEpoch = (): string => {
  const currentTimestamp = Number(memoryAuthSessionEpoch?.split('-', 1)[0])
  const timestamp = Math.max(
    Date.now(),
    Number.isFinite(currentTimestamp) ? currentTimestamp + 1 : 0,
  )
  const entropy = typeof globalThis.crypto?.randomUUID === 'function'
    ? globalThis.crypto.randomUUID()
    : Math.random().toString(16).slice(2)
  return `${timestamp}-${entropy}`
}

const stableAuthValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map(stableAuthValue)
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, stableAuthValue(item)]),
    )
  }
  return value
}

const authSessionFingerprint = (session: StoredAuthSession): string => {
  const identity = session.identity.role === 'master_admin'
    || session.identity.role === 'programme_pc'
    ? {
        ...session.identity,
        programmeScope: [...session.identity.programmeScope].sort(),
      }
    : session.identity
  return JSON.stringify(stableAuthValue({
    identity,
    csrfToken: session.csrfToken,
    sessionRefreshRequired: session.sessionRefreshRequired === true,
  }))
}

const writeAuthSession = (session: StoredAuthSession | null) => {
  memoryAuthSession = session
  memoryAuthSessionRevision += 1
  notifySessionChanged()
}

export const shouldAcceptCrossTabSessionLoss = (
  currentSessionEpoch: string | null,
  incomingSessionEpoch: string | null,
): boolean =>
  currentSessionEpoch === null || currentSessionEpoch === incomingSessionEpoch

export const shouldAcceptCrossTabSessionEstablished = (
  currentSessionEpoch: string | null,
  incomingSessionEpoch: string,
): boolean => {
  if (currentSessionEpoch === null) {
    return true
  }
  const currentTimestamp = Number(currentSessionEpoch.split('-', 1)[0])
  const incomingTimestamp = Number(incomingSessionEpoch.split('-', 1)[0])
  if (
    Number.isFinite(currentTimestamp)
    && Number.isFinite(incomingTimestamp)
    && currentTimestamp !== incomingTimestamp
  ) {
    return incomingTimestamp > currentTimestamp
  }
  return incomingSessionEpoch.localeCompare(currentSessionEpoch) > 0
}

export const shouldAcceptCrossTabSessionRotation = (
  currentSessionEpoch: string | null,
  incomingSessionEpoch: string,
): boolean =>
  currentSessionEpoch !== null && currentSessionEpoch === incomingSessionEpoch

export const createAuthSessionRevalidationCoordinator = (
  revalidateSession: () => Promise<void>,
  hasStoredSession: () => boolean,
): AuthSessionRevalidationCoordinator => {
  let active = true
  let revalidationInFlight = false
  let forcedRevalidationQueued = false

  const request = (force: boolean) => {
    if (!active) {
      return
    }
    if (revalidationInFlight) {
      forcedRevalidationQueued ||= force
      return
    }
    if (!force && !hasStoredSession()) {
      return
    }

    revalidationInFlight = true
    void revalidateSession().finally(() => {
      revalidationInFlight = false
      if (!active || !forcedRevalidationQueued) {
        return
      }
      forcedRevalidationQueued = false
      request(true)
    })
  }

  return {
    request,
    dispose: () => {
      active = false
      forcedRevalidationQueued = false
    },
  }
}

const authSessionChannel = (() => {
  if (!isBrowser() || typeof BroadcastChannel === 'undefined') {
    return null
  }
  try {
    const channel = new BroadcastChannel(AUTH_SESSION_CHANNEL_NAME)
    channel.addEventListener('message', (event: MessageEvent<unknown>) => {
      const message = parseAuthSessionChannelMessage(event.data)
      if (!message) {
        return
      }
      if (message.type === 'session-established') {
        if (!shouldAcceptCrossTabSessionEstablished(
          memoryAuthSessionEpoch,
          message.sessionEpoch,
        )) {
          return
        }
        memoryAuthSessionEpoch = message.sessionEpoch
        writeAuthSession(null)
        notifySessionRevalidationRequired()
        return
      }
      if (message.type === 'session-rotated') {
        if (!shouldAcceptCrossTabSessionRotation(
          memoryAuthSessionEpoch,
          message.sessionEpoch,
        )) {
          return
        }
        if (memoryAuthSession) {
          writeAuthSession(null)
        }
        notifySessionRevalidationRequired()
        return
      }
      if (!shouldAcceptCrossTabSessionLoss(memoryAuthSessionEpoch, message.sessionEpoch)) {
        return
      }
      memoryAuthSessionEpoch = message.sessionEpoch
      writeAuthSession(null)
    })
    return channel
  } catch {
    return null
  }
})()

const broadcastAuthSessionMessage = (message: AuthSessionChannelMessage) => {
  try {
    authSessionChannel?.postMessage(message)
  } catch {
    // Cross-tab synchronization is best effort; server authorization stays authoritative.
  }
}

export const authSessionChangedEvent = AUTH_SESSION_CHANGED_EVENT
export const authSessionRevalidationEvent = AUTH_SESSION_REVALIDATION_EVENT

export const readStoredAuthSession = (): StoredAuthSession | null => memoryAuthSession
export const readAuthSessionRevision = (): number => memoryAuthSessionRevision
export const readAuthSessionEpoch = (): string | null => memoryAuthSessionEpoch

export const captureAuthSessionFence = (): AuthSessionFence | null => {
  if (!memoryAuthSession) {
    return null
  }
  return {
    revision: memoryAuthSessionRevision,
    subjectId: memoryAuthSession.identity.subjectId,
    role: memoryAuthSession.identity.role,
    sessionEpoch: memoryAuthSessionEpoch,
  }
}

export const isAuthSessionFenceCurrent = (fence: AuthSessionFence): boolean => {
  const currentSession = memoryAuthSession
  return Boolean(currentSession)
    && fence.revision === memoryAuthSessionRevision
    && fence.subjectId === currentSession?.identity.subjectId
    && fence.role === currentSession?.identity.role
    && fence.sessionEpoch === memoryAuthSessionEpoch
}

export const isAuthSessionUpdateCompletionCurrent = (
  fence: AuthSessionFence,
  updatedIdentity: AuthIdentity,
): boolean => {
  const currentSession = memoryAuthSession
  return Boolean(currentSession)
    && memoryAuthSessionRevision === fence.revision + 1
    && fence.subjectId === currentSession?.identity.subjectId
    && fence.role === currentSession?.identity.role
    && fence.sessionEpoch === memoryAuthSessionEpoch
    && currentSession?.identity === updatedIdentity
}

export const announceAuthSessionEstablished = (): string => {
  const sessionEpoch = createSessionEpoch()
  memoryAuthSessionEpoch = sessionEpoch
  broadcastAuthSessionMessage({
    type: 'session-established',
    sessionEpoch,
  })
  return sessionEpoch
}

export const announceAuthSessionRotated = (): boolean => {
  if (memoryAuthSessionEpoch === null) {
    return false
  }
  broadcastAuthSessionMessage({
    type: 'session-rotated',
    sessionEpoch: memoryAuthSessionEpoch,
  })
  return true
}

export const saveAuthSession = (session: StoredAuthSession) => {
  writeAuthSession(session)
}

export const saveHydratedAuthSession = (session: StoredAuthSession): boolean => {
  if (
    memoryAuthSession
    && authSessionFingerprint(memoryAuthSession) === authSessionFingerprint(session)
  ) {
    return false
  }
  writeAuthSession(session)
  return true
}

export const clearAuthSession = (options: ClearAuthSessionOptions = {}) => {
  const sessionEpoch =
    options.sessionEpoch === undefined ? memoryAuthSessionEpoch : options.sessionEpoch
  writeAuthSession(null)
  if (options.broadcast) {
    broadcastAuthSessionMessage({
      type: 'session-cleared',
      reason: options.broadcast,
      sessionEpoch,
    })
  }
}

export const clearAuthSessionIfPresent = (
  options: ClearAuthSessionOptions = {},
): boolean => {
  if (!memoryAuthSession) {
    return false
  }
  clearAuthSession(options)
  return true
}
