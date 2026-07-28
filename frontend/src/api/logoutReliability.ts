export const LOGOUT_PENDING_STORAGE_KEY = 'mata.logout.pending.v1'
export const LOGOUT_RESOLUTION_STORAGE_KEY = 'mata.logout.resolution.v1'
export const LOGOUT_PENDING_CHANGED_EVENT = 'mata-logout-pending-change'
export const LOGOUT_PENDING_CHANNEL_NAME = 'mata-logout-pending-lifecycle'
export const LOGOUT_PENDING_MAX_SERIALIZED_BYTES = 512
export const LOGOUT_RESOLUTION_MAX_SERIALIZED_BYTES = 512
export const LOGOUT_MAX_TOTAL_ATTEMPTS = 4
export const LOGOUT_RETRY_DELAYS_MS = [1_000, 2_000, 4_000] as const

const LOGOUT_PENDING_STORAGE_PROBE_KEY_PREFIX = 'mata.logout.storage-probe.v1'
const LOGOUT_PENDING_HISTORY_STATE_KEY = '__mataLogoutPendingStorageV1'
const LOGOUT_PENDING_WINDOW_NAME_PREFIX = 'mata.logout.storage.v1:'
const LOGOUT_PENDING_WINDOW_NAME_MAX_BYTES = 2_048
const LOGOUT_PENDING_STORAGE_PROBE_VALUE =
  '.'.repeat(LOGOUT_PENDING_MAX_SERIALIZED_BYTES)

export type LogoutPendingTombstone = Readonly<{
  version: 1
  requestId: string
  initiatedAt: number
  retryCount: number
}>

export type LogoutPendingResolution = 'confirmed' | 'replacement-login'

export type LogoutResolutionWatermark = Readonly<{
  version: 1
  requestId: string
  initiatedAt: number
  resolvedAt: number
  resolution: LogoutPendingResolution
}>

export type LogoutPendingBlockedReason =
  | 'malformed'
  | 'oversized'
  | 'storage-unavailable'
  | 'storage-read-failed'
  | 'storage-write-failed'
  | 'unconfirmed-clear'

export type LogoutPendingSnapshot =
  | { status: 'clear' }
  | { status: 'pending'; tombstone: LogoutPendingTombstone }
  | { status: 'blocked'; reason: LogoutPendingBlockedReason }

export type LogoutPendingStorage = Pick<
  Storage,
  'getItem' | 'setItem' | 'removeItem'
>

export type LogoutPendingMutationResult =
  | { status: 'applied'; snapshot: LogoutPendingSnapshot }
  | { status: 'unchanged'; snapshot: LogoutPendingSnapshot }
  | { status: 'stale'; snapshot: LogoutPendingSnapshot }
  | { status: 'blocked'; snapshot: LogoutPendingSnapshot }

export type LogoutPendingChangeContext = Readonly<{
  resolvedRequestId: string
  resolution: LogoutPendingResolution
}>

type LogoutPendingEventTarget = Pick<
  Window,
  'addEventListener' | 'removeEventListener' | 'dispatchEvent'
>

type LogoutPendingChannel = {
  postMessage: (message: unknown) => void
  addEventListener: (
    type: 'message',
    listener: (event: MessageEvent<unknown>) => void,
  ) => void
  removeEventListener: (
    type: 'message',
    listener: (event: MessageEvent<unknown>) => void,
  ) => void
  close: () => void
}

type LogoutPendingChannelMessage =
  | { type: 'logout-pending-changed' }
  | {
      type: 'logout-pending-state'
      tombstone: LogoutPendingTombstone
    }
  | {
      type: 'logout-pending-blocked'
      requestId: string
      initiatedAt?: number
    }
  | {
      type: 'logout-pending-resolved'
      watermark: LogoutResolutionWatermark
    }
  | { type: 'logout-pending-sync-request' }

export type LogoutPendingStore = {
  read: () => LogoutPendingSnapshot
  refresh: () => LogoutPendingSnapshot
  subscribe: (
    listener: (
      snapshot: LogoutPendingSnapshot,
      context?: LogoutPendingChangeContext,
    ) => void,
  ) => () => void
  begin: (requestId: string, initiatedAt: number) => LogoutPendingMutationResult
  recordRetry: (requestId: string, retryCount: number) => LogoutPendingMutationResult
  clearIfMatching: (requestId: string) => LogoutPendingMutationResult
  retainRuntimeFence: (requestId: string) => LogoutPendingSnapshot
  releaseRuntimeFenceIfMatching: (
    requestId: string,
  ) => LogoutPendingMutationResult
  releaseRuntimeFenceAfterLogin: (
    requestId: string,
  ) => LogoutPendingMutationResult
  clearAfterSuccessfulLogin: (
    capturedSnapshot: LogoutPendingSnapshot,
  ) => LogoutPendingMutationResult
  dispose: () => void
}

type LogoutPendingStoreOptions = {
  storage?: LogoutPendingStorage | null
  eventTarget?: LogoutPendingEventTarget | null
  channelFactory?: ((name: string) => LogoutPendingChannel) | null
}

const blockedRawValues = new WeakMap<object, string>()
const blockedResolutionRawValues = new WeakMap<object, string>()
const blockedResolutionPendingRawValues =
  new WeakMap<object, string | null>()
const blockedRequestIds = new WeakMap<object, string>()
const storageFailureLatches = new WeakMap<object, LogoutPendingBlockedReason>()
const storageFailureRequestIds = new WeakMap<object, string>()
const runtimeUnconfirmedClearFences = new WeakMap<object, string>()
const verifiedWritableStorage = new WeakSet<object>()
const exactTombstoneKeys = ['initiatedAt', 'requestId', 'retryCount', 'version']
const exactResolutionWatermarkKeys = [
  'initiatedAt',
  'requestId',
  'resolution',
  'resolvedAt',
  'version',
]
const requestIdPattern = /^[A-Za-z0-9._:-]{1,128}$/
const maximumDateMilliseconds = 8_640_000_000_000_000
const storageProbeInstanceId = (() => {
  try {
    if (typeof globalThis.crypto?.randomUUID === 'function') {
      return globalThis.crypto.randomUUID()
    }
  } catch {
    // Fall through to non-sensitive local entropy.
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
})()
let storageProbeSequence = 0

const encodedBytes = (value: string): number => new TextEncoder().encode(value).byteLength

const blockedSnapshot = (
  reason: LogoutPendingBlockedReason,
  rawValue?: string,
  requestId?: string,
): LogoutPendingSnapshot => {
  const snapshot: LogoutPendingSnapshot = { status: 'blocked', reason }
  if (rawValue !== undefined) {
    blockedRawValues.set(snapshot, rawValue)
  }
  if (requestId !== undefined) {
    blockedRequestIds.set(snapshot, requestId)
  }
  return snapshot
}

const latchStorageFailure = (
  storage: LogoutPendingStorage,
  reason: LogoutPendingBlockedReason,
  requestId?: string,
): LogoutPendingSnapshot => {
  const storageIdentity = storage as object
  storageFailureLatches.set(storageIdentity, reason)
  if (requestId) {
    storageFailureRequestIds.set(storageIdentity, requestId)
    runtimeUnconfirmedClearFences.set(storageIdentity, requestId)
  }
  verifiedWritableStorage.delete(storageIdentity)
  return blockedSnapshot(
    reason,
    undefined,
    requestId
      ?? storageFailureRequestIds.get(storageIdentity)
      ?? runtimeUnconfirmedClearFences.get(storageIdentity),
  )
}

const createStorageProbeKey = (): string => {
  storageProbeSequence += 1
  return `${LOGOUT_PENDING_STORAGE_PROBE_KEY_PREFIX}.${storageProbeInstanceId}.${storageProbeSequence}`
}

const parseFallbackStorageValues = (
  value: unknown,
): Record<string, string> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Logout fallback storage is malformed.')
  }
  const entries = Object.entries(value as Record<string, unknown>)
  if (
    entries.length > 8
    || entries.some(([key, item]) =>
      key.length === 0
      || key.length > 256
      || typeof item !== 'string'
      || encodedBytes(item) > LOGOUT_PENDING_MAX_SERIALIZED_BYTES)
  ) {
    throw new Error('Logout fallback storage is malformed.')
  }
  return Object.fromEntries(entries) as Record<string, string>
}

const readHistoryStorageValues = (): Record<string, string> => {
  const state = window.history.state
  if (!state || typeof state !== 'object' || Array.isArray(state)) {
    return {}
  }
  const candidate = (state as Record<string, unknown>)[
    LOGOUT_PENDING_HISTORY_STATE_KEY
  ]
  if (candidate === undefined) {
    return {}
  }
  return parseFallbackStorageValues(candidate)
}

const replaceHistoryStorageValues = (values: Record<string, string>): void => {
  const state = window.history.state
  const currentState =
    state && typeof state === 'object' && !Array.isArray(state)
      ? state as Record<string, unknown>
      : {}
  const nextState = { ...currentState }
  if (Object.keys(values).length > 0) {
    nextState[LOGOUT_PENDING_HISTORY_STATE_KEY] = values
  } else {
    delete nextState[LOGOUT_PENDING_HISTORY_STATE_KEY]
  }
  window.history.replaceState(nextState, '')
}

const readWindowNameStorageValues = (): Record<string, string> => {
  const value = typeof window.name === 'string' ? window.name : ''
  if (!value.startsWith(LOGOUT_PENDING_WINDOW_NAME_PREFIX)) {
    return {}
  }
  if (encodedBytes(value) > LOGOUT_PENDING_WINDOW_NAME_MAX_BYTES) {
    throw new Error('Logout window-name storage is oversized.')
  }
  const parsed = JSON.parse(
    value.slice(LOGOUT_PENDING_WINDOW_NAME_PREFIX.length),
  ) as unknown
  return parseFallbackStorageValues(parsed)
}

const replaceWindowNameStorageValues = (
  values: Record<string, string>,
): void => {
  window.name = Object.keys(values).length > 0
    ? `${LOGOUT_PENDING_WINDOW_NAME_PREFIX}${JSON.stringify(values)}`
    : ''
}

const bestEffortRemoveStorageProbe = (
  storage: LogoutPendingStorage,
  probeKey: string,
): void => {
  try {
    storage.removeItem(probeKey)
  } catch {
    // The fail-closed latch remains authoritative.
  }
}

const verifyStorageWritable = (
  storage: LogoutPendingStorage,
  force = false,
): LogoutPendingSnapshot | null => {
  const storageIdentity = storage as object
  const latchedReason = storageFailureLatches.get(storageIdentity)
  if (!force && latchedReason) {
    return blockedSnapshot(
      latchedReason,
      undefined,
      storageFailureRequestIds.get(storageIdentity)
        ?? runtimeUnconfirmedClearFences.get(storageIdentity),
    )
  }
  if (!force && verifiedWritableStorage.has(storageIdentity)) {
    return null
  }
  const probeKey = createStorageProbeKey()

  try {
    storage.setItem(
      probeKey,
      LOGOUT_PENDING_STORAGE_PROBE_VALUE,
    )
  } catch {
    return latchStorageFailure(storage, 'storage-write-failed')
  }

  let writtenProbe: string | null
  try {
    writtenProbe = storage.getItem(probeKey)
  } catch {
    bestEffortRemoveStorageProbe(storage, probeKey)
    return latchStorageFailure(storage, 'storage-read-failed')
  }
  if (writtenProbe !== LOGOUT_PENDING_STORAGE_PROBE_VALUE) {
    bestEffortRemoveStorageProbe(storage, probeKey)
    return latchStorageFailure(storage, 'storage-write-failed')
  }

  try {
    storage.removeItem(probeKey)
  } catch {
    return latchStorageFailure(storage, 'storage-write-failed')
  }

  try {
    if (storage.getItem(probeKey) !== null) {
      return latchStorageFailure(storage, 'storage-write-failed')
    }
  } catch {
    return latchStorageFailure(storage, 'storage-read-failed')
  }

  storageFailureLatches.delete(storageIdentity)
  verifiedWritableStorage.add(storageIdentity)
  return null
}

const browserLogoutPendingStorage: LogoutPendingStorage = {
  getItem: (key) => {
    const values: string[] = []
    let lastError: unknown
    try {
      const primaryValue = window.localStorage.getItem(key)
      if (primaryValue !== null) {
        values.push(primaryValue)
      }
    } catch (error) {
      lastError = error
    }
    try {
      const fallbackValue = window.sessionStorage.getItem(key)
      if (fallbackValue !== null) {
        values.push(fallbackValue)
      }
    } catch (error) {
      lastError = error
    }
    try {
      const historyValue = readHistoryStorageValues()[key]
      if (historyValue !== undefined) {
        values.push(historyValue)
      }
    } catch (error) {
      lastError = error
    }
    try {
      const windowNameValue = readWindowNameStorageValues()[key]
      if (windowNameValue !== undefined) {
        values.push(windowNameValue)
      }
    } catch (error) {
      lastError = error
    }
    if (values.length === 0 && lastError) {
      throw lastError
    }
    if (values.length === 0) {
      return null
    }
    if (key === LOGOUT_PENDING_STORAGE_KEY) {
      const candidates = values
        .map(parseLogoutPendingTombstone)
        .filter((value): value is LogoutPendingTombstone => value !== null)
      if (candidates.length > 0) {
        const elected = electPendingTombstones(candidates)
        if (!elected) {
          throw new Error('Conflicting logout request markers.')
        }
        return JSON.stringify(elected)
      }
    }
    if (key === LOGOUT_RESOLUTION_STORAGE_KEY) {
      const candidates = values
        .map(parseLogoutResolutionWatermark)
        .filter((value): value is LogoutResolutionWatermark => value !== null)
      if (candidates.length > 0) {
        const elected = electResolutionWatermarks(candidates)
        if (!elected) {
          throw new Error('Conflicting logout resolution watermarks.')
        }
        return JSON.stringify(elected)
      }
    }
    return values[0] ?? null
  },
  setItem: (key, value) => {
    let writeSucceeded = false
    let webStorageSucceeded = false
    let lastError: unknown
    try {
      window.localStorage.setItem(key, value)
      writeSucceeded = true
      webStorageSucceeded = true
    } catch (error) {
      lastError = error
    }
    try {
      window.sessionStorage.setItem(key, value)
      writeSucceeded = true
      webStorageSucceeded = true
    } catch (error) {
      lastError = error
    }
    const historyValues = (() => {
      try {
        return readHistoryStorageValues()
      } catch (error) {
        lastError = error
        return null
      }
    })()
    if (
      historyValues
      && (!webStorageSucceeded || Object.keys(historyValues).length > 0)
    ) {
      try {
        replaceHistoryStorageValues({
          ...historyValues,
          [key]: value,
        })
        writeSucceeded = true
      } catch (error) {
        lastError = error
      }
    }
    const windowNameHasLogoutState =
      typeof window.name === 'string'
      && window.name.startsWith(LOGOUT_PENDING_WINDOW_NAME_PREFIX)
    if (!webStorageSucceeded || windowNameHasLogoutState) {
      try {
        replaceWindowNameStorageValues({
          ...readWindowNameStorageValues(),
          [key]: value,
        })
        writeSucceeded = true
      } catch (error) {
        lastError = error
      }
    }
    if (!writeSucceeded) {
      throw lastError
    }
  },
  removeItem: (key) => {
    let removalFailed = false
    let lastError: unknown
    try {
      window.localStorage.removeItem(key)
    } catch (error) {
      removalFailed = true
      lastError = error
    }
    try {
      window.sessionStorage.removeItem(key)
    } catch (error) {
      removalFailed = true
      lastError = error
    }
    try {
      const historyValues = readHistoryStorageValues()
      if (Object.hasOwn(historyValues, key)) {
        delete historyValues[key]
        replaceHistoryStorageValues(historyValues)
      }
    } catch (error) {
      removalFailed = true
      lastError = error
    }
    if (
      typeof window.name === 'string'
      && window.name.startsWith(LOGOUT_PENDING_WINDOW_NAME_PREFIX)
    ) {
      try {
        const windowNameValues = readWindowNameStorageValues()
        delete windowNameValues[key]
        replaceWindowNameStorageValues(windowNameValues)
      } catch (error) {
        removalFailed = true
        lastError = error
      }
    }
    if (removalFailed) {
      throw lastError
    }
  },
}

const resolveBrowserStorage = (): {
  storage: LogoutPendingStorage | null
  unavailable: boolean
} => {
  if (typeof window === 'undefined') {
    return { storage: null, unavailable: false }
  }
  return { storage: browserLogoutPendingStorage, unavailable: false }
}

const resolveStorage = (
  configuredStorage: LogoutPendingStorage | null | undefined,
): {
  storage: LogoutPendingStorage | null
  unavailable: boolean
} => {
  if (configuredStorage === null) {
    return { storage: null, unavailable: true }
  }
  if (configuredStorage !== undefined) {
    return { storage: configuredStorage, unavailable: false }
  }
  return resolveBrowserStorage()
}

export const parseLogoutPendingTombstone = (
  serialized: string,
): LogoutPendingTombstone | null => {
  if (
    serialized.length === 0
    || encodedBytes(serialized) > LOGOUT_PENDING_MAX_SERIALIZED_BYTES
  ) {
    return null
  }
  let value: unknown
  try {
    value = JSON.parse(serialized)
  } catch {
    return null
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const candidate = value as Record<string, unknown>
  if (
    Object.keys(candidate).sort().join('|') !== exactTombstoneKeys.join('|')
    || candidate.version !== 1
    || typeof candidate.requestId !== 'string'
    || !requestIdPattern.test(candidate.requestId)
    || !Number.isSafeInteger(candidate.initiatedAt)
    || (candidate.initiatedAt as number) < 0
    || (candidate.initiatedAt as number) > maximumDateMilliseconds
    || !Number.isSafeInteger(candidate.retryCount)
    || (candidate.retryCount as number) < 0
    || (candidate.retryCount as number) > LOGOUT_MAX_TOTAL_ATTEMPTS
  ) {
    return null
  }
  return Object.freeze({
    version: 1,
    requestId: candidate.requestId,
    initiatedAt: candidate.initiatedAt as number,
    retryCount: candidate.retryCount as number,
  })
}

export const parseLogoutResolutionWatermark = (
  serialized: string,
): LogoutResolutionWatermark | null => {
  if (
    serialized.length === 0
    || encodedBytes(serialized) > LOGOUT_RESOLUTION_MAX_SERIALIZED_BYTES
  ) {
    return null
  }
  let value: unknown
  try {
    value = JSON.parse(serialized)
  } catch {
    return null
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }
  const candidate = value as Record<string, unknown>
  if (
    Object.keys(candidate).sort().join('|')
      !== exactResolutionWatermarkKeys.join('|')
    || candidate.version !== 1
    || typeof candidate.requestId !== 'string'
    || !requestIdPattern.test(candidate.requestId)
    || !Number.isSafeInteger(candidate.initiatedAt)
    || (candidate.initiatedAt as number) < 0
    || (candidate.initiatedAt as number) > maximumDateMilliseconds
    || !Number.isSafeInteger(candidate.resolvedAt)
    || (candidate.resolvedAt as number) < (candidate.initiatedAt as number)
    || (candidate.resolvedAt as number) > maximumDateMilliseconds
    || (
      candidate.resolution !== 'confirmed'
      && candidate.resolution !== 'replacement-login'
    )
  ) {
    return null
  }
  return Object.freeze({
    version: 1,
    requestId: candidate.requestId,
    initiatedAt: candidate.initiatedAt as number,
    resolvedAt: candidate.resolvedAt as number,
    resolution: candidate.resolution,
  })
}

const compareRequestIds = (left: string, right: string): number =>
  left < right ? -1 : left > right ? 1 : 0

const comparePendingTombstones = (
  left: LogoutPendingTombstone,
  right: LogoutPendingTombstone,
): number | null => {
  if (
    left.requestId === right.requestId
    && left.initiatedAt !== right.initiatedAt
  ) {
    return null
  }
  if (left.initiatedAt !== right.initiatedAt) {
    return left.initiatedAt < right.initiatedAt ? -1 : 1
  }
  const requestOrder = compareRequestIds(left.requestId, right.requestId)
  if (requestOrder !== 0) {
    return requestOrder
  }
  return left.retryCount - right.retryCount
}

const compareResolutionWatermarks = (
  left: LogoutResolutionWatermark,
  right: LogoutResolutionWatermark,
): number => {
  if (left.resolvedAt !== right.resolvedAt) {
    return left.resolvedAt < right.resolvedAt ? -1 : 1
  }
  return compareRequestIds(left.requestId, right.requestId)
}

const resolutionWatermarksMatch = (
  left: LogoutResolutionWatermark,
  right: LogoutResolutionWatermark,
): boolean =>
  left.version === right.version
  && left.requestId === right.requestId
  && left.initiatedAt === right.initiatedAt
  && left.resolvedAt === right.resolvedAt
  && left.resolution === right.resolution

const resolutionSupersedesTombstone = (
  watermark: LogoutResolutionWatermark,
  tombstone: LogoutPendingTombstone,
): boolean =>
  watermark.requestId === tombstone.requestId
    ? watermark.initiatedAt === tombstone.initiatedAt
    : tombstone.initiatedAt <= watermark.resolvedAt

const electPendingTombstones = (
  tombstones: readonly LogoutPendingTombstone[],
): LogoutPendingTombstone | null => {
  let winner: LogoutPendingTombstone | null = null
  for (const candidate of tombstones) {
    if (!winner) {
      winner = candidate
      continue
    }
    const order = comparePendingTombstones(winner, candidate)
    if (order === null) {
      return null
    }
    if (
      (
        winner.requestId === candidate.requestId
        && winner.initiatedAt === candidate.initiatedAt
        && candidate.retryCount > winner.retryCount
      )
      || (
        (
          winner.requestId !== candidate.requestId
          || winner.initiatedAt !== candidate.initiatedAt
        )
        && order > 0
      )
    ) {
      winner = candidate
    }
  }
  return winner
}

const electResolutionWatermarks = (
  watermarks: readonly LogoutResolutionWatermark[],
): LogoutResolutionWatermark | null => {
  let winner: LogoutResolutionWatermark | null = null
  for (const [index, candidate] of watermarks.entries()) {
    for (const existing of watermarks.slice(0, index)) {
      if (
        compareResolutionWatermarks(existing, candidate) === 0
        && !resolutionWatermarksMatch(existing, candidate)
      ) {
        return null
      }
    }
    if (!winner) {
      winner = candidate
      continue
    }
    const order = compareResolutionWatermarks(winner, candidate)
    if (order < 0) {
      winner = candidate
    }
  }
  return winner
}

export const createLogoutPendingTombstone = (
  requestId: string,
  initiatedAt: number,
): LogoutPendingTombstone => {
  const serialized = JSON.stringify({
    version: 1,
    requestId,
    initiatedAt,
    retryCount: 0,
  })
  const tombstone = parseLogoutPendingTombstone(serialized)
  if (!tombstone) {
    throw new Error('Invalid logout request marker.')
  }
  return tombstone
}

export const readLogoutPendingSnapshot = (
  configuredStorage?: LogoutPendingStorage | null,
): LogoutPendingSnapshot => {
  const resolved = resolveStorage(configuredStorage)
  if (!resolved.storage) {
    return resolved.unavailable
      ? blockedSnapshot('storage-unavailable')
      : { status: 'clear' }
  }
  let serialized: string | null
  let serializedResolution: string | null
  try {
    serialized = resolved.storage.getItem(LOGOUT_PENDING_STORAGE_KEY)
    serializedResolution = resolved.storage.getItem(
      LOGOUT_RESOLUTION_STORAGE_KEY,
    )
  } catch {
    return latchStorageFailure(resolved.storage, 'storage-read-failed')
  }
  const storageIdentity = resolved.storage as object
  const runtimeRequestId =
    runtimeUnconfirmedClearFences.get(storageIdentity)
  if (
    serializedResolution !== null
    && encodedBytes(serializedResolution)
      > LOGOUT_RESOLUTION_MAX_SERIALIZED_BYTES
  ) {
    const snapshot = blockedSnapshot(
      'oversized',
      undefined,
      runtimeRequestId,
    )
    blockedResolutionRawValues.set(snapshot, serializedResolution)
    blockedResolutionPendingRawValues.set(snapshot, serialized)
    return snapshot
  }
  const watermark = serializedResolution === null
    ? null
    : parseLogoutResolutionWatermark(serializedResolution)
  if (serializedResolution !== null && !watermark) {
    const snapshot = blockedSnapshot(
      'malformed',
      undefined,
      runtimeRequestId,
    )
    blockedResolutionRawValues.set(snapshot, serializedResolution)
    blockedResolutionPendingRawValues.set(snapshot, serialized)
    return snapshot
  }
  const releaseResolvedRuntimeFence = (
    resolvedRequestId: string,
  ): void => {
    if (
      runtimeUnconfirmedClearFences.get(storageIdentity) === resolvedRequestId
    ) {
      runtimeUnconfirmedClearFences.delete(storageIdentity)
    }
    if (storageFailureRequestIds.get(storageIdentity) === resolvedRequestId) {
      storageFailureRequestIds.delete(storageIdentity)
      storageFailureLatches.delete(storageIdentity)
    }
  }
  const removeSupersededMarker = (): void => {
    try {
      resolved.storage?.removeItem(LOGOUT_PENDING_STORAGE_KEY)
    } catch {
      // The durable watermark remains authoritative over a stale replica.
    }
  }
  const healBrowserResolutionReplicas = ():
    | LogoutPendingSnapshot
    | null => {
    if (
      !watermark
      || resolved.storage !== browserLogoutPendingStorage
    ) {
      return null
    }
    try {
      resolved.storage.setItem(
        LOGOUT_RESOLUTION_STORAGE_KEY,
        JSON.stringify(watermark),
      )
    } catch {
      return latchStorageFailure(
        resolved.storage,
        'storage-write-failed',
        runtimeRequestId,
      )
    }
    let verifiedRaw: string | null
    try {
      verifiedRaw = resolved.storage.getItem(LOGOUT_RESOLUTION_STORAGE_KEY)
    } catch {
      return latchStorageFailure(
        resolved.storage,
        'storage-read-failed',
        runtimeRequestId,
      )
    }
    const verified = verifiedRaw === null
      ? null
      : parseLogoutResolutionWatermark(verifiedRaw)
    if (!verified || !resolutionWatermarksMatch(verified, watermark)) {
      return latchStorageFailure(
        resolved.storage,
        'storage-write-failed',
        runtimeRequestId,
      )
    }
    return verifyStorageWritable(resolved.storage, true)
  }

  if (serialized === null) {
    const replicaFailure = healBrowserResolutionReplicas()
    if (replicaFailure) {
      return replicaFailure
    }
    if (watermark && runtimeRequestId === watermark.requestId) {
      releaseResolvedRuntimeFence(watermark.requestId)
      return { status: 'clear' }
    }
    const storageFailure = verifyStorageWritable(resolved.storage)
    if (storageFailure) {
      return storageFailure
    }
    return runtimeRequestId
      ? blockedSnapshot('unconfirmed-clear', undefined, runtimeRequestId)
      : { status: 'clear' }
  }
  if (encodedBytes(serialized) > LOGOUT_PENDING_MAX_SERIALIZED_BYTES) {
    if (watermark && runtimeRequestId === watermark.requestId) {
      removeSupersededMarker()
      releaseResolvedRuntimeFence(watermark.requestId)
      return { status: 'clear' }
    }
    return blockedSnapshot('oversized', serialized, runtimeRequestId)
  }
  const tombstone = parseLogoutPendingTombstone(serialized)
  if (!tombstone) {
    if (watermark && runtimeRequestId === watermark.requestId) {
      removeSupersededMarker()
      releaseResolvedRuntimeFence(watermark.requestId)
      return { status: 'clear' }
    }
    return blockedSnapshot('malformed', serialized, runtimeRequestId)
  }
  if (watermark && resolutionSupersedesTombstone(watermark, tombstone)) {
    removeSupersededMarker()
    releaseResolvedRuntimeFence(tombstone.requestId)
    return { status: 'clear' }
  }
  if (resolved.storage === browserLogoutPendingStorage) {
    try {
      if (watermark) {
        resolved.storage.setItem(
          LOGOUT_RESOLUTION_STORAGE_KEY,
          JSON.stringify(watermark),
        )
      }
      resolved.storage.setItem(
        LOGOUT_PENDING_STORAGE_KEY,
        JSON.stringify(tombstone),
      )
    } catch {
      return latchStorageFailure(
        resolved.storage,
        'storage-write-failed',
        tombstone.requestId,
      )
    }
  }
  runtimeUnconfirmedClearFences.set(
    storageIdentity,
    tombstone.requestId,
  )
  return { status: 'pending', tombstone }
}

export const isLogoutPendingBlocked = (
  snapshot: LogoutPendingSnapshot,
): boolean => snapshot.status !== 'clear'

export const logoutPendingRequestId = (
  snapshot: LogoutPendingSnapshot,
): string | null => {
  if (snapshot.status === 'pending') {
    return snapshot.tombstone.requestId
  }
  return snapshot.status === 'blocked'
    ? blockedRequestIds.get(snapshot) ?? null
    : null
}

const parseLogoutPendingChannelMessage = (
  value: unknown,
): LogoutPendingChannelMessage | null => {
  if (!value || typeof value !== 'object') {
    return null
  }
  const candidate = value as Record<string, unknown>
  if (
    (
      candidate.type === 'logout-pending-changed'
      || candidate.type === 'logout-pending-sync-request'
    )
    && Object.keys(candidate).length === 1
  ) {
    return { type: candidate.type }
  }
  const blockedMessageKeys = Object.keys(candidate).sort().join('|')
  if (
    candidate.type === 'logout-pending-blocked'
    && (
      blockedMessageKeys === 'requestId|type'
      || blockedMessageKeys === 'initiatedAt|requestId|type'
    )
    && typeof candidate.requestId === 'string'
    && requestIdPattern.test(candidate.requestId)
    && (
      candidate.initiatedAt === undefined
      || (
        Number.isSafeInteger(candidate.initiatedAt)
        && (candidate.initiatedAt as number) >= 0
        && (candidate.initiatedAt as number) <= maximumDateMilliseconds
      )
    )
  ) {
    return candidate.initiatedAt === undefined
      ? {
          type: candidate.type,
          requestId: candidate.requestId,
        }
      : {
          type: candidate.type,
          requestId: candidate.requestId,
          initiatedAt: candidate.initiatedAt as number,
        }
  }
  if (candidate.type === 'logout-pending-resolved') {
    if (Object.keys(candidate).sort().join('|') !== 'type|watermark') {
      return null
    }
    let serializedWatermark: string
    try {
      serializedWatermark = JSON.stringify(candidate.watermark)
    } catch {
      return null
    }
    const watermark = parseLogoutResolutionWatermark(serializedWatermark)
    return watermark
      ? { type: candidate.type, watermark }
      : null
  }
  if (
    candidate.type !== 'logout-pending-state'
    || Object.keys(candidate).sort().join('|') !== 'tombstone|type'
  ) {
    return null
  }
  let serialized: string
  try {
    serialized = JSON.stringify(candidate.tombstone)
  } catch {
    return null
  }
  const tombstone = parseLogoutPendingTombstone(serialized)
  return tombstone
    ? { type: candidate.type, tombstone }
    : null
}

const snapshotsMatch = (
  left: LogoutPendingSnapshot,
  right: LogoutPendingSnapshot,
): boolean => {
  if (left.status !== right.status) {
    return false
  }
  if (left.status === 'clear' && right.status === 'clear') {
    return true
  }
  if (left.status === 'blocked' && right.status === 'blocked') {
    return left.reason === right.reason
  }
  return left.status === 'pending'
    && right.status === 'pending'
    && left.tombstone.requestId === right.tombstone.requestId
    && left.tombstone.initiatedAt === right.tombstone.initiatedAt
    && left.tombstone.retryCount === right.tombstone.retryCount
}

export const createLogoutPendingStore = (
  options: LogoutPendingStoreOptions = {},
): LogoutPendingStore => {
  const configuredStorage = options.storage
  const eventTarget = options.eventTarget === undefined
    ? (typeof window === 'undefined' ? null : window)
    : options.eventTarget
  const channelFactory = options.channelFactory === undefined
    ? (
        typeof window === 'undefined' || typeof BroadcastChannel === 'undefined'
          ? null
          : (name: string) => new BroadcastChannel(name) as LogoutPendingChannel
      )
    : options.channelFactory
  const listeners = new Set<(
    snapshot: LogoutPendingSnapshot,
    context?: LogoutPendingChangeContext,
  ) => void>()
  let disposed = false
  let channel: LogoutPendingChannel | null = null
  let lastKnownTombstone: LogoutPendingTombstone | null = null
  let lastResolution: LogoutResolutionWatermark | null = null
  let resolutionConflict = false

  const readDurableResolutionWatermark = ():
    | LogoutResolutionWatermark
    | null => {
    const resolved = resolveStorage(configuredStorage)
    if (!resolved.storage) {
      return null
    }
    try {
      const serialized = resolved.storage.getItem(
        LOGOUT_RESOLUTION_STORAGE_KEY,
      )
      return serialized === null
        ? null
        : parseLogoutResolutionWatermark(serialized)
    } catch {
      return null
    }
  }

  const latestKnownResolution = (): LogoutResolutionWatermark | null => {
    const durable = readDurableResolutionWatermark()
    if (!lastResolution) {
      resolutionConflict = false
      lastResolution = durable
      return durable
    }
    if (!durable) {
      resolutionConflict = false
      return lastResolution
    }
    const elected = electResolutionWatermarks([lastResolution, durable])
    if (!elected) {
      resolutionConflict = true
      return null
    }
    resolutionConflict = false
    lastResolution = elected
    return lastResolution
  }

  const persistResolutionWatermark = (
    candidate: LogoutResolutionWatermark,
  ): LogoutResolutionWatermark | null => {
    const resolved = resolveStorage(configuredStorage)
    if (!resolved.storage) {
      return null
    }
    const existing = readDurableResolutionWatermark()
    const elected = electResolutionWatermarks([
      ...(lastResolution ? [lastResolution] : []),
      ...(existing ? [existing] : []),
      candidate,
    ])
    if (!elected) {
      return null
    }
    try {
      resolved.storage.setItem(
        LOGOUT_RESOLUTION_STORAGE_KEY,
        JSON.stringify(elected),
      )
      const written = resolved.storage.getItem(LOGOUT_RESOLUTION_STORAGE_KEY)
      const verified = written === null
        ? null
        : parseLogoutResolutionWatermark(written)
      if (!verified || !resolutionWatermarksMatch(verified, elected)) {
        return null
      }
      lastResolution = verified
      return verified
    } catch {
      return null
    }
  }

  const readResolutionConflictSnapshot = (): LogoutPendingSnapshot | null => {
    latestKnownResolution()
    return resolutionConflict
      ? blockedSnapshot(
        'malformed',
        undefined,
        lastKnownTombstone?.requestId,
      )
      : null
  }

  const readTrackedSnapshot = (): LogoutPendingSnapshot => {
    const conflictSnapshot = readResolutionConflictSnapshot()
    if (conflictSnapshot) {
      return conflictSnapshot
    }
    const snapshot = readLogoutPendingSnapshot(configuredStorage)
    if (snapshot.status === 'pending') {
      lastKnownTombstone = snapshot.tombstone
    }
    return snapshot
  }

  const createResolutionWatermark = (
    requestId: string,
    initiatedAt: number,
    resolution: LogoutPendingResolution,
  ): LogoutResolutionWatermark | null => {
    const resolvedAt = Math.max(Date.now(), initiatedAt)
    if (
      !Number.isSafeInteger(resolvedAt)
      || resolvedAt > maximumDateMilliseconds
    ) {
      return null
    }
    return parseLogoutResolutionWatermark(JSON.stringify({
      version: 1,
      requestId,
      initiatedAt,
      resolvedAt,
      resolution,
    }))
  }

  const refresh = (
    context?: LogoutPendingChangeContext,
  ): LogoutPendingSnapshot => {
    const priorTombstone = lastKnownTombstone
    const nextSnapshot = readTrackedSnapshot()
    let effectiveContext = context
    if (
      !effectiveContext
      && priorTombstone
      && nextSnapshot.status === 'clear'
    ) {
      const resolution = latestKnownResolution()
      if (
        resolution
        && resolutionSupersedesTombstone(resolution, priorTombstone)
      ) {
        lastKnownTombstone = null
        effectiveContext = {
          resolvedRequestId: priorTombstone.requestId,
          resolution: resolution.resolution,
        }
      }
    }
    for (const listener of listeners) {
      listener(nextSnapshot, effectiveContext)
    }
    return nextSnapshot
  }

  const onStorage = (event: Event) => {
    const key = (event as StorageEvent).key
    if (
      key === null
      || key === LOGOUT_PENDING_STORAGE_KEY
      || key === LOGOUT_RESOLUTION_STORAGE_KEY
    ) {
      refresh()
    }
  }
  const onSameTabChange = () => {
    refresh()
  }
  const postChannelMessage = (message: LogoutPendingChannelMessage) => {
    try {
      channel?.postMessage(message)
    } catch {
      // Durable storage and request-time reads remain authoritative.
    }
  }

  const applyRemoteTombstone = (
    tombstone: LogoutPendingTombstone,
  ): LogoutPendingSnapshot => {
    const resolution = latestKnownResolution()
    if (resolutionConflict) {
      return refresh()
    }
    if (resolution && resolutionSupersedesTombstone(resolution, tombstone)) {
      return refresh()
    }
    const currentSnapshot = readTrackedSnapshot()
    const currentRequestId = logoutPendingRequestId(currentSnapshot)
    if (currentSnapshot.status === 'pending') {
      const elected = electPendingTombstones([
        currentSnapshot.tombstone,
        tombstone,
      ])
      if (
        !elected
        || snapshotsMatch(
          currentSnapshot,
          { status: 'pending', tombstone: elected },
        )
      ) {
        return refresh()
      }
    } else if (
      currentSnapshot.status === 'blocked'
      && currentRequestId !== null
      && currentRequestId !== tombstone.requestId
    ) {
      return refresh()
    }
    if (
      currentSnapshot.status === 'blocked'
      && currentRequestId === null
      && (
        currentSnapshot.reason === 'malformed'
        || currentSnapshot.reason === 'oversized'
      )
    ) {
      const blockedStorage = resolveStorage(configuredStorage).storage
      if (blockedStorage) {
        runtimeUnconfirmedClearFences.set(
          blockedStorage as object,
          tombstone.requestId,
        )
      }
      lastKnownTombstone = tombstone
      return refresh()
    }

    lastKnownTombstone = tombstone
    const resolved = resolveStorage(configuredStorage)
    if (!resolved.storage) {
      return refresh()
    }
    const storageIdentity = resolved.storage as object
    runtimeUnconfirmedClearFences.set(storageIdentity, tombstone.requestId)
    try {
      resolved.storage.setItem(
        LOGOUT_PENDING_STORAGE_KEY,
        JSON.stringify(tombstone),
      )
    } catch {
      latchStorageFailure(
        resolved.storage,
        'storage-write-failed',
        tombstone.requestId,
      )
      return refresh()
    }
    const verified = readTrackedSnapshot()
    if (
      verified.status === 'pending'
      && snapshotsMatch(verified, { status: 'pending', tombstone })
    ) {
      storageFailureLatches.delete(storageIdentity)
      storageFailureRequestIds.delete(storageIdentity)
      verifiedWritableStorage.add(storageIdentity)
    }
    return refresh()
  }

  const applyRemoteBlocked = (
    requestId: string,
    initiatedAt?: number,
  ): LogoutPendingSnapshot => {
    const resolution = latestKnownResolution()
    if (resolutionConflict) {
      return refresh()
    }
    if (
      resolution
      && (
        resolution.requestId === requestId
        || (
          initiatedAt !== undefined
          && initiatedAt <= resolution.resolvedAt
        )
      )
    ) {
      return refresh()
    }
    const currentSnapshot = readTrackedSnapshot()
    const currentRequestId = logoutPendingRequestId(currentSnapshot)
    if (
      currentRequestId !== null
      && currentRequestId !== requestId
    ) {
      return refresh()
    }
    const resolved = resolveStorage(configuredStorage)
    if (resolved.storage) {
      const storageIdentity = resolved.storage as object
      runtimeUnconfirmedClearFences.set(storageIdentity, requestId)
      verifiedWritableStorage.delete(storageIdentity)
    }
    return refresh()
  }

  const applyRemoteResolution = (
    watermark: LogoutResolutionWatermark,
  ): LogoutPendingSnapshot => {
    const currentSnapshot = readTrackedSnapshot()
    if (resolutionConflict) {
      return refresh()
    }
    const currentRequestId = logoutPendingRequestId(currentSnapshot)
    if (
      currentSnapshot.status === 'pending'
      && currentSnapshot.tombstone.requestId === watermark.requestId
      && currentSnapshot.tombstone.initiatedAt !== watermark.initiatedAt
    ) {
      return refresh()
    }
    const persisted = persistResolutionWatermark(watermark)
    if (!persisted) {
      return refresh()
    }
    const appliesToCurrent =
      currentSnapshot.status === 'pending'
        ? resolutionSupersedesTombstone(
            persisted,
            currentSnapshot.tombstone,
          )
        : currentSnapshot.status === 'blocked'
          && currentRequestId === persisted.requestId
    if (
      lastKnownTombstone
      && resolutionSupersedesTombstone(persisted, lastKnownTombstone)
    ) {
      lastKnownTombstone = null
    }
    return refresh(
      appliesToCurrent
        ? {
            resolvedRequestId:
              currentRequestId ?? persisted.requestId,
            resolution: persisted.resolution,
          }
        : undefined,
    )
  }

  const onChannelMessage = (event: MessageEvent<unknown>) => {
    const message = parseLogoutPendingChannelMessage(event.data)
    if (!message) {
      return
    }
    if (message.type === 'logout-pending-changed') {
      refresh()
      return
    }
    if (message.type === 'logout-pending-state') {
      applyRemoteTombstone(message.tombstone)
      return
    }
    if (message.type === 'logout-pending-blocked') {
      applyRemoteBlocked(message.requestId, message.initiatedAt)
      return
    }
    if (message.type === 'logout-pending-resolved') {
      applyRemoteResolution(message.watermark)
      return
    }

    const watermark = latestKnownResolution()
    if (watermark) {
      postChannelMessage({
        type: 'logout-pending-resolved',
        watermark,
      })
    }
    const snapshot = readTrackedSnapshot()
    const requestId = logoutPendingRequestId(snapshot)
    if (snapshot.status === 'pending') {
      postChannelMessage({
        type: 'logout-pending-state',
        tombstone: snapshot.tombstone,
      })
      return
    }
    if (requestId) {
      if (lastKnownTombstone?.requestId === requestId) {
        postChannelMessage({
          type: 'logout-pending-state',
          tombstone: lastKnownTombstone,
        })
      } else {
        postChannelMessage({
          type: 'logout-pending-blocked',
          requestId,
        })
      }
      return
    }
  }

  eventTarget?.addEventListener('storage', onStorage)
  eventTarget?.addEventListener(LOGOUT_PENDING_CHANGED_EVENT, onSameTabChange)
  if (channelFactory) {
    try {
      channel = channelFactory(LOGOUT_PENDING_CHANNEL_NAME)
      channel.addEventListener('message', onChannelMessage)
    } catch {
      channel = null
    }
  }
  postChannelMessage({ type: 'logout-pending-sync-request' })

  const publishChange = (
    message: LogoutPendingChannelMessage = {
      type: 'logout-pending-changed',
    },
  ) => {
    refresh(
      message.type === 'logout-pending-resolved'
        ? {
            resolvedRequestId: message.watermark.requestId,
            resolution: message.watermark.resolution,
          }
        : undefined,
    )
    try {
      eventTarget?.dispatchEvent(new Event(LOGOUT_PENDING_CHANGED_EVENT))
    } catch {
      // The durable marker remains authoritative if same-tab notification fails.
    }
    postChannelMessage(message)
  }

  const resultFor = (
    status: LogoutPendingMutationResult['status'],
    snapshot: LogoutPendingSnapshot,
  ): LogoutPendingMutationResult => ({ status, snapshot })

  const failClosedBegin = (
    snapshot: Extract<LogoutPendingSnapshot, { status: 'blocked' }>,
    tombstone: LogoutPendingTombstone,
  ): LogoutPendingMutationResult => {
    const effectiveRequestId =
      logoutPendingRequestId(snapshot) ?? tombstone.requestId
    blockedRequestIds.set(snapshot, effectiveRequestId)
    const resolved = resolveStorage(configuredStorage)
    if (resolved.storage) {
      const storageIdentity = resolved.storage as object
      const activeRequestId =
        runtimeUnconfirmedClearFences.get(storageIdentity)
      if (
        activeRequestId === undefined
        || activeRequestId === effectiveRequestId
      ) {
        runtimeUnconfirmedClearFences.set(
          storageIdentity,
          effectiveRequestId,
        )
      }
      if (
        snapshot.reason === 'storage-read-failed'
        || snapshot.reason === 'storage-write-failed'
      ) {
        storageFailureRequestIds.set(
          storageIdentity,
          effectiveRequestId,
        )
      }
      verifiedWritableStorage.delete(storageIdentity)
    }
    if (effectiveRequestId === tombstone.requestId) {
      lastKnownTombstone = tombstone
      publishChange({
        type: 'logout-pending-state',
        tombstone,
      })
    } else {
      publishChange({
        type: 'logout-pending-blocked',
        requestId: effectiveRequestId,
      })
    }
    return resultFor('blocked', snapshot)
  }

  const writeTombstone = (
    tombstone: LogoutPendingTombstone,
  ): LogoutPendingMutationResult => {
    const conflictSnapshot = readResolutionConflictSnapshot()
    if (conflictSnapshot) {
      return resultFor('blocked', conflictSnapshot)
    }
    const resolved = resolveStorage(configuredStorage)
    if (!resolved.storage) {
      return resultFor('blocked', blockedSnapshot('storage-unavailable'))
    }
    try {
      resolved.storage.setItem(
        LOGOUT_PENDING_STORAGE_KEY,
        JSON.stringify(tombstone),
      )
    } catch {
      return resultFor(
        'blocked',
        latchStorageFailure(resolved.storage, 'storage-write-failed'),
      )
    }
    const verified = readTrackedSnapshot()
    if (
      verified.status !== 'pending'
      || !snapshotsMatch(verified, { status: 'pending', tombstone })
    ) {
      if (verified.status === 'clear') {
        return resultFor(
          'blocked',
          latchStorageFailure(resolved.storage, 'storage-write-failed'),
        )
      }
      return resultFor(
        verified.status === 'pending' ? 'stale' : 'blocked',
        verified,
      )
    }
    const storageIdentity = resolved.storage as object
    storageFailureLatches.delete(storageIdentity)
    storageFailureRequestIds.delete(storageIdentity)
    verifiedWritableStorage.add(storageIdentity)
    lastKnownTombstone = tombstone
    publishChange({
      type: 'logout-pending-state',
      tombstone,
    })
    return resultFor('applied', verified)
  }

  const removeCurrent = (
    releaseRuntimeRequestId?: string,
    resolution?: LogoutPendingResolution,
  ): LogoutPendingMutationResult => {
    const conflictSnapshot = readResolutionConflictSnapshot()
    if (conflictSnapshot) {
      return resultFor('blocked', conflictSnapshot)
    }
    const resolved = resolveStorage(configuredStorage)
    if (!resolved.storage) {
      return resultFor('blocked', blockedSnapshot('storage-unavailable'))
    }
    if (
      releaseRuntimeRequestId !== undefined
      && !requestIdPattern.test(releaseRuntimeRequestId)
    ) {
      return resultFor('blocked', blockedSnapshot('malformed'))
    }
    const storageIdentity = resolved.storage as object
    if (releaseRuntimeRequestId !== undefined) {
      const activeRequestId =
        runtimeUnconfirmedClearFences.get(storageIdentity)
      const failureRequestId =
        storageFailureRequestIds.get(storageIdentity)
      if (
        (
          activeRequestId !== undefined
          && activeRequestId !== releaseRuntimeRequestId
        )
        || (
          failureRequestId !== undefined
          && failureRequestId !== releaseRuntimeRequestId
        )
      ) {
        return resultFor(
          'stale',
          readTrackedSnapshot(),
        )
      }
    }
    let persistedWatermark: LogoutResolutionWatermark | null = null
    if (releaseRuntimeRequestId && resolution) {
      let currentTombstone: LogoutPendingTombstone | null
      try {
        const currentRaw = resolved.storage.getItem(
          LOGOUT_PENDING_STORAGE_KEY,
        )
        currentTombstone = currentRaw === null
          ? null
          : parseLogoutPendingTombstone(currentRaw)
      } catch {
        return resultFor(
          'blocked',
          latchStorageFailure(
            resolved.storage,
            'storage-read-failed',
            releaseRuntimeRequestId,
          ),
        )
      }
      const knownTombstone =
        currentTombstone?.requestId === releaseRuntimeRequestId
          ? currentTombstone
          : lastKnownTombstone?.requestId === releaseRuntimeRequestId
            ? lastKnownTombstone
            : null
      if (
        currentTombstone
        && currentTombstone.requestId !== releaseRuntimeRequestId
      ) {
        return resultFor(
          'stale',
          readTrackedSnapshot(),
        )
      }
      const candidate = createResolutionWatermark(
        releaseRuntimeRequestId,
        knownTombstone?.initiatedAt ?? 0,
        resolution,
      )
      persistedWatermark = candidate
        ? persistResolutionWatermark(candidate)
        : null
      if (!persistedWatermark) {
        return resultFor(
          'blocked',
          readTrackedSnapshot(),
        )
      }
    }
    try {
      resolved.storage.removeItem(LOGOUT_PENDING_STORAGE_KEY)
    } catch {
      if (persistedWatermark) {
        const verified = readTrackedSnapshot()
        if (verified.status === 'clear') {
          if (
            lastKnownTombstone
            && resolutionSupersedesTombstone(
              persistedWatermark,
              lastKnownTombstone,
            )
          ) {
            lastKnownTombstone = null
          }
          publishChange({
            type: 'logout-pending-resolved',
            watermark: persistedWatermark,
          })
          return resultFor('applied', verified)
        }
      }
      return resultFor(
        'blocked',
        latchStorageFailure(resolved.storage, 'storage-write-failed'),
      )
    }

    let remainingRawValue: string | null
    try {
      remainingRawValue = resolved.storage.getItem(LOGOUT_PENDING_STORAGE_KEY)
    } catch {
      return resultFor(
        'blocked',
        latchStorageFailure(resolved.storage, 'storage-read-failed'),
      )
    }
    if (remainingRawValue !== null) {
      const remainingSnapshot = readTrackedSnapshot()
      if (persistedWatermark && remainingSnapshot.status === 'clear') {
        if (
          lastKnownTombstone
          && resolutionSupersedesTombstone(
            persistedWatermark,
            lastKnownTombstone,
          )
        ) {
          lastKnownTombstone = null
        }
        publishChange({
          type: 'logout-pending-resolved',
          watermark: persistedWatermark,
        })
        return resultFor('applied', remainingSnapshot)
      }
      if (remainingSnapshot.status === 'pending') {
        return resultFor(
          'blocked',
          latchStorageFailure(resolved.storage, 'storage-write-failed'),
        )
      }
      return resultFor('blocked', remainingSnapshot)
    }

    const probeFailure = verifyStorageWritable(resolved.storage, true)
    if (probeFailure) {
      return resultFor('blocked', probeFailure)
    }
    if (releaseRuntimeRequestId !== undefined) {
      const activeRequestId = runtimeUnconfirmedClearFences.get(storageIdentity)
      if (
        activeRequestId !== undefined
        && activeRequestId !== releaseRuntimeRequestId
      ) {
        const mismatchedSnapshot = readTrackedSnapshot()
        publishChange()
        return resultFor('stale', mismatchedSnapshot)
      }
      runtimeUnconfirmedClearFences.delete(storageIdentity)
    }
    const verified = readTrackedSnapshot()
    if (verified.status === 'pending') {
      publishChange({
        type: 'logout-pending-state',
        tombstone: verified.tombstone,
      })
      return resultFor('stale', verified)
    }
    if (
      verified.status === 'blocked'
      && verified.reason !== 'unconfirmed-clear'
    ) {
      publishChange()
      return resultFor('blocked', verified)
    }
    storageFailureLatches.delete(storageIdentity)
    if (
      releaseRuntimeRequestId === undefined
      || storageFailureRequestIds.get(storageIdentity)
        === releaseRuntimeRequestId
    ) {
      storageFailureRequestIds.delete(storageIdentity)
    }
    verifiedWritableStorage.add(storageIdentity)
    if (persistedWatermark) {
      if (
        lastKnownTombstone
        && resolutionSupersedesTombstone(
          persistedWatermark,
          lastKnownTombstone,
        )
      ) {
        lastKnownTombstone = null
      }
      publishChange({
        type: 'logout-pending-resolved',
        watermark: persistedWatermark,
      })
    } else {
      publishChange()
    }
    return resultFor('applied', verified)
  }

  const retainRuntimeFence = (requestId: string): LogoutPendingSnapshot => {
    const conflictSnapshot = readResolutionConflictSnapshot()
    if (conflictSnapshot) {
      return conflictSnapshot
    }
    const resolved = resolveStorage(configuredStorage)
    if (!resolved.storage) {
      return blockedSnapshot('storage-unavailable')
    }
    if (!requestIdPattern.test(requestId)) {
      return blockedSnapshot('malformed')
    }
    runtimeUnconfirmedClearFences.set(
      resolved.storage as object,
      requestId,
    )
    return readTrackedSnapshot()
  }

  const releaseRuntimeFenceIfMatching = (
    requestId: string,
    resolution?: LogoutPendingResolution,
  ): LogoutPendingMutationResult => {
    const conflictSnapshot = readResolutionConflictSnapshot()
    if (conflictSnapshot) {
      return resultFor('blocked', conflictSnapshot)
    }
    const resolved = resolveStorage(configuredStorage)
    if (!resolved.storage) {
      return resultFor('blocked', blockedSnapshot('storage-unavailable'))
    }
    if (!requestIdPattern.test(requestId)) {
      return resultFor('blocked', blockedSnapshot('malformed'))
    }

    let currentRawValue: string | null
    try {
      currentRawValue = resolved.storage.getItem(LOGOUT_PENDING_STORAGE_KEY)
    } catch {
      return resultFor(
        'blocked',
        latchStorageFailure(resolved.storage, 'storage-read-failed'),
      )
    }
    if (currentRawValue !== null) {
      const currentSnapshot = readTrackedSnapshot()
      return resultFor(
        currentSnapshot.status === 'pending' ? 'stale' : 'blocked',
        currentSnapshot,
      )
    }

    const storageIdentity = resolved.storage as object
    const activeRequestId = runtimeUnconfirmedClearFences.get(storageIdentity)
    if (!activeRequestId) {
      return resultFor(
        'unchanged',
        readTrackedSnapshot(),
      )
    }
    if (activeRequestId !== requestId) {
      return resultFor('stale', readTrackedSnapshot())
    }
    if (resolution) {
      const knownTombstone =
        lastKnownTombstone?.requestId === requestId
          ? lastKnownTombstone
          : null
      const candidate = createResolutionWatermark(
        requestId,
        knownTombstone?.initiatedAt ?? 0,
        resolution,
      )
      const persisted = candidate
        ? persistResolutionWatermark(candidate)
        : null
      if (!persisted) {
        return resultFor(
          'blocked',
          readTrackedSnapshot(),
        )
      }
      const verified = readTrackedSnapshot()
      if (verified.status !== 'clear') {
        return resultFor(
          verified.status === 'pending' ? 'stale' : 'blocked',
          verified,
        )
      }
      if (
        lastKnownTombstone
        && resolutionSupersedesTombstone(persisted, lastKnownTombstone)
      ) {
        lastKnownTombstone = null
      }
      publishChange({
        type: 'logout-pending-resolved',
        watermark: persisted,
      })
      return resultFor('applied', verified)
    }
    const probeFailure = verifyStorageWritable(resolved.storage, true)
    if (probeFailure) {
      return resultFor('blocked', probeFailure)
    }
    runtimeUnconfirmedClearFences.delete(storageIdentity)
    storageFailureLatches.delete(storageIdentity)
    storageFailureRequestIds.delete(storageIdentity)
    verifiedWritableStorage.add(storageIdentity)
    const verified = readTrackedSnapshot()
    if (verified.status !== 'clear') {
      publishChange()
      return resultFor(
        verified.status === 'pending' ? 'stale' : 'blocked',
        verified,
      )
    }
    publishChange()
    return resultFor('applied', verified)
  }

  const releaseRuntimeFenceAfterLogin = (
    requestId: string,
  ): LogoutPendingMutationResult =>
    releaseRuntimeFenceIfMatching(requestId, 'replacement-login')

  const publishProofPositiveResolution = (
    requestId: string,
    snapshot: LogoutPendingSnapshot,
  ): LogoutPendingMutationResult => {
    const knownTombstone =
      lastKnownTombstone?.requestId === requestId
        ? lastKnownTombstone
        : null
    const candidate = createResolutionWatermark(
      requestId,
      knownTombstone?.initiatedAt ?? 0,
      'confirmed',
    )
    if (!candidate) {
      return resultFor('blocked', snapshot)
    }
    const priorResolution = latestKnownResolution()
    if (resolutionConflict) {
      return resultFor('blocked', readTrackedSnapshot())
    }
    const persisted = persistResolutionWatermark(candidate)
    const watermark = persisted ?? candidate
    const elected = priorResolution
      ? electResolutionWatermarks([priorResolution, watermark])
      : watermark
    if (!elected) {
      return resultFor('blocked', snapshot)
    }
    lastResolution = elected
    if (
      persisted
      && lastKnownTombstone
      && resolutionSupersedesTombstone(elected, lastKnownTombstone)
    ) {
      lastKnownTombstone = null
    }
    publishChange({
      type: 'logout-pending-resolved',
      watermark: elected,
    })
    return resultFor(
      'applied',
      persisted
        ? readTrackedSnapshot()
        : snapshot,
    )
  }

  const clearIfMatching = (requestId: string): LogoutPendingMutationResult => {
    const snapshot = readTrackedSnapshot()
    if (snapshot.status === 'blocked') {
      if (logoutPendingRequestId(snapshot) !== requestId) {
        return resultFor('blocked', snapshot)
      }
      if (snapshot.reason === 'unconfirmed-clear') {
        const released = releaseRuntimeFenceIfMatching(requestId, 'confirmed')
        return released.status === 'applied' || released.status === 'stale'
          ? released
          : publishProofPositiveResolution(requestId, released.snapshot)
      }
      if (
        snapshot.reason === 'malformed'
        || snapshot.reason === 'oversized'
      ) {
        const cleared = removeCurrent(requestId, 'confirmed')
        return cleared.status === 'applied' || cleared.status === 'stale'
          ? cleared
          : publishProofPositiveResolution(requestId, cleared.snapshot)
      }
      const cleared = removeCurrent(requestId, 'confirmed')
      return cleared.status === 'applied' || cleared.status === 'stale'
        ? cleared
        : publishProofPositiveResolution(requestId, cleared.snapshot)
    }
    if (snapshot.status === 'clear') {
      return resultFor('unchanged', snapshot)
    }
    if (snapshot.tombstone.requestId !== requestId) {
      return resultFor('stale', snapshot)
    }
    return removeCurrent(requestId, 'confirmed')
  }

  const recoverStorageAfterSuccessfulLogin = (
    capturedRequestId: string | null,
  ): LogoutPendingMutationResult => {
    const conflictSnapshot = readResolutionConflictSnapshot()
    if (conflictSnapshot) {
      return resultFor('blocked', conflictSnapshot)
    }
    const resolved = resolveStorage(configuredStorage)
    if (!resolved.storage) {
      return resultFor('blocked', blockedSnapshot('storage-unavailable'))
    }

    let currentRawValue: string | null
    try {
      currentRawValue = resolved.storage.getItem(LOGOUT_PENDING_STORAGE_KEY)
    } catch {
      return resultFor(
        'blocked',
        latchStorageFailure(resolved.storage, 'storage-read-failed'),
      )
    }
    if (currentRawValue !== null) {
      const currentSnapshot = readTrackedSnapshot()
      if (
        capturedRequestId
        && currentSnapshot.status === 'pending'
        && currentSnapshot.tombstone.requestId === capturedRequestId
      ) {
        return removeCurrent(
          capturedRequestId,
          'replacement-login',
        )
      }
      return resultFor(
        currentSnapshot.status === 'pending' ? 'stale' : 'blocked',
        currentSnapshot,
      )
    }

    const probeFailure = verifyStorageWritable(resolved.storage, true)
    if (probeFailure) {
      return resultFor('blocked', probeFailure)
    }
    const storageIdentity = resolved.storage as object
    const activeRequestId = runtimeUnconfirmedClearFences.get(storageIdentity)
    const failureRequestId = storageFailureRequestIds.get(storageIdentity)
    const recoveryRequestId =
      capturedRequestId ?? failureRequestId ?? activeRequestId ?? null
    if (
      recoveryRequestId
      && (
        (activeRequestId !== undefined && activeRequestId !== recoveryRequestId)
        || (
          failureRequestId !== undefined
          && failureRequestId !== recoveryRequestId
        )
      )
    ) {
      return resultFor(
        'stale',
        readTrackedSnapshot(),
      )
    }
    if (recoveryRequestId) {
      return releaseRuntimeFenceIfMatching(
        recoveryRequestId,
        'replacement-login',
      )
    }
    storageFailureLatches.delete(storageIdentity)
    storageFailureRequestIds.delete(storageIdentity)
    verifiedWritableStorage.add(storageIdentity)
    const verified = readTrackedSnapshot()
    if (verified.status !== 'clear') {
      return resultFor(
        verified.status === 'pending' ? 'stale' : 'blocked',
        verified,
      )
    }
    publishChange()
    return resultFor('applied', verified)
  }

  return {
    read: readTrackedSnapshot,
    refresh,
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    begin: (requestId, initiatedAt) => {
      createLogoutPendingTombstone(requestId, initiatedAt)
      const watermark = latestKnownResolution()
      if (resolutionConflict) {
        return resultFor(
          'blocked',
          blockedSnapshot('malformed', undefined, requestId),
        )
      }
      if (
        watermark
        && initiatedAt <= watermark.resolvedAt
        && watermark.resolvedAt >= maximumDateMilliseconds
      ) {
        const resolved = resolveStorage(configuredStorage)
        if (resolved.storage) {
          runtimeUnconfirmedClearFences.set(
            resolved.storage as object,
            requestId,
          )
        }
        return resultFor(
          'blocked',
          blockedSnapshot('unconfirmed-clear', undefined, requestId),
        )
      }
      const effectiveInitiatedAt =
        watermark && initiatedAt <= watermark.resolvedAt
          ? watermark.resolvedAt + 1
          : initiatedAt
      const tombstone = createLogoutPendingTombstone(
        requestId,
        effectiveInitiatedAt,
      )
      const snapshot = readTrackedSnapshot()
      if (snapshot.status === 'blocked') {
        return failClosedBegin(snapshot, tombstone)
      }
      if (snapshot.status === 'pending') {
        const order = comparePendingTombstones(
          snapshot.tombstone,
          tombstone,
        )
        if (order === null) {
          return resultFor('blocked', snapshot)
        }
        if (order > 0) {
          return writeTombstone(tombstone)
        }
        return resultFor(
          snapshot.tombstone.requestId === requestId
            ? 'unchanged'
            : 'stale',
          snapshot,
        )
      }
      const written = writeTombstone(tombstone)
      return written.status === 'blocked'
        && written.snapshot.status === 'blocked'
        ? failClosedBegin(written.snapshot, tombstone)
        : written
    },
    recordRetry: (requestId, retryCount) => {
      const snapshot = readTrackedSnapshot()
      if (snapshot.status === 'blocked') {
        return resultFor('blocked', snapshot)
      }
      if (
        snapshot.status === 'clear'
        || snapshot.tombstone.requestId !== requestId
      ) {
        return resultFor('stale', snapshot)
      }
      if (
        !Number.isSafeInteger(retryCount)
        || retryCount < 0
        || retryCount > LOGOUT_MAX_TOTAL_ATTEMPTS
      ) {
        return resultFor('blocked', snapshot)
      }
      if (snapshot.tombstone.retryCount >= retryCount) {
        return resultFor('unchanged', snapshot)
      }
      return writeTombstone({
        ...snapshot.tombstone,
        retryCount,
      })
    },
    clearIfMatching,
    retainRuntimeFence,
    releaseRuntimeFenceIfMatching,
    releaseRuntimeFenceAfterLogin,
    clearAfterSuccessfulLogin: (capturedSnapshot) => {
      const conflictSnapshot = readResolutionConflictSnapshot()
      if (conflictSnapshot) {
        return resultFor('blocked', conflictSnapshot)
      }
      if (capturedSnapshot.status === 'clear') {
        return resultFor('unchanged', readTrackedSnapshot())
      }
      if (capturedSnapshot.status === 'pending') {
        const currentSnapshot = readTrackedSnapshot()
        if (
          currentSnapshot.status === 'blocked'
          && currentSnapshot.reason === 'unconfirmed-clear'
          && logoutPendingRequestId(currentSnapshot)
            === capturedSnapshot.tombstone.requestId
        ) {
          return releaseRuntimeFenceAfterLogin(
            capturedSnapshot.tombstone.requestId,
          )
        }
        if (
          currentSnapshot.status === 'pending'
          && currentSnapshot.tombstone.requestId
            === capturedSnapshot.tombstone.requestId
        ) {
          return removeCurrent(
            capturedSnapshot.tombstone.requestId,
            'replacement-login',
          )
        }
        return currentSnapshot.status === 'clear'
          ? resultFor('unchanged', currentSnapshot)
          : resultFor(
              currentSnapshot.status === 'pending' ? 'stale' : 'blocked',
              currentSnapshot,
            )
      }
      if (capturedSnapshot.reason === 'unconfirmed-clear') {
        const capturedRequestId = logoutPendingRequestId(capturedSnapshot)
        return capturedRequestId
          ? releaseRuntimeFenceAfterLogin(capturedRequestId)
          : resultFor('blocked', readTrackedSnapshot())
      }
      if (
        capturedSnapshot.reason === 'storage-unavailable'
        || capturedSnapshot.reason === 'storage-read-failed'
        || capturedSnapshot.reason === 'storage-write-failed'
      ) {
        return recoverStorageAfterSuccessfulLogin(
          logoutPendingRequestId(capturedSnapshot),
        )
      }
      if (
        capturedSnapshot.reason !== 'malformed'
        && capturedSnapshot.reason !== 'oversized'
      ) {
        return resultFor('blocked', readTrackedSnapshot())
      }
      const capturedResolutionRaw =
        blockedResolutionRawValues.get(capturedSnapshot)
      if (capturedResolutionRaw !== undefined) {
        const capturedPendingRaw =
          blockedResolutionPendingRawValues.get(capturedSnapshot) ?? null
        const resolved = resolveStorage(configuredStorage)
        if (!resolved.storage) {
          return resultFor(
            'blocked',
            readTrackedSnapshot(),
          )
        }
        let currentResolutionRaw: string | null
        let currentPendingRaw: string | null
        try {
          currentResolutionRaw = resolved.storage.getItem(
            LOGOUT_RESOLUTION_STORAGE_KEY,
          )
          currentPendingRaw = resolved.storage.getItem(
            LOGOUT_PENDING_STORAGE_KEY,
          )
        } catch {
          return resultFor('blocked', blockedSnapshot('storage-read-failed'))
        }
        if (
          currentResolutionRaw !== capturedResolutionRaw
          || currentPendingRaw !== capturedPendingRaw
        ) {
          return resultFor(
            'stale',
            readTrackedSnapshot(),
          )
        }
        const capturedTombstone = currentPendingRaw === null
          ? null
          : parseLogoutPendingTombstone(currentPendingRaw)
        const recoveryRequestId =
          logoutPendingRequestId(capturedSnapshot)
          ?? capturedTombstone?.requestId
          ?? null
        if (capturedTombstone) {
          lastKnownTombstone = capturedTombstone
        }
        if (recoveryRequestId) {
          return removeCurrent(
            recoveryRequestId,
            'replacement-login',
          )
        }
        try {
          resolved.storage.removeItem(LOGOUT_RESOLUTION_STORAGE_KEY)
          if (
            resolved.storage.getItem(LOGOUT_RESOLUTION_STORAGE_KEY) !== null
          ) {
            return resultFor(
              'blocked',
              readTrackedSnapshot(),
            )
          }
        } catch {
          return resultFor('blocked', blockedSnapshot('storage-write-failed'))
        }
        return removeCurrent()
      }
      const capturedRawValue = blockedRawValues.get(capturedSnapshot)
      const resolved = resolveStorage(configuredStorage)
      if (!capturedRawValue || !resolved.storage) {
        return resultFor('blocked', readTrackedSnapshot())
      }
      let currentRawValue: string | null
      try {
        currentRawValue = resolved.storage.getItem(LOGOUT_PENDING_STORAGE_KEY)
      } catch {
        return resultFor('blocked', blockedSnapshot('storage-read-failed'))
      }
      if (currentRawValue !== capturedRawValue) {
        return resultFor('stale', readTrackedSnapshot())
      }
      const capturedRequestId = logoutPendingRequestId(capturedSnapshot)
      return removeCurrent(
        capturedRequestId ?? undefined,
        capturedRequestId ? 'replacement-login' : undefined,
      )
    },
    dispose: () => {
      if (disposed) {
        return
      }
      disposed = true
      listeners.clear()
      eventTarget?.removeEventListener('storage', onStorage)
      eventTarget?.removeEventListener(LOGOUT_PENDING_CHANGED_EVENT, onSameTabChange)
      if (channel) {
        channel.removeEventListener('message', onChannelMessage)
        channel.close()
      }
      channel = null
    },
  }
}

export type LogoutAttemptResult =
  | 'confirmed'
  | 'retryable'
  | 'unconfirmed'
  | 'stale'

export type LogoutRetryReason =
  | 'offline'
  | 'retry-scheduled'
  | 'no-proof'
  | 'server-unconfirmed'
  | 'non-retryable-error'
  | 'exhausted'
  | 'stale'
  | 'cancelled'

export type LogoutRetrySnapshot = Readonly<{
  status:
    | 'idle'
    | 'waiting'
    | 'attempting'
    | 'confirmed'
    | 'unconfirmed'
    | 'cancelled'
  requestId: string | null
  retryCount: number
  inFlight: boolean
  proofAvailable: boolean
  canRetry: boolean
  nextRetryDelayMs: number | null
  reason: LogoutRetryReason | null
}>

export type LogoutRetryScheduler = {
  setTimer: (callback: () => void, delayMs: number) => unknown
  clearTimer: (handle: unknown) => void
}

export type LogoutRetryCoordinator = {
  start: (input: { requestId: string; proof: unknown | null }) => void
  requestExplicitRetry: (requestId: string) => boolean
  notifyOnline: (requestId: string) => boolean
  cancel: (requestId: string, reason?: LogoutRetryReason) => boolean
  getSnapshot: () => LogoutRetrySnapshot
  dispose: () => void
}

type LogoutRetryDependencies<Proof> = {
  attempt: (input: {
    requestId: string
    proof: Proof
    retryCount: number
    signal: AbortSignal
  }) => Promise<LogoutAttemptResult>
  isCurrent: (requestId: string) => boolean
  classifyError: (error: unknown) => 'retryable' | 'unconfirmed'
  scheduler?: LogoutRetryScheduler
  isOnline?: () => boolean
  recordAttempt?: (requestId: string, retryCount: number) => boolean
  onStateChange?: (snapshot: LogoutRetrySnapshot) => void
}

const defaultScheduler: LogoutRetryScheduler = {
  setTimer: (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
  clearTimer: (handle) => globalThis.clearTimeout(handle as number),
}

export const createLogoutRetryCoordinator = <Proof>(
  dependencies: LogoutRetryDependencies<Proof>,
): LogoutRetryCoordinator => {
  const scheduler = dependencies.scheduler ?? defaultScheduler
  const isOnline = dependencies.isOnline ?? (() => true)
  let disposed = false
  let requestId: string | null = null
  let proof: Proof | null = null
  let retryCount = 0
  let inFlight = false
  let retryEligible = false
  let nextRetryDelayMs: number | null = null
  let status: LogoutRetrySnapshot['status'] = 'idle'
  let reason: LogoutRetryReason | null = null
  let timerHandle: unknown = null
  let operationVersion = 0
  let abortController: AbortController | null = null

  const getSnapshot = (): LogoutRetrySnapshot => Object.freeze({
    status,
    requestId,
    retryCount,
    inFlight,
    proofAvailable: proof !== null,
    canRetry:
      !disposed
      && requestId !== null
      && proof !== null
      && retryEligible
      && !inFlight
      && retryCount < LOGOUT_MAX_TOTAL_ATTEMPTS
      && dependencies.isCurrent(requestId),
    nextRetryDelayMs,
    reason,
  })

  const notify = () => {
    dependencies.onStateChange?.(getSnapshot())
  }

  const clearScheduledRetry = () => {
    if (timerHandle !== null) {
      scheduler.clearTimer(timerHandle)
      timerHandle = null
    }
    nextRetryDelayMs = null
  }

  const setTerminalState = (
    nextStatus: 'confirmed' | 'unconfirmed' | 'cancelled',
    nextReason: LogoutRetryReason | null,
  ) => {
    clearScheduledRetry()
    status = nextStatus
    reason = nextReason
    retryEligible = false
    inFlight = false
    abortController = null
    proof = null
    notify()
  }

  const scheduleRetry = (runAttempt: () => void) => {
    if (retryCount >= LOGOUT_MAX_TOTAL_ATTEMPTS) {
      setTerminalState('unconfirmed', 'exhausted')
      return
    }
    if (!isOnline()) {
      status = 'waiting'
      reason = 'offline'
      nextRetryDelayMs = null
      notify()
      return
    }
    const delay = LOGOUT_RETRY_DELAYS_MS[retryCount - 1]
    if (delay === undefined) {
      setTerminalState('unconfirmed', 'exhausted')
      return
    }
    status = 'waiting'
    reason = 'retry-scheduled'
    nextRetryDelayMs = delay
    timerHandle = scheduler.setTimer(() => {
      timerHandle = null
      nextRetryDelayMs = null
      runAttempt()
    }, delay)
    notify()
  }

  const runAttempt = async () => {
    const activeRequestId = requestId
    const activeProof = proof
    if (
      disposed
      || !activeRequestId
      || !activeProof
      || inFlight
    ) {
      return
    }
    if (!dependencies.isCurrent(activeRequestId)) {
      setTerminalState('cancelled', 'stale')
      return
    }
    if (!isOnline()) {
      status = 'waiting'
      reason = 'offline'
      retryEligible = true
      notify()
      return
    }
    if (retryCount >= LOGOUT_MAX_TOTAL_ATTEMPTS) {
      setTerminalState('unconfirmed', 'exhausted')
      return
    }

    clearScheduledRetry()
    retryCount += 1
    if (
      dependencies.recordAttempt
      && !dependencies.recordAttempt(activeRequestId, retryCount)
    ) {
      setTerminalState('cancelled', 'stale')
      return
    }
    inFlight = true
    retryEligible = false
    status = 'attempting'
    reason = null
    abortController = new AbortController()
    const activeVersion = operationVersion
    notify()

    let result: LogoutAttemptResult
    try {
      result = await dependencies.attempt({
        requestId: activeRequestId,
        proof: activeProof,
        retryCount,
        signal: abortController.signal,
      })
    } catch (error) {
      result = dependencies.classifyError(error)
    }

    if (
      disposed
      || activeVersion !== operationVersion
      || requestId !== activeRequestId
    ) {
      return
    }
    if (!dependencies.isCurrent(activeRequestId)) {
      setTerminalState('cancelled', 'stale')
      return
    }
    inFlight = false
    abortController = null
    if (result === 'confirmed') {
      setTerminalState('confirmed', null)
      return
    }
    if (result === 'unconfirmed') {
      setTerminalState('unconfirmed', 'server-unconfirmed')
      return
    }
    if (result === 'stale') {
      setTerminalState('cancelled', 'stale')
      return
    }
    retryEligible = true
    scheduleRetry(() => {
      void runAttempt()
    })
  }

  return {
    start: (input) => {
      operationVersion += 1
      clearScheduledRetry()
      abortController?.abort()
      abortController = null
      requestId = input.requestId
      proof = input.proof as Proof | null
      retryCount = 0
      inFlight = false
      retryEligible = input.proof !== null
      if (input.proof === null) {
        status = 'unconfirmed'
        reason = 'no-proof'
        notify()
        return
      }
      status = isOnline() ? 'waiting' : 'waiting'
      reason = isOnline() ? 'retry-scheduled' : 'offline'
      notify()
      void runAttempt()
    },
    requestExplicitRetry: (candidateRequestId) => {
      if (
        disposed
        || candidateRequestId !== requestId
        || !proof
        || inFlight
        || !retryEligible
        || retryCount >= LOGOUT_MAX_TOTAL_ATTEMPTS
        || !dependencies.isCurrent(candidateRequestId)
      ) {
        return false
      }
      clearScheduledRetry()
      void runAttempt()
      return true
    },
    notifyOnline: (candidateRequestId) => {
      if (
        disposed
        || candidateRequestId !== requestId
        || !proof
        || inFlight
        || !retryEligible
        || retryCount >= LOGOUT_MAX_TOTAL_ATTEMPTS
        || !dependencies.isCurrent(candidateRequestId)
      ) {
        return false
      }
      clearScheduledRetry()
      void runAttempt()
      return true
    },
    cancel: (candidateRequestId, cancelReason = 'cancelled') => {
      if (candidateRequestId !== requestId) {
        return false
      }
      operationVersion += 1
      abortController?.abort()
      abortController = null
      setTerminalState('cancelled', cancelReason)
      return true
    },
    getSnapshot,
    dispose: () => {
      if (disposed) {
        return
      }
      disposed = true
      operationVersion += 1
      clearScheduledRetry()
      abortController?.abort()
      abortController = null
      proof = null
      inFlight = false
      retryEligible = false
    },
  }
}
