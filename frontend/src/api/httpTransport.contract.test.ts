/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import { AxiosHeaders } from 'axios'
import {
  applySessionRequestHeaders,
  CSRF_HEADER_NAME,
  handleUnauthorizedSessionResponse,
  shouldClearSessionForUnauthorized,
  shouldBlockRequestDuringLogoutPending,
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

test('pending logout blocks protected safe and unsafe requests unless explicitly allowed', () => {
  assert.equal(shouldBlockRequestDuringLogoutPending(true, undefined), true)
  assert.equal(shouldBlockRequestDuringLogoutPending(true, false), true)
  assert.equal(shouldBlockRequestDuringLogoutPending(true, true), false)
  assert.equal(shouldBlockRequestDuringLogoutPending(false, undefined), false)
})

test('only a 401 from the current session revision clears memory state', () => {
  assert.equal(shouldClearSessionForUnauthorized(401, true, 7, true, 7), true)
  assert.equal(shouldClearSessionForUnauthorized(401, true, 6, true, 7), false)
  assert.equal(shouldClearSessionForUnauthorized(401, true, undefined, true, 7), false)
  assert.equal(shouldClearSessionForUnauthorized(403, true, 7, true, 7), false)
})

test('an unauthenticated login or public request 401 cannot clear or broadcast', () => {
  let clearCount = 0
  let broadcastCount = 0
  const clearAndBroadcast = () => {
    clearCount += 1
    broadcastCount += 1
  }

  assert.equal(
    handleUnauthorizedSessionResponse(401, false, 7, false, 7, clearAndBroadcast),
    false,
  )
  assert.equal(
    handleUnauthorizedSessionResponse(401, undefined, 7, false, 7, clearAndBroadcast),
    false,
  )
  assert.equal(clearCount, 0)
  assert.equal(broadcastCount, 0)
})

test('an authenticated request 401 cannot clear a session that is no longer current', () => {
  assert.equal(shouldClearSessionForUnauthorized(401, true, 7, false, 7), false)
  assert.equal(shouldClearSessionForUnauthorized(401, false, 7, true, 7), false)
})

test('unauthorized handling terminates exactly the current session and never retries', () => {
  let terminationCount = 0
  const terminate = () => {
    terminationCount += 1
  }

  assert.equal(handleUnauthorizedSessionResponse(401, true, 7, true, 7, terminate), true)
  assert.equal(terminationCount, 1)

  assert.equal(handleUnauthorizedSessionResponse(401, true, 6, true, 7, terminate), false)
  assert.equal(handleUnauthorizedSessionResponse(401, true, undefined, true, 7, terminate), false)
  assert.equal(handleUnauthorizedSessionResponse(403, true, 7, true, 7, terminate), false)
  assert.equal(terminationCount, 1)
})
