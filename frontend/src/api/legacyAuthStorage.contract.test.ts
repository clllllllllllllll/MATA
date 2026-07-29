/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import {
  LEGACY_MATA_AUTH_SESSION_KEY,
  removeKnownLegacyCredentials,
} from './legacyAuthStorage.ts'

class MemoryStorage {
  readonly values = new Map<string, string>()
  readonly removed: string[] = []

  removeItem(key: string): void {
    this.removed.push(key)
    this.values.delete(key)
  }
}

test('startup cleanup removes only the exact known legacy MATA key', () => {
  const storage = new MemoryStorage()
  const projectRef = 'abcdefghijklmnopqrst'
  const removable = [LEGACY_MATA_AUTH_SESSION_KEY]
  const retained = [
    'mata.logout.pending.v1',
    'mata.uploads.v1',
    'unrelated-auth-token',
    `sb-short-auth-token`,
    `sb-${projectRef}-auth-token`,
    `sb-${projectRef}-auth-token-code-verifier`,
    `sb-${projectRef}-auth-token.0`,
    `sb-${projectRef}-unrelated`,
  ]

  for (const key of [...removable, ...retained]) {
    storage.values.set(key, 'value-that-is-never-read')
  }

  removeKnownLegacyCredentials(storage)
  assert.deepEqual(storage.removed.sort(), removable.sort())
  assert.deepEqual([...storage.values.keys()].sort(), retained.sort())
})

test('cleanup directly requests only the known key when storage has no match', () => {
  const storage = new MemoryStorage()
  storage.values.set('unrelated-before', 'preserved')
  storage.values.set('unrelated-after', 'preserved')

  removeKnownLegacyCredentials(storage)
  assert.deepEqual(storage.removed, [LEGACY_MATA_AUTH_SESSION_KEY])
  assert.deepEqual(
    [...storage.values.keys()],
    ['unrelated-before', 'unrelated-after'],
  )
})
