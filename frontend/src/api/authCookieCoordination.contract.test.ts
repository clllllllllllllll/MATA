/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import {
  AUTH_COOKIE_COORDINATION_HEADER_NAME,
  AUTH_COOKIE_COORDINATION_PROTOCOL,
  AUTH_COOKIE_RESPONSE_LOCK_NAME,
  AuthCookieCoordinationUnavailableError,
  type AuthCookieCoordinationEnvironment,
  type AuthCookieLockManager,
  withAuthCookieResponseLock,
} from './authCookieCoordination.ts'

const deferred = <T>() => {
  let resolvePromise: ((value: T | PromiseLike<T>) => void) | undefined
  let rejectPromise: ((reason?: unknown) => void) | undefined
  const promise = new Promise<T>((resolve, reject) => {
    resolvePromise = resolve
    rejectPromise = reject
  })
  return {
    promise,
    resolve: (value: T) => resolvePromise?.(value),
    reject: (reason: unknown) => rejectPromise?.(reason),
  }
}

class FifoLockManager implements AuthCookieLockManager {
  private tail: Promise<void> = Promise.resolve()

  request<T>(
    name: string,
    options: { mode: 'exclusive' },
    callback: () => Promise<T>,
  ): Promise<T> {
    assert.equal(name, AUTH_COOKIE_RESPONSE_LOCK_NAME)
    assert.deepEqual(options, { mode: 'exclusive' })
    const result = this.tail.then(callback)
    this.tail = result.then(
      () => undefined,
      () => undefined,
    )
    return result
  }
}

const coordinatedEnvironment = (
  lockManager: AuthCookieLockManager = new FifoLockManager(),
): AuthCookieCoordinationEnvironment => ({
  secureContext: true,
  lockManager,
})

test('auth cookie responses are serialized through browser cookie application', async () => {
  const firstStarted = deferred<void>()
  const releaseFirst = deferred<void>()
  const order: string[] = []
  let sharedCookie = 'parent-a'
  const environment = coordinatedEnvironment()

  const staleRefresh = withAuthCookieResponseLock(async () => {
    order.push('refresh-start')
    firstStarted.resolve()
    await releaseFirst.promise
    sharedCookie = 'child-a'
    order.push('refresh-response')
  }, environment)
  await firstStarted.promise

  const newerLogin = withAuthCookieResponseLock(async () => {
    order.push('login-start')
    sharedCookie = 'session-b'
    order.push('login-response')
  }, environment)

  assert.deepEqual(order, ['refresh-start'])
  releaseFirst.resolve()
  await Promise.all([staleRefresh, newerLogin])

  assert.deepEqual(order, [
    'refresh-start',
    'refresh-response',
    'login-start',
    'login-response',
  ])
  assert.equal(sharedCookie, 'session-b')
})

test('a rejected operation releases the exclusive response lock', async () => {
  const environment = coordinatedEnvironment()
  const firstError = new Error('refresh failed')
  let secondRan = false

  await assert.rejects(
    withAuthCookieResponseLock(async () => {
      throw firstError
    }, environment),
    firstError,
  )
  await withAuthCookieResponseLock(async () => {
    secondRan = true
  }, environment)

  assert.equal(secondRan, true)
})

test('missing secure Web Locks support fails before network dispatch', async () => {
  let dispatchCount = 0
  const operation = async () => {
    dispatchCount += 1
  }

  await assert.rejects(
    withAuthCookieResponseLock(operation, {
      secureContext: false,
      lockManager: new FifoLockManager(),
    }),
    AuthCookieCoordinationUnavailableError,
  )
  await assert.rejects(
    withAuthCookieResponseLock(operation, {
      secureContext: true,
      lockManager: null,
    }),
    AuthCookieCoordinationUnavailableError,
  )

  assert.equal(dispatchCount, 0)
})

test('lock acquisition failure never invokes the lifecycle request', async () => {
  const lockError = new Error('lock manager unavailable')
  let dispatchCount = 0
  const rejectingManager: AuthCookieLockManager = {
    request: async () => {
      throw lockError
    },
  }

  await assert.rejects(
    withAuthCookieResponseLock(async () => {
      dispatchCount += 1
    }, coordinatedEnvironment(rejectingManager)),
    lockError,
  )

  assert.equal(dispatchCount, 0)
})

test('the versioned production coordination protocol is exact', () => {
  assert.equal(
    AUTH_COOKIE_COORDINATION_HEADER_NAME,
    'X-MATA-Session-Coordination',
  )
  assert.equal(AUTH_COOKIE_COORDINATION_PROTOCOL, 'web-locks-v1')
})
