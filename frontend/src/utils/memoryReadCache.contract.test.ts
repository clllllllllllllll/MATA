/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import {
  clearMemoryCache,
  getMemoryCache,
  MemoryCacheInvalidatedError,
  readThroughMemoryCache,
} from './memoryReadCache.ts'

test('a cache clear fences an in-flight protected result from returning or repopulating memory', async () => {
  clearMemoryCache()
  const key = 'protected-session-resource'
  let resolveFetch: ((value: string) => void) | undefined
  const fetched = new Promise<string>((resolve) => {
    resolveFetch = resolve
  })

  const pendingRead = readThroughMemoryCache(key, () => fetched)
  clearMemoryCache()
  resolveFetch?.('stale-protected-data')

  await assert.rejects(pendingRead, MemoryCacheInvalidatedError)
  assert.equal(getMemoryCache(key), undefined)

  assert.deepEqual(
    await readThroughMemoryCache(key, async () => 'fresh-protected-data'),
    {
      data: 'fresh-protected-data',
      fromCache: false,
    },
  )
  assert.equal(getMemoryCache<string>(key)?.data, 'fresh-protected-data')
  clearMemoryCache()
})

test('a scoped clear also fences reads already in flight', async () => {
  clearMemoryCache()
  const key = 'scoped-protected-resource'
  let resolveFetch: ((value: string) => void) | undefined
  const fetched = new Promise<string>((resolve) => {
    resolveFetch = resolve
  })

  const pendingRead = readThroughMemoryCache(key, () => fetched)
  clearMemoryCache((candidate) => candidate === key)
  resolveFetch?.('stale-scoped-data')

  await assert.rejects(pendingRead, MemoryCacheInvalidatedError)
  assert.equal(getMemoryCache(key), undefined)
  clearMemoryCache()
})

test('a scoped clear does not cancel an unrelated in-flight read', async () => {
  clearMemoryCache()
  const key = 'unrelated-protected-resource'
  let resolveFetch: ((value: string) => void) | undefined
  const fetched = new Promise<string>((resolve) => {
    resolveFetch = resolve
  })

  const pendingRead = readThroughMemoryCache(key, () => fetched)
  clearMemoryCache((candidate) => candidate === 'different-protected-resource')
  resolveFetch?.('current-protected-data')

  assert.deepEqual(await pendingRead, {
    data: 'current-protected-data',
    fromCache: false,
  })
  assert.equal(getMemoryCache<string>(key)?.data, 'current-protected-data')
  clearMemoryCache()
})

test('a cache clear replaces an in-flight protected rejection with invalidation', async () => {
  clearMemoryCache()
  const key = 'rejected-protected-resource'
  let rejectFetch: ((error: Error) => void) | undefined
  const fetched = new Promise<string>((_resolve, reject) => {
    rejectFetch = reject
  })

  const pendingRead = readThroughMemoryCache(key, () => fetched)
  clearMemoryCache()
  rejectFetch?.(new Error('stale identity error'))

  await assert.rejects(pendingRead, MemoryCacheInvalidatedError)
  assert.equal(getMemoryCache(key), undefined)
  clearMemoryCache()
})
