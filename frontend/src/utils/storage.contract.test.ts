/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import type { UploadMeta } from '../types/upload.ts'
import {
  clearUploadHistory,
  loadUploadHistory,
  saveUploadHistory,
} from './storage.ts'

const LEGACY_UPLOADS_KEY = 'mata.admin.uploads.v1'

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>()
  setItemCalls = 0

  get length(): number {
    return this.values.size
  }

  clear(): void {
    this.values.clear()
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }

  setItem(key: string, value: string): void {
    this.setItemCalls += 1
    this.values.set(key, value)
  }
}

const uploadMeta = (): UploadMeta => ({
  id: 'upload-1',
  uploadType: 'ttf',
  uploadLabel: 'Teaching Target File',
  uploadedAtIso: '2026-07-27T10:00:00.000Z',
  filename: 'programme-targets.xlsx',
  reportingPeriodId: 'period-1',
  reportingPeriodLabel: 'Jul-Dec 2026',
  programmeCode: 'GRM',
  status: 'success',
  response: {
    targets_created: 5,
    warning_count: 0,
    error_count: 0,
  },
  warningsCount: 0,
  errorsCount: 0,
})

test('upload metadata is memory-only and legacy localStorage residue is removed', () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const localStorage = new MemoryStorage()
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: { localStorage },
  })

  try {
    clearUploadHistory()
    localStorage.setItem(LEGACY_UPLOADS_KEY, JSON.stringify([uploadMeta()]))
    localStorage.setItemCalls = 0
    assert.deepEqual(loadUploadHistory(), [])
    assert.equal(localStorage.getItem(LEGACY_UPLOADS_KEY), null)

    const entry = uploadMeta()
    saveUploadHistory([entry])
    assert.equal(localStorage.setItemCalls, 0)
    assert.equal(localStorage.getItem(LEGACY_UPLOADS_KEY), null)
    assert.deepEqual(loadUploadHistory(), [entry])

    const loaded = loadUploadHistory()
    loaded[0].response.targets_created = 999
    assert.equal(loadUploadHistory()[0].response.targets_created, 5)

    clearUploadHistory()
    assert.deepEqual(loadUploadHistory(), [])
    assert.equal(localStorage.getItem(LEGACY_UPLOADS_KEY), null)
  } finally {
    clearUploadHistory()
    if (originalWindow) {
      Object.defineProperty(globalThis, 'window', originalWindow)
    } else {
      Reflect.deleteProperty(globalThis, 'window')
    }
  }
})
