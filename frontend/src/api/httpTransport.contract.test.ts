/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import { AxiosHeaders } from 'axios'
import {
  applySessionRequestHeaders,
  CSRF_HEADER_NAME,
  shouldClearSessionForUnauthorized,
} from './httpTransport.ts'

test('cookie transport strips legacy identity credentials and replaces unsafe CSRF', () => {
  const headers = new AxiosHeaders({
    authorization: 'Bearer stale-browser-token',
    'x-user-role': 'admin',
    'X-User-Id': 'stale-subject',
    'X-User-Programme': 'DR',
    'X-User-Site': 'TTSHCardio',
    'X-User-MCR': 'stale-resident-credential',
    'X-Admin-Level': 'master',
    'x-csrf-token': 'stale-csrf',
  })

  applySessionRequestHeaders(headers, {
    method: 'patch',
    csrfToken: 'current-csrf',
    stripLegacyCredentials: true,
  })

  for (const headerName of [
    'Authorization',
    'X-User-Role',
    'X-User-Id',
    'X-User-Programme',
    'X-User-Site',
    'X-User-MCR',
    'X-Admin-Level',
  ]) {
    assert.equal(headers.has(headerName), false)
  }
  assert.equal(headers.get(CSRF_HEADER_NAME), 'current-csrf')
})

test('safe requests never retain a caller-supplied CSRF header', () => {
  const headers = new AxiosHeaders({
    'X-CSRF-Token': 'caller-supplied',
  })
  applySessionRequestHeaders(headers, {
    method: 'GET',
    csrfToken: 'memory-token',
    stripLegacyCredentials: true,
  })
  assert.equal(headers.has(CSRF_HEADER_NAME), false)
})

test('only a 401 from the current session revision clears memory state', () => {
  assert.equal(shouldClearSessionForUnauthorized(401, 7, 7), true)
  assert.equal(shouldClearSessionForUnauthorized(401, 6, 7), false)
  assert.equal(shouldClearSessionForUnauthorized(401, undefined, 7), false)
  assert.equal(shouldClearSessionForUnauthorized(403, 7, 7), false)
})
