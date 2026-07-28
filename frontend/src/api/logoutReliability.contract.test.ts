/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import {
  createLogoutPendingStore,
  createLogoutPendingTombstone,
  createLogoutRetryCoordinator,
  isLogoutPendingBlocked,
  LOGOUT_MAX_TOTAL_ATTEMPTS,
  LOGOUT_PENDING_CHANNEL_NAME,
  LOGOUT_PENDING_CHANGED_EVENT,
  LOGOUT_PENDING_MAX_SERIALIZED_BYTES,
  LOGOUT_PENDING_STORAGE_KEY,
  LOGOUT_RESOLUTION_MAX_SERIALIZED_BYTES,
  LOGOUT_RESOLUTION_STORAGE_KEY,
  LOGOUT_RETRY_DELAYS_MS,
  logoutPendingRequestId,
  parseLogoutResolutionWatermark,
  parseLogoutPendingTombstone,
  readLogoutPendingSnapshot,
  type LogoutAttemptResult,
  type LogoutPendingSnapshot,
  type LogoutPendingStorage,
  type LogoutResolutionWatermark,
  type LogoutRetrySnapshot,
  type LogoutRetryScheduler,
} from './logoutReliability.ts'

class MemoryStorage implements LogoutPendingStorage {
  private readonly values = new Map<string, string>()
  failRead = false
  failWrite = false
  failRemove = false
  ignoreWrite = false
  ignoreRemove = false
  onProbeRead: (() => void) | null = null

  getItem(key: string): string | null {
    if (this.failRead) {
      throw new Error('storage read failed')
    }
    if (
      key !== LOGOUT_PENDING_STORAGE_KEY
      && key !== LOGOUT_RESOLUTION_STORAGE_KEY
      && this.onProbeRead
    ) {
      const callback = this.onProbeRead
      this.onProbeRead = null
      callback()
    }
    return this.values.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    if (this.failWrite) {
      throw new Error('storage write failed')
    }
    if (!this.ignoreWrite) {
      this.values.set(key, value)
    }
  }

  removeItem(key: string): void {
    if (this.failRemove) {
      throw new Error('storage remove failed')
    }
    if (!this.ignoreRemove) {
      this.values.delete(key)
    }
  }

  readRaw(): string | null {
    return this.values.get(LOGOUT_PENDING_STORAGE_KEY) ?? null
  }

  writeRaw(value: string): void {
    this.values.set(LOGOUT_PENDING_STORAGE_KEY, value)
  }

  readResolutionRaw(): string | null {
    return this.values.get(LOGOUT_RESOLUTION_STORAGE_KEY) ?? null
  }

  writeResolutionRaw(value: string): void {
    this.values.set(LOGOUT_RESOLUTION_STORAGE_KEY, value)
  }
}

type ChannelListener = (event: MessageEvent<unknown>) => void

class FakeBroadcastChannel {
  private readonly listeners = new Set<ChannelListener>()
  private readonly hub: FakeBroadcastHub
  closed = false

  constructor(hub: FakeBroadcastHub) {
    this.hub = hub
  }

  postMessage(message: unknown): void {
    this.hub.deliver(this, message)
  }

  addEventListener(type: 'message', listener: ChannelListener): void {
    assert.equal(type, 'message')
    this.listeners.add(listener)
  }

  removeEventListener(type: 'message', listener: ChannelListener): void {
    assert.equal(type, 'message')
    this.listeners.delete(listener)
  }

  close(): void {
    this.closed = true
    this.hub.remove(this)
    this.listeners.clear()
  }

  receive(message: unknown): void {
    const event = { data: message } as MessageEvent<unknown>
    for (const listener of this.listeners) {
      listener(event)
    }
  }
}

class FakeBroadcastHub {
  private readonly channels = new Set<FakeBroadcastChannel>()
  readonly messages: unknown[] = []

  create = (name: string): FakeBroadcastChannel => {
    assert.equal(name, LOGOUT_PENDING_CHANNEL_NAME)
    const channel = new FakeBroadcastChannel(this)
    this.channels.add(channel)
    return channel
  }

  deliver(sender: FakeBroadcastChannel, message: unknown): void {
    this.messages.push(message)
    for (const channel of this.channels) {
      if (channel !== sender && !channel.closed) {
        channel.receive(message)
      }
    }
  }

  broadcast(message: unknown): void {
    this.messages.push(message)
    for (const channel of this.channels) {
      if (!channel.closed) {
        channel.receive(message)
      }
    }
  }

  remove(channel: FakeBroadcastChannel): void {
    this.channels.delete(channel)
  }
}

type ScheduledTask = {
  id: number
  dueAt: number
  callback: () => void
}

class FakeScheduler implements LogoutRetryScheduler {
  now = 0
  private nextId = 1
  private readonly tasks = new Map<number, ScheduledTask>()

  setTimer = (callback: () => void, delayMs: number): unknown => {
    const id = this.nextId
    this.nextId += 1
    this.tasks.set(id, {
      id,
      dueAt: this.now + delayMs,
      callback,
    })
    return id
  }

  clearTimer = (handle: unknown): void => {
    if (typeof handle === 'number') {
      this.tasks.delete(handle)
    }
  }

  advanceBy(delayMs: number): void {
    const target = this.now + delayMs
    while (true) {
      const next = Array.from(this.tasks.values())
        .filter((task) => task.dueAt <= target)
        .sort((left, right) =>
          left.dueAt - right.dueAt || left.id - right.id
        )[0]
      if (!next) {
        break
      }
      this.tasks.delete(next.id)
      this.now = next.dueAt
      next.callback()
    }
    this.now = target
  }

  get pendingCount(): number {
    return this.tasks.size
  }
}

const deferred = <T>() => {
  let resolvePromise: (value: T | PromiseLike<T>) => void = () => undefined
  let rejectPromise: (reason?: unknown) => void = () => undefined
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve
    rejectPromise = reject
  })
  return {
    promise,
    resolve: resolvePromise,
    reject: rejectPromise,
  }
}

const flushAsync = async () => {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

const serializePending = (
  requestId = 'request-1',
  initiatedAt = 1_722_160_800_000,
  retryCount = 0,
): string => JSON.stringify({
  version: 1,
  requestId,
  initiatedAt,
  retryCount,
})

const serializeResolution = (
  requestId = 'request-1',
  initiatedAt = 123,
  resolvedAt = 456,
  resolution: LogoutResolutionWatermark['resolution'] = 'confirmed',
): string => JSON.stringify({
  version: 1,
  requestId,
  initiatedAt,
  resolvedAt,
  resolution,
})

const resolutionMessage = (
  requestId: string,
  initiatedAt: number,
  resolvedAt: number,
  resolution: LogoutResolutionWatermark['resolution'] = 'confirmed',
) => ({
  type: 'logout-pending-resolved',
  watermark: {
    version: 1,
    requestId,
    initiatedAt,
    resolvedAt,
    resolution,
  },
})

const last = <T>(values: T[]): T | undefined => values.at(-1)

const pendingRequestId = (
  snapshot: LogoutPendingSnapshot | undefined,
): string | null =>
  snapshot?.status === 'pending' ? snapshot.tombstone.requestId : null

const signalWasAborted = (signal: AbortSignal | null): boolean =>
  signal?.aborted === true

test('the tombstone has exactly the four approved non-sensitive fields', () => {
  const tombstone = createLogoutPendingTombstone(
    'request-1',
    1_722_160_800_000,
  )

  assert.deepEqual(tombstone, {
    version: 1,
    requestId: 'request-1',
    initiatedAt: 1_722_160_800_000,
    retryCount: 0,
  })
  assert.deepEqual(Object.keys(tombstone).sort(), [
    'initiatedAt',
    'requestId',
    'retryCount',
    'version',
  ])
  assert.equal(Object.isFrozen(tombstone), true)

  const serialized = JSON.stringify(tombstone)
  for (const prohibited of [
    'cookie',
    'credential',
    'csrf',
    'digest',
    'expiry',
    'mcr',
    'name',
    'programme',
    'role',
    'scope',
    'session',
    'subject',
    'token',
  ]) {
    assert.doesNotMatch(serialized, new RegExp(prohibited, 'i'))
  }
})

test('the resolution watermark has exactly five bounded non-sensitive fields', () => {
  const serialized = serializeResolution(
    'resolved-request',
    123,
    456,
    'replacement-login',
  )
  const watermark = parseLogoutResolutionWatermark(serialized)

  assert.deepEqual(watermark, {
    version: 1,
    requestId: 'resolved-request',
    initiatedAt: 123,
    resolvedAt: 456,
    resolution: 'replacement-login',
  })
  assert.deepEqual(Object.keys(watermark ?? {}).sort(), [
    'initiatedAt',
    'requestId',
    'resolution',
    'resolvedAt',
    'version',
  ])
  assert.equal(Object.isFrozen(watermark), true)
  for (const prohibited of [
    'cookie',
    'credential',
    'csrf',
    'identity',
    'mcr',
    'programme',
    'role',
    'scope',
    'session',
    'subject',
    'token',
  ]) {
    assert.doesNotMatch(serialized, new RegExp(prohibited, 'i'))
  }
})

test('resolution watermark parsing is exact, bounded, and causal', () => {
  const valid = serializeResolution()
  const atCap = valid + ' '.repeat(
    LOGOUT_RESOLUTION_MAX_SERIALIZED_BYTES - Buffer.byteLength(valid),
  )
  assert.ok(parseLogoutResolutionWatermark(atCap))
  assert.equal(
    Buffer.byteLength(atCap),
    LOGOUT_RESOLUTION_MAX_SERIALIZED_BYTES,
  )
  assert.equal(parseLogoutResolutionWatermark(`${atCap} `), null)

  for (const malformed of [
    '',
    '{',
    '{}',
    JSON.stringify({
      ...(JSON.parse(valid) as Record<string, unknown>),
      csrfToken: 'not-allowed',
    }),
    serializeResolution('', 123, 456),
    serializeResolution('request-1', 457, 456),
    serializeResolution('request-1', -1, 456),
    serializeResolution(
      'request-1',
      123,
      8_640_000_000_000_001,
    ),
    JSON.stringify({
      version: 1,
      requestId: 'request-1',
      initiatedAt: 123,
      resolvedAt: 456,
      resolution: 'unknown',
    }),
  ]) {
    assert.equal(parseLogoutResolutionWatermark(malformed), null, malformed)
  }
})

test('strict parsing accepts safe boundary values without applying a TTL', () => {
  assert.deepEqual(parseLogoutPendingTombstone(serializePending('old', 0, 4)), {
    version: 1,
    requestId: 'old',
    initiatedAt: 0,
    retryCount: 4,
  })

  const storage = new MemoryStorage()
  storage.writeRaw(serializePending('old', 0, 0))
  assert.deepEqual(readLogoutPendingSnapshot(storage), {
    status: 'pending',
    tombstone: {
      version: 1,
      requestId: 'old',
      initiatedAt: 0,
      retryCount: 0,
    },
  })
})

test('strict parsing rejects malformed, non-exact, and unsafe tombstones', () => {
  const malformedValues: unknown[] = [
    '',
    '{',
    'null',
    '[]',
    '"pending"',
    '{}',
    JSON.stringify({
      version: 2,
      requestId: 'request-1',
      initiatedAt: 1,
      retryCount: 0,
    }),
    JSON.stringify({
      version: 1,
      requestId: 'request-1',
      initiatedAt: 1,
    }),
    JSON.stringify({
      version: 1,
      requestId: 'request-1',
      initiatedAt: 1,
      retryCount: 0,
      csrfToken: 'must-not-be-accepted',
    }),
    serializePending('', 1, 0),
    serializePending('contains a space', 1, 0),
    serializePending('x'.repeat(129), 1, 0),
    serializePending('request-1', -1, 0),
    serializePending('request-1', 1.5, 0),
    serializePending('request-1', 8_640_000_000_000_001, 0),
    serializePending('request-1', 1, -1),
    serializePending('request-1', 1, 5),
    serializePending('request-1', 1, 0.5),
  ]

  for (const malformed of malformedValues) {
    assert.equal(
      parseLogoutPendingTombstone(String(malformed)),
      null,
      String(malformed),
    )
  }
})

test('serialized-size validation accepts the cap and rejects cap plus one', () => {
  const valid = serializePending()
  const atCap = valid + ' '.repeat(
    LOGOUT_PENDING_MAX_SERIALIZED_BYTES - Buffer.byteLength(valid),
  )
  const aboveCap = `${atCap} `

  assert.ok(parseLogoutPendingTombstone(atCap))
  assert.equal(Buffer.byteLength(atCap), LOGOUT_PENDING_MAX_SERIALIZED_BYTES)
  assert.equal(parseLogoutPendingTombstone(aboveCap), null)

  const storage = new MemoryStorage()
  storage.writeRaw(aboveCap)
  assert.deepEqual(readLogoutPendingSnapshot(storage), {
    status: 'blocked',
    reason: 'oversized',
  })
})

test('non-null malformed markers and storage read failures fail closed', () => {
  const storage = new MemoryStorage()
  storage.writeRaw('{malformed')
  const malformed = readLogoutPendingSnapshot(storage)
  assert.deepEqual(malformed, { status: 'blocked', reason: 'malformed' })
  assert.equal(isLogoutPendingBlocked(malformed), true)

  storage.failRead = true
  const readFailure = readLogoutPendingSnapshot(storage)
  assert.deepEqual(readFailure, {
    status: 'blocked',
    reason: 'storage-read-failed',
  })
  assert.equal(isLogoutPendingBlocked(readFailure), true)

  const unavailable = readLogoutPendingSnapshot(null)
  assert.deepEqual(unavailable, {
    status: 'blocked',
    reason: 'storage-unavailable',
  })
  assert.equal(isLogoutPendingBlocked(unavailable), true)
  assert.equal(isLogoutPendingBlocked({ status: 'clear' }), false)
})

test('non-null invalid resolution metadata fails closed', () => {
  const storage = new MemoryStorage()
  storage.writeRaw(serializePending('pending-request', 123, 0))
  storage.writeResolutionRaw('{malformed')
  assert.deepEqual(readLogoutPendingSnapshot(storage), {
    status: 'blocked',
    reason: 'malformed',
  })

  storage.writeResolutionRaw(
    'x'.repeat(LOGOUT_RESOLUTION_MAX_SERIALIZED_BYTES + 1),
  )
  assert.deepEqual(readLogoutPendingSnapshot(storage), {
    status: 'blocked',
    reason: 'oversized',
  })
})

test('standalone reads give durable resolution precedence over stale replicas', () => {
  const storage = new MemoryStorage()
  storage.writeRaw(serializePending('resolved-request', 123, 2))
  storage.writeResolutionRaw(
    serializeResolution('resolved-request', 123, 456),
  )

  assert.deepEqual(readLogoutPendingSnapshot(storage), { status: 'clear' })
  assert.equal(storage.readRaw(), null)

  storage.writeRaw(serializePending('resolved-request', 123, 0))
  assert.deepEqual(readLogoutPendingSnapshot(storage), { status: 'clear' })
})

test('begin clamps above the durable resolution, including the same millisecond', () => {
  const storage = new MemoryStorage()
  storage.writeResolutionRaw(
    serializeResolution('request-a', 100, 500),
  )
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })

  assert.equal(store.begin('request-b', 500).status, 'applied')
  assert.equal(storage.readRaw(), serializePending('request-b', 501, 0))
  store.dispose()
})

test('begin fails closed when no timestamp exists above the watermark', () => {
  const storage = new MemoryStorage()
  storage.writeResolutionRaw(serializeResolution(
    'request-a',
    8_640_000_000_000_000,
    8_640_000_000_000_000,
  ))
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })

  const result = store.begin('request-b', 8_640_000_000_000_000)
  assert.equal(result.status, 'blocked')
  assert.equal(logoutPendingRequestId(result.snapshot), 'request-b')
  assert.equal(isLogoutPendingBlocked(store.read()), true)
  store.dispose()
})

test('begin persists canonically and rejects a reused ID with a new initiation', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })

  assert.equal(store.begin('request-1', 123).status, 'applied')
  assert.equal(store.begin('request-1', 123).status, 'unchanged')
  assert.equal(store.begin('request-1', 999).status, 'blocked')
  assert.equal(store.begin('request-2', 124).status, 'stale')
  assert.equal(storage.readRaw(), serializePending('request-1', 123, 0))
  store.dispose()
})

test('storage write failures and failed read-back never report an applied marker', () => {
  const throwingStorage = new MemoryStorage()
  throwingStorage.failWrite = true
  const throwingStore = createLogoutPendingStore({
    storage: throwingStorage,
    eventTarget: null,
    channelFactory: null,
  })
  const writeFailure = throwingStore.begin('request-1', 123)
  assert.equal(writeFailure.status, 'blocked')
  assert.deepEqual(writeFailure.snapshot, {
    status: 'blocked',
    reason: 'storage-write-failed',
  })
  assert.deepEqual(throwingStore.read(), {
    status: 'blocked',
    reason: 'storage-write-failed',
  })

  throwingStorage.failWrite = false
  assert.deepEqual(throwingStore.read(), {
    status: 'blocked',
    reason: 'storage-write-failed',
  })
  assert.equal(
    throwingStore.clearAfterSuccessfulLogin(writeFailure.snapshot).status,
    'applied',
  )
  assert.deepEqual(throwingStore.read(), { status: 'clear' })

  const noOpStorage = new MemoryStorage()
  noOpStorage.ignoreWrite = true
  const noOpStore = createLogoutPendingStore({
    storage: noOpStorage,
    eventTarget: null,
    channelFactory: null,
  })
  assert.equal(noOpStore.begin('request-1', 123).status, 'blocked')
  assert.equal(noOpStorage.readRaw(), null)
  assert.deepEqual(noOpStore.read(), {
    status: 'blocked',
    reason: 'storage-write-failed',
  })

  const reloadStorage = new MemoryStorage()
  reloadStorage.failWrite = true
  assert.deepEqual(readLogoutPendingSnapshot(reloadStorage), {
    status: 'blocked',
    reason: 'storage-write-failed',
  })

  throwingStore.dispose()
  noOpStore.dispose()
})

test('concurrent storage capability probes cannot delete each other', () => {
  const storage = new MemoryStorage()
  let nestedSnapshot: LogoutPendingSnapshot | null = null
  storage.onProbeRead = () => {
    nestedSnapshot = readLogoutPendingSnapshot(storage)
  }

  const outerSnapshot = readLogoutPendingSnapshot(storage)

  assert.deepEqual(nestedSnapshot, { status: 'clear' })
  assert.deepEqual(outerSnapshot, { status: 'clear' })
})

test('browser storage falls back to session storage for reload-safe markers', () => {
  const primary = new MemoryStorage()
  const fallback = new MemoryStorage()
  primary.failWrite = true
  let historyState: unknown = null
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      localStorage: primary,
      sessionStorage: fallback,
      history: {
        get state() {
          return historyState
        },
        replaceState(value: unknown) {
          historyState = value
        },
      },
    },
  })
  try {
    const first = createLogoutPendingStore({
      eventTarget: null,
      channelFactory: null,
    })
    assert.equal(first.begin('fallback-request', 123).status, 'applied')
    assert.equal(primary.readRaw(), null)
    assert.equal(
      fallback.readRaw(),
      serializePending('fallback-request', 123, 0),
    )

    const reloaded = createLogoutPendingStore({
      eventTarget: null,
      channelFactory: null,
    })
    assert.equal(
      logoutPendingRequestId(reloaded.read()),
      'fallback-request',
    )
    assert.equal(
      reloaded.clearAfterSuccessfulLogin(reloaded.read()).status,
      'applied',
    )
    assert.equal(fallback.readRaw(), null)
    first.dispose()
    reloaded.dispose()
  } finally {
    if (originalWindow) {
      Object.defineProperty(globalThis, 'window', originalWindow)
    } else {
      Reflect.deleteProperty(globalThis, 'window')
    }
  }
})

test('browser fallback replicas elect simultaneous distinct IDs deterministically', () => {
  const primary = new MemoryStorage()
  const fallback = new MemoryStorage()
  primary.writeRaw(serializePending('request-b', 100, 0))
  fallback.writeRaw(serializePending('request-a', 100, 0))
  let historyState: unknown = null
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      name: '',
      localStorage: primary,
      sessionStorage: fallback,
      history: {
        get state() {
          return historyState
        },
        replaceState(value: unknown) {
          historyState = value
        },
      },
    },
  })
  try {
    const store = createLogoutPendingStore({
      eventTarget: null,
      channelFactory: null,
    })
    assert.equal(logoutPendingRequestId(store.read()), 'request-a')
    assert.equal(primary.readRaw(), serializePending('request-a', 100, 0))
    assert.equal(fallback.readRaw(), serializePending('request-a', 100, 0))
    assert.equal(
      store.clearAfterSuccessfulLogin(store.read()).status,
      'applied',
    )
    store.dispose()
  } finally {
    if (originalWindow) {
      Object.defineProperty(globalThis, 'window', originalWindow)
    } else {
      Reflect.deleteProperty(globalThis, 'window')
    }
  }
})

test('clear browser reads heal the elected resolution across fallback replicas', () => {
  const primary = new MemoryStorage()
  const fallback = new MemoryStorage()
  const newestResolution = serializeResolution('request-a', 100, 300)
  primary.writeResolutionRaw(newestResolution)
  fallback.writeResolutionRaw(
    serializeResolution('request-b', 50, 100),
  )
  let historyState: unknown = null
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      name: '',
      localStorage: primary,
      sessionStorage: fallback,
      history: {
        get state() {
          return historyState
        },
        replaceState(value: unknown) {
          historyState = value
        },
      },
    },
  })
  try {
    assert.deepEqual(readLogoutPendingSnapshot(), { status: 'clear' })
    assert.equal(primary.readResolutionRaw(), newestResolution)
    assert.equal(fallback.readResolutionRaw(), newestResolution)

    primary.removeItem(LOGOUT_RESOLUTION_STORAGE_KEY)
    const store = createLogoutPendingStore({
      eventTarget: null,
      channelFactory: null,
    })
    const begun = store.begin('request-c', 150)
    assert.equal(begun.status, 'applied')
    assert.equal(
      begun.snapshot.status === 'pending'
        ? begun.snapshot.tombstone.initiatedAt
        : null,
      301,
    )
    assert.equal(store.clearIfMatching('request-c').status, 'applied')
    store.dispose()
  } finally {
    if (originalWindow) {
      Object.defineProperty(globalThis, 'window', originalWindow)
    } else {
      Reflect.deleteProperty(globalThis, 'window')
    }
  }
})

test('browser history state is the final reload-safe tombstone fallback', () => {
  const primary = new MemoryStorage()
  const fallback = new MemoryStorage()
  primary.failWrite = true
  fallback.failWrite = true
  let historyState: unknown = null
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      localStorage: primary,
      sessionStorage: fallback,
      history: {
        get state() {
          return historyState
        },
        replaceState(value: unknown) {
          historyState = value
        },
      },
    },
  })
  try {
    const store = createLogoutPendingStore({
      eventTarget: null,
      channelFactory: null,
    })
    assert.equal(store.begin('history-fallback', 123).status, 'applied')
    assert.equal(
      logoutPendingRequestId(store.read()),
      'history-fallback',
    )
    store.dispose()
  } finally {
    if (originalWindow) {
      Object.defineProperty(globalThis, 'window', originalWindow)
    } else {
      Reflect.deleteProperty(globalThis, 'window')
    }
  }
})

test('retry metadata updates only the matching marker', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  store.begin('request-1', 123)

  assert.equal(store.recordRetry('request-2', 1).status, 'stale')
  assert.equal(store.recordRetry('request-1', 1).status, 'applied')
  assert.equal(store.recordRetry('request-1', 1).status, 'unchanged')
  assert.equal(store.recordRetry('request-1', 5).status, 'blocked')
  assert.equal(storage.readRaw(), serializePending('request-1', 123, 1))
  store.dispose()
})

test('confirmation clears only a matching ID and watermarks failed removal', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  store.begin('request-1', 123)

  assert.equal(store.clearIfMatching('request-2').status, 'stale')
  assert.ok(storage.readRaw())
  assert.equal(store.clearIfMatching('request-1').status, 'applied')
  assert.equal(storage.readRaw(), null)
  assert.equal(store.clearIfMatching('request-1').status, 'unchanged')

  store.begin('request-3', 124)
  storage.ignoreRemove = true
  assert.equal(store.clearIfMatching('request-3').status, 'applied')
  assert.ok(storage.readRaw())
  assert.deepEqual(store.read(), { status: 'clear' })
  storage.ignoreRemove = false
  storage.failRemove = true
  assert.equal(store.clearIfMatching('request-3').status, 'unchanged')
  assert.ok(storage.readRaw())
  store.dispose()
})

test('successful-login recovery clears the captured pending marker only', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  store.begin('request-1', 123)
  const captured = store.read()

  storage.writeRaw(serializePending('request-2', 124, 0))
  assert.equal(store.clearAfterSuccessfulLogin(captured).status, 'stale')
  assert.equal(storage.readRaw(), serializePending('request-2', 124, 0))

  const current = store.read()
  assert.equal(store.clearAfterSuccessfulLogin(current).status, 'applied')
  assert.equal(storage.readRaw(), null)
  store.dispose()
})

test('successful-login recovery clears only the exact captured malformed value', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  storage.writeRaw('{first-malformed')
  const captured = store.read()

  storage.writeRaw('{newer-malformed')
  assert.equal(store.clearAfterSuccessfulLogin(captured).status, 'stale')
  assert.equal(storage.readRaw(), '{newer-malformed')

  const current = store.read()
  assert.equal(store.clearAfterSuccessfulLogin(current).status, 'applied')
  assert.equal(storage.readRaw(), null)
  store.dispose()
})

test('successful-login recovery handles an unchanged oversized marker', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  storage.writeRaw('x'.repeat(LOGOUT_PENDING_MAX_SERIALIZED_BYTES + 1))
  const captured = store.read()

  assert.deepEqual(captured, { status: 'blocked', reason: 'oversized' })
  assert.equal(store.clearAfterSuccessfulLogin(captured).status, 'applied')
  assert.equal(storage.readRaw(), null)
  store.dispose()
})

test('successful login clears a matching fence behind corrupted durable state', () => {
  for (const corrupted of [
    '{malformed',
    'x'.repeat(LOGOUT_PENDING_MAX_SERIALIZED_BYTES + 1),
  ]) {
    const storage = new MemoryStorage()
    const store = createLogoutPendingStore({
      storage,
      eventTarget: null,
      channelFactory: null,
    })
    store.begin('logout-a', 123)
    storage.writeRaw(corrupted)
    const captured = store.read()

    assert.equal(logoutPendingRequestId(captured), 'logout-a')
    assert.equal(store.clearAfterSuccessfulLogin(captured).status, 'applied')
    assert.deepEqual(store.read(), { status: 'clear' })
    store.dispose()
  }
})

test('corrupted-state recovery cannot remove a newer runtime fence', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  store.begin('logout-a', 123)
  storage.writeRaw('{same-corrupted-value')
  const captured = store.read()
  store.retainRuntimeFence('logout-b')

  assert.equal(store.clearAfterSuccessfulLogin(captured).status, 'stale')
  assert.equal(storage.readRaw(), '{same-corrupted-value')
  assert.equal(logoutPendingRequestId(store.read()), 'logout-b')
  store.dispose()
})

test('successful login recovers the matching fence after a transient read failure', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  store.begin('logout-a', 123)
  storage.removeItem(LOGOUT_PENDING_STORAGE_KEY)
  storage.failRead = true
  const captured = store.read()
  storage.failRead = false

  assert.equal(logoutPendingRequestId(captured), 'logout-a')
  assert.equal(store.clearAfterSuccessfulLogin(captured).status, 'applied')
  assert.deepEqual(store.read(), { status: 'clear' })
  store.dispose()
})

test('unverifiable blocked and clear captures never remove a newer marker', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  const clearCapture = store.read()
  storage.writeRaw(serializePending('newer', 124, 0))
  store.clearAfterSuccessfulLogin(clearCapture)
  assert.equal(storage.readRaw(), serializePending('newer', 124, 0))

  const unreadableStorage = new MemoryStorage()
  const unreadableStore = createLogoutPendingStore({
    storage: unreadableStorage,
    eventTarget: null,
    channelFactory: null,
  })
  unreadableStorage.failRead = true
  const failedCapture = unreadableStore.read()
  unreadableStorage.failRead = false
  unreadableStorage.writeRaw(serializePending('later', 125, 0))
  assert.equal(
    unreadableStore.clearAfterSuccessfulLogin(failedCapture).status,
    'stale',
  )
  assert.equal(
    unreadableStorage.readRaw(),
    serializePending('later', 125, 0),
  )
  store.dispose()
  unreadableStore.dispose()
})

test('raw marker removal stays fail-closed before any notification arrives', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  store.begin('logout-a', 123)
  const loginCapture = store.read()
  storage.removeItem(LOGOUT_PENDING_STORAGE_KEY)

  const runtimeFence = store.read()
  assert.deepEqual(runtimeFence, {
    status: 'blocked',
    reason: 'unconfirmed-clear',
  })
  assert.equal(logoutPendingRequestId(runtimeFence), 'logout-a')
  assert.equal(isLogoutPendingBlocked(store.read()), true)
  assert.equal(
    store.releaseRuntimeFenceIfMatching('other-logout').status,
    'stale',
  )
  assert.equal(isLogoutPendingBlocked(store.read()), true)

  const recovered = store.clearAfterSuccessfulLogin(loginCapture)
  assert.equal(recovered.status, 'applied')
  assert.deepEqual(store.read(), { status: 'clear' })
  store.dispose()
})

test('matching login release stays clear after delayed storage and channel events', () => {
  const storage = new MemoryStorage()
  const target = new EventTarget()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: target,
    channelFactory: hub.create,
  })
  const observed: LogoutPendingSnapshot[] = []
  store.subscribe((snapshot) => observed.push(snapshot))
  store.begin('logout-a', 123)
  const loginCapture = store.read()
  storage.removeItem(LOGOUT_PENDING_STORAGE_KEY)

  assert.equal(store.clearAfterSuccessfulLogin(loginCapture).status, 'applied')
  assert.deepEqual(store.read(), { status: 'clear' })

  const delayedStorageEvent = new Event('storage')
  Object.defineProperty(delayedStorageEvent, 'key', {
    value: LOGOUT_PENDING_STORAGE_KEY,
  })
  target.dispatchEvent(delayedStorageEvent)
  hub.broadcast({ type: 'logout-pending-changed' })

  assert.deepEqual(last(observed), { status: 'clear' })
  assert.deepEqual(store.read(), { status: 'clear' })
  store.dispose()
})

test('cross-tab login release requires the exact latest logout request ID', () => {
  const storage = new MemoryStorage()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: null,
  })
  storage.writeRaw(serializePending('logout-a', 123, 0))
  store.read()
  storage.writeRaw(serializePending('logout-b', 124, 0))
  store.read()
  storage.removeItem(LOGOUT_PENDING_STORAGE_KEY)

  const staleRelease = store.releaseRuntimeFenceAfterLogin('logout-a')
  assert.equal(staleRelease.status, 'stale')
  assert.equal(logoutPendingRequestId(store.read()), 'logout-b')
  assert.equal(
    store.releaseRuntimeFenceAfterLogin('logout-b').status,
    'applied',
  )
  assert.deepEqual(store.read(), { status: 'clear' })
  store.dispose()
})

test('same-tab custom events converge by re-reading durable storage', () => {
  const storage = new MemoryStorage()
  const target = new EventTarget()
  const first = createLogoutPendingStore({
    storage,
    eventTarget: target,
    channelFactory: null,
  })
  const second = createLogoutPendingStore({
    storage,
    eventTarget: target,
    channelFactory: null,
  })
  const observed: LogoutPendingSnapshot[] = []
  second.subscribe((snapshot) => observed.push(snapshot))

  first.begin('request-1', 123)
  assert.deepEqual(last(observed), {
    status: 'pending',
    tombstone: {
      version: 1,
      requestId: 'request-1',
      initiatedAt: 123,
      retryCount: 0,
    },
  })

  first.clearIfMatching('request-1')
  assert.deepEqual(last(observed), { status: 'clear' })
  first.dispose()
  second.dispose()
})

test('generic BroadcastChannel signals contain no state authority and force a durable reread', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const first = createLogoutPendingStore({
    storage,
    eventTarget: new EventTarget(),
    channelFactory: hub.create,
  })
  const second = createLogoutPendingStore({
    storage,
    eventTarget: new EventTarget(),
    channelFactory: hub.create,
  })
  const observed: LogoutPendingSnapshot[] = []
  second.subscribe((snapshot) => observed.push(snapshot))

  first.begin('request-current', 123)
  assert.equal(pendingRequestId(last(observed)), 'request-current')

  storage.writeRaw(serializePending('durable-wins', 124, 2))
  hub.broadcast({
    type: 'logout-pending-changed',
    tombstone: {
      version: 1,
      requestId: 'stale-payload',
      initiatedAt: 1,
      retryCount: 0,
      csrfToken: 'untrusted',
    },
  })
  assert.equal(pendingRequestId(last(observed)), 'request-current')

  hub.broadcast({ type: 'logout-pending-changed' })
  assert.equal(pendingRequestId(last(observed)), 'durable-wins')
  first.dispose()
  second.dispose()
})

test('failed marker persistence propagates a validated durable fence to peers', () => {
  const failingStorage = new MemoryStorage()
  const peerStorage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const first = createLogoutPendingStore({
    storage: failingStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  const peer = createLogoutPendingStore({
    storage: peerStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  failingStorage.failWrite = true

  const failed = first.begin('failed-request', 123)

  assert.equal(failed.status, 'blocked')
  assert.equal(logoutPendingRequestId(failed.snapshot), 'failed-request')
  assert.equal(
    peerStorage.readRaw(),
    serializePending('failed-request', 123, 0),
  )
  assert.equal(logoutPendingRequestId(peer.read()), 'failed-request')
  first.dispose()
  peer.dispose()
})

test('proof-positive confirmation clears matching peer state with context', () => {
  const firstStorage = new MemoryStorage()
  const peerStorage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const first = createLogoutPendingStore({
    storage: firstStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  const peer = createLogoutPendingStore({
    storage: peerStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  let resolvedContext:
    | { resolvedRequestId: string; resolution: string }
    | undefined
  peer.subscribe((_snapshot, context) => {
    if (context) {
      resolvedContext = context
    }
  })

  first.begin('confirmed-request', 123)
  assert.equal(logoutPendingRequestId(peer.read()), 'confirmed-request')
  assert.equal(first.clearIfMatching('confirmed-request').status, 'applied')

  assert.deepEqual(peer.read(), { status: 'clear' })
  assert.deepEqual(resolvedContext, {
    resolvedRequestId: 'confirmed-request',
    resolution: 'confirmed',
  })
  first.dispose()
  peer.dispose()
})

test('pending election is ascending by initiation and ID in either delivery order', () => {
  for (const messages of [
    [
      { type: 'logout-pending-state', tombstone: {
        version: 1, requestId: 'request-b', initiatedAt: 100, retryCount: 0,
      } },
      { type: 'logout-pending-state', tombstone: {
        version: 1, requestId: 'request-a', initiatedAt: 100, retryCount: 0,
      } },
    ],
    [
      { type: 'logout-pending-state', tombstone: {
        version: 1, requestId: 'request-a', initiatedAt: 100, retryCount: 0,
      } },
      { type: 'logout-pending-state', tombstone: {
        version: 1, requestId: 'request-b', initiatedAt: 100, retryCount: 0,
      } },
    ],
  ]) {
    const storage = new MemoryStorage()
    const hub = new FakeBroadcastHub()
    const store = createLogoutPendingStore({
      storage,
      eventTarget: null,
      channelFactory: hub.create,
    })
    for (const message of messages) {
      hub.broadcast(message)
    }
    assert.equal(logoutPendingRequestId(store.read()), 'request-a')
    store.dispose()
  }

  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  hub.broadcast({
    type: 'logout-pending-state',
    tombstone: {
      version: 1,
      requestId: 'later',
      initiatedAt: 101,
      retryCount: 0,
    },
  })
  hub.broadcast({
    type: 'logout-pending-state',
    tombstone: {
      version: 1,
      requestId: 'earlier',
      initiatedAt: 100,
      retryCount: 0,
    },
  })
  assert.equal(logoutPendingRequestId(store.read()), 'earlier')
  store.dispose()
})

test('same pending identity keeps max retry and conflicting initiation fails closed', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  hub.broadcast({
    type: 'logout-pending-state',
    tombstone: {
      version: 1,
      requestId: 'same',
      initiatedAt: 100,
      retryCount: 3,
    },
  })
  hub.broadcast({
    type: 'logout-pending-state',
    tombstone: {
      version: 1,
      requestId: 'same',
      initiatedAt: 100,
      retryCount: 1,
    },
  })
  assert.equal(storage.readRaw(), serializePending('same', 100, 3))

  hub.broadcast({
    type: 'logout-pending-state',
    tombstone: {
      version: 1,
      requestId: 'same',
      initiatedAt: 99,
      retryCount: 4,
    },
  })
  assert.equal(storage.readRaw(), serializePending('same', 100, 3))
  assert.equal(isLogoutPendingBlocked(store.read()), true)
  store.dispose()
})

test('a valid resolution received before election clears an older distinct candidate', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  store.begin('candidate-b', 100)
  let context:
    | { resolvedRequestId: string; resolution: string }
    | undefined
  store.subscribe((_snapshot, nextContext) => {
    context = nextContext ?? context
  })

  hub.broadcast(resolutionMessage('candidate-a', 100, 101))

  assert.deepEqual(store.read(), { status: 'clear' })
  assert.deepEqual(context, {
    resolvedRequestId: 'candidate-b',
    resolution: 'confirmed',
  })
  store.dispose()
})

test('A resolution history suppresses late A state after newer B begins', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  hub.broadcast(resolutionMessage('request-a', 100, 200))
  store.begin('request-b', 200)
  const pendingB = store.read()
  assert.equal(pendingRequestId(pendingB), 'request-b')
  assert.equal(
    pendingB.status === 'pending' ? pendingB.tombstone.initiatedAt : null,
    201,
  )

  hub.broadcast({
    type: 'logout-pending-state',
    tombstone: {
      version: 1,
      requestId: 'request-a',
      initiatedAt: 100,
      retryCount: 4,
    },
  })
  assert.equal(logoutPendingRequestId(store.read()), 'request-b')
  store.dispose()
})

test('matching but corrupted or causally conflicting resolution is inert', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  store.begin('request-a', 100)

  hub.broadcast({
    ...resolutionMessage('request-a', 100, 101),
    csrfToken: 'not-allowed',
  })
  hub.broadcast(resolutionMessage('request-a', 99, 101))

  assert.equal(logoutPendingRequestId(store.read()), 'request-a')
  assert.equal(storage.readResolutionRaw(), null)
  store.dispose()
})

test('a stale resolved signal cannot clear a newer peer marker', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  store.begin('newer-request', 124)

  hub.broadcast(resolutionMessage('older-request', 100, 123))

  assert.equal(logoutPendingRequestId(store.read()), 'newer-request')
  assert.equal(
    storage.readRaw(),
    serializePending('newer-request', 124, 0),
  )
  store.dispose()
})

test('a stale blocked signal cannot relatch a resolved request', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  store.begin('resolved-request', 123)
  assert.equal(store.clearIfMatching('resolved-request').status, 'applied')

  hub.broadcast({
    type: 'logout-pending-blocked',
    requestId: 'resolved-request',
  })

  assert.deepEqual(store.read(), { status: 'clear' })
  assert.equal(storage.readRaw(), null)
  store.dispose()
})

test('ordered blocked metadata cannot resurrect A after A then B resolve', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  hub.broadcast(resolutionMessage('request-a', 100, 200))
  store.begin('request-b', 201)
  hub.broadcast(resolutionMessage('request-b', 201, 300))
  assert.deepEqual(store.read(), { status: 'clear' })

  hub.broadcast({
    type: 'logout-pending-blocked',
    requestId: 'request-a',
    initiatedAt: 100,
  })

  assert.deepEqual(store.read(), { status: 'clear' })
  store.dispose()
})

test('sync replay resolves a marker even when the original signal was missed', () => {
  const firstStorage = new MemoryStorage()
  const lateStorage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const first = createLogoutPendingStore({
    storage: firstStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  first.begin('resolved-before-mount', 123)
  assert.equal(
    first.clearIfMatching('resolved-before-mount').status,
    'applied',
  )
  lateStorage.writeRaw(serializePending('resolved-before-mount', 123, 0))

  const lateStore = createLogoutPendingStore({
    storage: lateStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })

  assert.deepEqual(lateStore.read(), { status: 'clear' })
  first.dispose()
  lateStore.dispose()
})

test('durable replacement-login watermark converges without a channel signal', () => {
  const storage = new MemoryStorage()
  const target = new EventTarget()
  const first = createLogoutPendingStore({
    storage,
    eventTarget: target,
    channelFactory: null,
  })
  const peer = createLogoutPendingStore({
    storage,
    eventTarget: target,
    channelFactory: null,
  })
  const observed: LogoutPendingSnapshot[] = []
  const observedContexts: Array<{
    resolvedRequestId: string
    resolution: string
  }> = []
  peer.subscribe((snapshot, context) => {
    observed.push(snapshot)
    if (context) {
      observedContexts.push(context)
    }
  })
  first.begin('replacement-login-request', 123)
  const captured = first.read()
  storage.ignoreRemove = true

  assert.equal(first.clearAfterSuccessfulLogin(captured).status, 'applied')
  assert.ok(storage.readRaw())
  assert.ok(storage.readResolutionRaw())
  assert.deepEqual(last(observed), { status: 'clear' })
  assert.deepEqual(last(observedContexts), {
    resolvedRequestId: 'replacement-login-request',
    resolution: 'replacement-login',
  })
  assert.deepEqual(peer.read(), { status: 'clear' })
  first.dispose()
  peer.dispose()
})

test('proof-positive confirmation broadcasts while failed persistence stays blocked', () => {
  const failingStorage = new MemoryStorage()
  const peerStorage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const first = createLogoutPendingStore({
    storage: failingStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  const peer = createLogoutPendingStore({
    storage: peerStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  failingStorage.failWrite = true
  const begun = first.begin('confirmed-with-storage-failure', 123)
  assert.equal(begun.status, 'blocked')
  assert.equal(
    logoutPendingRequestId(peer.read()),
    'confirmed-with-storage-failure',
  )

  const confirmed = first.clearIfMatching(
    'confirmed-with-storage-failure',
  )

  assert.equal(confirmed.status, 'applied')
  assert.equal(isLogoutPendingBlocked(first.read()), true)
  assert.equal(failingStorage.readResolutionRaw(), null)
  assert.deepEqual(peer.read(), { status: 'clear' })
  first.dispose()
  peer.dispose()
})

test('recovered persistence cannot replace a newer in-memory resolution', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  const initiatedAt = 8_000_000_000_000_000
  storage.failWrite = true
  assert.equal(store.begin('request-a', initiatedAt).status, 'blocked')
  assert.equal(store.clearIfMatching('request-a').status, 'applied')

  const proofMessage = hub.messages.findLast((message) =>
    Boolean(
      message
      && typeof message === 'object'
      && (message as { type?: unknown }).type === 'logout-pending-resolved',
    )
  ) as { watermark: LogoutResolutionWatermark } | undefined
  assert.ok(proofMessage)
  assert.equal(proofMessage.watermark.requestId, 'request-a')

  storage.failWrite = false
  hub.broadcast({
    type: 'logout-pending-resolved',
    watermark: {
      ...proofMessage.watermark,
      resolution: 'replacement-login',
    },
  })
  assert.equal(storage.readResolutionRaw(), null)

  hub.broadcast(resolutionMessage(
    'request-b',
    0,
    initiatedAt - 1,
  ))
  assert.deepEqual(
    parseLogoutResolutionWatermark(storage.readResolutionRaw() ?? ''),
    proofMessage.watermark,
  )

  hub.broadcast({
    type: 'logout-pending-state',
    tombstone: {
      version: 1,
      requestId: 'request-a',
      initiatedAt,
      retryCount: LOGOUT_MAX_TOTAL_ATTEMPTS,
    },
  })
  assert.deepEqual(store.read(), { status: 'clear' })
  assert.equal(storage.readRaw(), null)
  store.dispose()
})

test('equal-order resolution ambiguity stays blocked until durable state is coherent', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  const coherentResolution = serializeResolution(
    'request-a',
    100,
    200,
  )
  hub.broadcast(resolutionMessage('request-a', 100, 200))
  assert.equal(storage.readResolutionRaw(), coherentResolution)

  const conflictingResolution = serializeResolution(
    'request-a',
    99,
    200,
  )
  storage.writeResolutionRaw(conflictingResolution)
  assert.deepEqual(store.read(), {
    status: 'blocked',
    reason: 'malformed',
  })
  assert.equal(store.begin('request-b', 201).status, 'blocked')
  assert.equal(storage.readRaw(), null)
  assert.equal(storage.readResolutionRaw(), conflictingResolution)

  hub.broadcast({
    type: 'logout-pending-state',
    tombstone: {
      version: 1,
      requestId: 'request-a',
      initiatedAt: 100,
      retryCount: 0,
    },
  })
  hub.broadcast(resolutionMessage('request-c', 0, 300))
  assert.deepEqual(store.read(), {
    status: 'blocked',
    reason: 'malformed',
  })
  assert.equal(storage.readRaw(), null)
  assert.equal(storage.readResolutionRaw(), conflictingResolution)

  storage.writeResolutionRaw(coherentResolution)
  assert.deepEqual(store.read(), { status: 'clear' })
  hub.broadcast({
    type: 'logout-pending-state',
    tombstone: {
      version: 1,
      requestId: 'request-a',
      initiatedAt: 100,
      retryCount: 0,
    },
  })
  assert.deepEqual(store.read(), { status: 'clear' })
  assert.equal(storage.readRaw(), null)
  store.dispose()
})

test('proof-positive fallback broadcasts only the monotonic resolution winner', () => {
  const storage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  const initiatedAt = 8_000_000_000_000_000
  const newestResolution = serializeResolution(
    'request-a',
    initiatedAt,
    initiatedAt,
  )
  storage.writeResolutionRaw(newestResolution)
  const store = createLogoutPendingStore({
    storage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  storage.failWrite = true
  const blocked = store.retainRuntimeFence('request-b')
  assert.equal(logoutPendingRequestId(blocked), 'request-b')
  hub.messages.splice(0)

  assert.equal(store.clearIfMatching('request-b').status, 'applied')

  const published = hub.messages.findLast((message) =>
    Boolean(
      message
      && typeof message === 'object'
      && (message as { type?: unknown }).type === 'logout-pending-resolved',
    )
  ) as { watermark: LogoutResolutionWatermark } | undefined
  assert.ok(published)
  assert.deepEqual(
    published.watermark,
    parseLogoutResolutionWatermark(newestResolution),
  )
  assert.equal(isLogoutPendingBlocked(store.read()), true)
  store.dispose()
})

test('sync replay sends the monotonic watermark before newer pending state', () => {
  const firstStorage = new MemoryStorage()
  const lateStorage = new MemoryStorage()
  const hub = new FakeBroadcastHub()
  firstStorage.writeResolutionRaw(
    serializeResolution('request-a', 100, 200),
  )
  firstStorage.writeRaw(serializePending('request-b', 201, 0))
  const first = createLogoutPendingStore({
    storage: firstStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })
  hub.messages.splice(0)

  const late = createLogoutPendingStore({
    storage: lateStorage,
    eventTarget: null,
    channelFactory: hub.create,
  })

  const replayTypes = hub.messages
    .map((message) =>
      message && typeof message === 'object'
        ? (message as { type?: unknown }).type
        : null
    )
  assert.ok(
    replayTypes.indexOf('logout-pending-resolved')
      < replayTypes.indexOf('logout-pending-state'),
  )
  assert.equal(logoutPendingRequestId(late.read()), 'request-b')
  first.dispose()
  late.dispose()
})

test('storage events ignore stale newValue payloads and reread the key', () => {
  const storage = new MemoryStorage()
  const target = new EventTarget()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: target,
    channelFactory: null,
  })
  const observed: LogoutPendingSnapshot[] = []
  store.subscribe((snapshot) => observed.push(snapshot))
  storage.writeRaw(serializePending('durable-current', 123, 0))

  const storageEvent = new Event('storage')
  Object.defineProperties(storageEvent, {
    key: { value: LOGOUT_PENDING_STORAGE_KEY },
    newValue: { value: serializePending('stale-payload', 1, 0) },
  })
  target.dispatchEvent(storageEvent)

  assert.equal(pendingRequestId(last(observed)), 'durable-current')
  store.dispose()
})

test('unrelated storage and channel events do not mutate pending state', () => {
  const storage = new MemoryStorage()
  const target = new EventTarget()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: target,
    channelFactory: hub.create,
  })
  let notificationCount = 0
  store.subscribe(() => {
    notificationCount += 1
  })

  const unrelatedStorageEvent = new Event('storage')
  Object.defineProperty(unrelatedStorageEvent, 'key', { value: 'other-key' })
  target.dispatchEvent(unrelatedStorageEvent)
  hub.broadcast({ type: 'unrelated' })
  assert.equal(notificationCount, 0)

  target.dispatchEvent(new Event(LOGOUT_PENDING_CHANGED_EVENT))
  assert.equal(notificationCount, 1)
  store.dispose()
})

test('disposed stores stop observing same-tab, storage, and channel signals', () => {
  const storage = new MemoryStorage()
  const target = new EventTarget()
  const hub = new FakeBroadcastHub()
  const store = createLogoutPendingStore({
    storage,
    eventTarget: target,
    channelFactory: hub.create,
  })
  let notificationCount = 0
  store.subscribe(() => {
    notificationCount += 1
  })
  store.dispose()

  target.dispatchEvent(new Event(LOGOUT_PENDING_CHANGED_EVENT))
  const storageEvent = new Event('storage')
  Object.defineProperty(storageEvent, 'key', {
    value: LOGOUT_PENDING_STORAGE_KEY,
  })
  target.dispatchEvent(storageEvent)
  hub.broadcast({ type: 'logout-pending-changed' })
  assert.equal(notificationCount, 0)
})

test('nominal automatic retry offsets are 0, 1, 3, and 7 seconds', async () => {
  const scheduler = new FakeScheduler()
  const attempts: Array<{ at: number; retryCount: number }> = []
  const persistedCounts: number[] = []
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    recordAttempt: (_requestId, retryCount) => {
      persistedCounts.push(retryCount)
      return true
    },
    attempt: async ({ retryCount }) => {
      attempts.push({ at: scheduler.now, retryCount })
      return 'retryable'
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  await flushAsync()
  scheduler.advanceBy(1_000)
  await flushAsync()
  scheduler.advanceBy(2_000)
  await flushAsync()
  scheduler.advanceBy(4_000)
  await flushAsync()
  scheduler.advanceBy(60_000)
  await flushAsync()

  assert.deepEqual(attempts, [
    { at: 0, retryCount: 1 },
    { at: 1_000, retryCount: 2 },
    { at: 3_000, retryCount: 3 },
    { at: 7_000, retryCount: 4 },
  ])
  assert.deepEqual(persistedCounts, [1, 2, 3, 4])
  assert.deepEqual(LOGOUT_RETRY_DELAYS_MS, [1_000, 2_000, 4_000])
  assert.equal(LOGOUT_MAX_TOTAL_ATTEMPTS, 4)
  assert.equal(coordinator.getSnapshot().status, 'unconfirmed')
  assert.equal(coordinator.getSnapshot().reason, 'exhausted')
  assert.equal(coordinator.getSnapshot().canRetry, false)
  assert.equal(coordinator.getSnapshot().proofAvailable, false)
  assert.equal(scheduler.pendingCount, 0)
  coordinator.dispose()
})

test('confirmed success cancels retries and releases the memory-only proof', async () => {
  const scheduler = new FakeScheduler()
  let attempts = 0
  const coordinator = createLogoutRetryCoordinator<object>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async () => {
      attempts += 1
      return 'confirmed'
    },
  })

  const proof = { csrf: 'memory-only' }
  coordinator.start({ requestId: 'request-1', proof })
  await flushAsync()

  assert.equal(attempts, 1)
  assert.equal(coordinator.getSnapshot().status, 'confirmed')
  assert.equal(coordinator.getSnapshot().proofAvailable, false)
  assert.equal(coordinator.getSnapshot().canRetry, false)
  assert.equal(scheduler.pendingCount, 0)
  coordinator.dispose()
})

test('controlled unconfirmed responses remain pending without automatic retry', async () => {
  const scheduler = new FakeScheduler()
  let attempts = 0
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async () => {
      attempts += 1
      return 'unconfirmed'
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  await flushAsync()
  scheduler.advanceBy(60_000)
  await flushAsync()

  assert.equal(attempts, 1)
  assert.equal(coordinator.getSnapshot().status, 'unconfirmed')
  assert.equal(coordinator.getSnapshot().reason, 'server-unconfirmed')
  assert.equal(coordinator.getSnapshot().canRetry, false)
  assert.equal(coordinator.getSnapshot().proofAvailable, false)
  assert.equal(scheduler.pendingCount, 0)
  coordinator.dispose()
})

test('error classification separates retryable from terminal failures', async () => {
  const retryScheduler = new FakeScheduler()
  const retrying = createLogoutRetryCoordinator<string>({
    scheduler: retryScheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async () => {
      throw new Error('network failure')
    },
  })
  retrying.start({ requestId: 'retryable', proof: 'memory-proof' })
  await flushAsync()
  assert.equal(retrying.getSnapshot().status, 'waiting')
  assert.equal(retrying.getSnapshot().nextRetryDelayMs, 1_000)
  assert.equal(retryScheduler.pendingCount, 1)

  const terminalScheduler = new FakeScheduler()
  const terminal = createLogoutRetryCoordinator<string>({
    scheduler: terminalScheduler,
    isCurrent: () => true,
    classifyError: () => 'unconfirmed',
    attempt: async () => {
      throw new Error('controlled failure')
    },
  })
  terminal.start({ requestId: 'terminal', proof: 'memory-proof' })
  await flushAsync()
  assert.equal(terminal.getSnapshot().status, 'unconfirmed')
  assert.equal(terminal.getSnapshot().proofAvailable, false)
  assert.equal(terminalScheduler.pendingCount, 0)

  retrying.dispose()
  terminal.dispose()
})

test('same-operation staleness releases an in-flight proof and controller', async () => {
  const scheduler = new FakeScheduler()
  const activeAttempt = deferred<LogoutAttemptResult>()
  let current = true
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => current,
    classifyError: () => 'retryable',
    attempt: async () => activeAttempt.promise,
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  assert.equal(coordinator.getSnapshot().inFlight, true)
  current = false
  activeAttempt.resolve('retryable')
  await flushAsync()

  assert.equal(coordinator.getSnapshot().status, 'cancelled')
  assert.equal(coordinator.getSnapshot().reason, 'stale')
  assert.equal(coordinator.getSnapshot().inFlight, false)
  assert.equal(coordinator.getSnapshot().proofAvailable, false)
  assert.equal(coordinator.getSnapshot().canRetry, false)
  assert.equal(scheduler.pendingCount, 0)
  coordinator.dispose()
})

test('a stale transport outcome is terminal and cannot schedule another attempt', async () => {
  const scheduler = new FakeScheduler()
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async () => 'stale',
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  await flushAsync()

  assert.equal(coordinator.getSnapshot().status, 'cancelled')
  assert.equal(coordinator.getSnapshot().reason, 'stale')
  assert.equal(coordinator.getSnapshot().proofAvailable, false)
  assert.equal(scheduler.pendingCount, 0)
  coordinator.dispose()
})

test('explicit retry brings backoff forward and trigger storms stay one-in-flight', async () => {
  const scheduler = new FakeScheduler()
  const outcomes: LogoutAttemptResult[] = ['retryable', 'confirmed']
  let attempts = 0
  const secondAttempt = deferred<LogoutAttemptResult>()
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async () => {
      attempts += 1
      if (attempts === 1) {
        return outcomes[0] as LogoutAttemptResult
      }
      return secondAttempt.promise
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  await flushAsync()
  assert.equal(scheduler.pendingCount, 1)
  assert.equal(coordinator.requestExplicitRetry('request-1'), true)
  assert.equal(coordinator.requestExplicitRetry('request-1'), false)
  assert.equal(coordinator.notifyOnline('request-1'), false)
  assert.equal(attempts, 2)
  assert.equal(scheduler.pendingCount, 0)

  secondAttempt.resolve('confirmed')
  await flushAsync()
  assert.equal(coordinator.getSnapshot().status, 'confirmed')
  assert.equal(attempts, 2)
  coordinator.dispose()
})

test('offline start consumes no attempt and one online trigger starts it', async () => {
  const scheduler = new FakeScheduler()
  let online = false
  const activeAttempt = deferred<LogoutAttemptResult>()
  let attempts = 0
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isOnline: () => online,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async () => {
      attempts += 1
      return activeAttempt.promise
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  await flushAsync()
  assert.equal(attempts, 0)
  assert.equal(coordinator.getSnapshot().reason, 'offline')

  online = true
  assert.equal(coordinator.notifyOnline('request-1'), true)
  assert.equal(coordinator.notifyOnline('request-1'), false)
  assert.equal(attempts, 1)
  activeAttempt.resolve('confirmed')
  await flushAsync()
  assert.equal(coordinator.getSnapshot().status, 'confirmed')
  coordinator.dispose()
})

test('going offline during backoff defers without spending another attempt', async () => {
  const scheduler = new FakeScheduler()
  let online = true
  const outcomes: LogoutAttemptResult[] = ['retryable', 'confirmed']
  const attempts: number[] = []
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isOnline: () => online,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async ({ retryCount }) => {
      attempts.push(retryCount)
      return outcomes.shift() ?? 'confirmed'
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  await flushAsync()
  online = false
  scheduler.advanceBy(1_000)
  await flushAsync()
  assert.deepEqual(attempts, [1])
  assert.equal(coordinator.getSnapshot().reason, 'offline')

  online = true
  assert.equal(coordinator.notifyOnline('request-1'), true)
  await flushAsync()
  assert.deepEqual(attempts, [1, 2])
  assert.equal(coordinator.getSnapshot().status, 'confirmed')
  coordinator.dispose()
})

test('explicit and online signals are coalesced while an attempt is in flight', async () => {
  const scheduler = new FakeScheduler()
  const activeAttempt = deferred<LogoutAttemptResult>()
  let attempts = 0
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async () => {
      attempts += 1
      return activeAttempt.promise
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  assert.equal(coordinator.requestExplicitRetry('request-1'), false)
  assert.equal(coordinator.notifyOnline('request-1'), false)
  assert.equal(coordinator.requestExplicitRetry('other-request'), false)
  assert.equal(attempts, 1)

  activeAttempt.resolve('retryable')
  await flushAsync()
  assert.equal(attempts, 1)
  assert.equal(scheduler.pendingCount, 1)
  coordinator.dispose()
})

test('a stale attempt fence cancels before transport dispatch', async () => {
  const scheduler = new FakeScheduler()
  let attempts = 0
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    recordAttempt: () => false,
    attempt: async () => {
      attempts += 1
      return 'confirmed'
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  await flushAsync()
  assert.equal(attempts, 0)
  assert.equal(coordinator.getSnapshot().status, 'cancelled')
  assert.equal(coordinator.getSnapshot().reason, 'stale')
  assert.equal(coordinator.getSnapshot().proofAvailable, false)
  coordinator.dispose()
})

test('matching cancellation aborts in-flight work and makes late success inert', async () => {
  const scheduler = new FakeScheduler()
  const activeAttempt = deferred<LogoutAttemptResult>()
  let observedSignal: AbortSignal | null = null
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async ({ signal }) => {
      observedSignal = signal
      return activeAttempt.promise
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  assert.equal(coordinator.cancel('other-request'), false)
  assert.equal(coordinator.cancel('request-1', 'stale'), true)
  assert.equal(signalWasAborted(observedSignal), true)
  assert.equal(coordinator.getSnapshot().status, 'cancelled')
  assert.equal(coordinator.getSnapshot().reason, 'stale')

  activeAttempt.resolve('confirmed')
  await flushAsync()
  assert.equal(coordinator.getSnapshot().status, 'cancelled')
  assert.equal(scheduler.pendingCount, 0)
  coordinator.dispose()
})

test('starting a newer operation aborts and fences the older completion', async () => {
  const scheduler = new FakeScheduler()
  const firstAttempt = deferred<LogoutAttemptResult>()
  let firstSignal: AbortSignal | null = null
  const attempts: string[] = []
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async ({ requestId, signal }) => {
      attempts.push(requestId)
      if (requestId === 'request-1') {
        firstSignal = signal
        return firstAttempt.promise
      }
      return 'confirmed'
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'old-proof' })
  coordinator.start({ requestId: 'request-2', proof: 'new-proof' })
  await flushAsync()
  assert.equal(signalWasAborted(firstSignal), true)
  assert.deepEqual(attempts, ['request-1', 'request-2'])
  assert.equal(coordinator.getSnapshot().requestId, 'request-2')
  assert.equal(coordinator.getSnapshot().status, 'confirmed')

  firstAttempt.resolve('retryable')
  await flushAsync()
  assert.equal(coordinator.getSnapshot().requestId, 'request-2')
  assert.equal(coordinator.getSnapshot().status, 'confirmed')
  coordinator.dispose()
})

test('dispose clears scheduled and in-flight work without dispatching again', async () => {
  const scheduler = new FakeScheduler()
  let attempts = 0
  const stateChanges: LogoutRetrySnapshot[] = []
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async () => {
      attempts += 1
      return 'retryable'
    },
    onStateChange: (snapshot) => {
      stateChanges.push(snapshot)
    },
  })

  coordinator.start({ requestId: 'request-1', proof: 'memory-proof' })
  await flushAsync()
  assert.equal(scheduler.pendingCount, 1)
  const notificationsBeforeDispose = stateChanges.length
  coordinator.dispose()
  assert.equal(coordinator.getSnapshot().proofAvailable, false)
  assert.equal(coordinator.getSnapshot().canRetry, false)
  assert.equal(scheduler.pendingCount, 0)

  scheduler.advanceBy(60_000)
  await flushAsync()
  assert.equal(attempts, 1)
  assert.equal(stateChanges.length, notificationsBeforeDispose)
  coordinator.dispose()
})

test('reload without an in-memory proof never dispatches or retries', async () => {
  const scheduler = new FakeScheduler()
  let attempts = 0
  const coordinator = createLogoutRetryCoordinator<string>({
    scheduler,
    isCurrent: () => true,
    classifyError: () => 'retryable',
    attempt: async () => {
      attempts += 1
      return 'confirmed'
    },
  })

  coordinator.start({ requestId: 'persisted-request', proof: null })
  await flushAsync()
  scheduler.advanceBy(60_000)
  await flushAsync()

  assert.equal(attempts, 0)
  assert.equal(scheduler.pendingCount, 0)
  assert.equal(coordinator.getSnapshot().status, 'unconfirmed')
  assert.equal(coordinator.getSnapshot().reason, 'no-proof')
  assert.equal(coordinator.getSnapshot().proofAvailable, false)
  assert.equal(coordinator.getSnapshot().canRetry, false)
  assert.equal(coordinator.requestExplicitRetry('persisted-request'), false)
  assert.equal(coordinator.notifyOnline('persisted-request'), false)
  coordinator.dispose()
})
