/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import {
  createResidentLoginPayload,
  type ResidentLoginPayload,
  type ResidentLoginRole,
} from '../../api/loginPayloads.ts'
import { resolveResidentLoginError } from '../../api/loginErrorMessages.ts'
import type { StoredAuthSession } from '../../types/auth.ts'
import {
  createInitialResidentLoginState,
  selectResidentLoginRole,
  submitSelectedResidentLogin,
} from './residentLoginFlow.ts'

const sessionForRole = (role: ResidentLoginRole): StoredAuthSession => ({
  mode: 'supabase',
  accessToken: role === 'resident' ? 'mata-native-token' : 'mata-external-token',
  tokenType: 'bearer',
  createdAt: '2026-07-16T00:00:00.000Z',
  identity: role === 'resident'
    ? {
        role: 'resident',
        subjectId: 'native-resident-id',
        name: 'Native Resident',
        mcr: 'M90001Z',
        programmeCode: 'GRM',
      }
    : {
        role: 'external_resident',
        subjectId: 'external-resident-id',
        name: 'Non-NHG Resident',
        mcr: 'M90001Z',
        homeCluster: 'NUH',
      },
})

test('NHG MCR submit constructs one normalized resident request and returns the native route', async () => {
  const requests: ResidentLoginPayload[] = []

  const result = await submitSelectedResidentLogin({
    rawMcr: '  m90001z  ',
    role: 'resident',
    authenticate: async (payload) => {
      requests.push(payload)
      return sessionForRole('resident')
    },
  })

  assert.deepEqual(requests, [{ role: 'resident', mcr: 'M90001Z' }])
  assert.equal(result.session.accessToken, 'mata-native-token')
  assert.equal(result.redirectPath, '/resident/submissions')
})

test('registered Non-NHG MCR submit constructs one explicit external request and returns its route', async () => {
  const requests: ResidentLoginPayload[] = []

  const result = await submitSelectedResidentLogin({
    rawMcr: '  m90001z  ',
    role: 'external_resident',
    authenticate: async (payload) => {
      requests.push(payload)
      return sessionForRole('external_resident')
    },
  })

  assert.deepEqual(requests, [{ role: 'external_resident', mcr: 'M90001Z' }])
  assert.equal(result.session.accessToken, 'mata-external-token')
  assert.equal(result.redirectPath, '/external/submissions')
})

test('returning to the normal login page creates a fresh NHG Resident mode', () => {
  const nonNhgState = selectResidentLoginRole('external_resident')
  assert.equal(nonNhgState.role, 'external_resident')

  const remountedLoginState = createInitialResidentLoginState()
  assert.equal(remountedLoginState.role, 'resident')
})

test('a previous external attempt cannot change the next explicit NHG request', async () => {
  const requests: ResidentLoginPayload[] = []

  await assert.rejects(
    submitSelectedResidentLogin({
      rawMcr: 'M90001Z',
      role: 'external_resident',
      authenticate: async (payload) => {
        requests.push(payload)
        throw new Error('Unauthorized')
      },
    }),
  )

  const result = await submitSelectedResidentLogin({
    rawMcr: 'M90001Z',
    role: 'resident',
    authenticate: async (payload) => {
      requests.push(payload)
      return sessionForRole('resident')
    },
  })

  assert.deepEqual(requests, [
    { role: 'external_resident', mcr: 'M90001Z' },
    { role: 'resident', mcr: 'M90001Z' },
  ])
  assert.equal(result.session.identity.role, 'resident')
})

test('a previous NHG attempt cannot change the next explicit Non-NHG request', async () => {
  const requests: ResidentLoginPayload[] = []

  await assert.rejects(
    submitSelectedResidentLogin({
      rawMcr: 'M90001Z',
      role: 'resident',
      authenticate: async (payload) => {
        requests.push(payload)
        throw new Error('Unauthorized')
      },
    }),
  )

  const result = await submitSelectedResidentLogin({
    rawMcr: 'M90001Z',
    role: 'external_resident',
    authenticate: async (payload) => {
      requests.push(payload)
      return sessionForRole('external_resident')
    },
  })

  assert.deepEqual(requests, [
    { role: 'resident', mcr: 'M90001Z' },
    { role: 'external_resident', mcr: 'M90001Z' },
  ])
  assert.equal(result.session.identity.role, 'external_resident')
})

test('failed NHG login neither probes the external table nor mutates the selected subtype', async () => {
  const state = createInitialResidentLoginState()
  const requests: ResidentLoginPayload[] = []

  for (let attempt = 0; attempt < 2; attempt += 1) {
    await assert.rejects(
      submitSelectedResidentLogin({
        rawMcr: ' M90001Z ',
        role: state.role,
        authenticate: async (payload) => {
          requests.push(payload)
          throw new Error('Unauthorized')
        },
      }),
    )
  }

  assert.equal(state.role, 'resident')
  assert.deepEqual(requests, [
    { role: 'resident', mcr: 'M90001Z' },
    { role: 'resident', mcr: 'M90001Z' },
  ])
})

test('MCR normalization is shared by both explicit resident payloads', () => {
  assert.deepEqual(createResidentLoginPayload('\t m12345a \n', 'resident'), {
    role: 'resident',
    mcr: 'M12345A',
  })
  assert.deepEqual(createResidentLoginPayload('  e12345a  ', 'external_resident'), {
    role: 'external_resident',
    mcr: 'E12345A',
  })
})

test('ordinary auth, validation, and network failures map to the exact generic message', () => {
  const network = Object.assign(new Error('https://internal.example failed'), { isNetworkError: true })

  for (const status of [401, 403, 404, 422]) {
    const failure = Object.assign(new Error(`Sensitive backend detail for ${status}`), { status })
    assert.equal(
      resolveResidentLoginError(failure),
      'Unable to sign in. Check your details and try again.',
    )
  }
  assert.equal(
    resolveResidentLoginError(network),
    'Unable to sign in. Check your details and try again.',
  )
})

test('unexpected details are redacted and rate-limit timing remains specific', () => {
  const unexpected = new Error('SQL SELECT secret_token FROM users')
  const rateLimited = Object.assign(new Error('backend detail'), {
    status: 429,
    retryAfterSeconds: 120,
  })

  const unexpectedMessage = resolveResidentLoginError(unexpected)
  assert.equal(unexpectedMessage, 'Unable to sign in. Check your details and try again.')
  assert.equal(unexpectedMessage.includes('SQL'), false)
  assert.equal(unexpectedMessage.includes('secret_token'), false)
  assert.equal(
    resolveResidentLoginError(rateLimited),
    'Too many sign-in attempts. Please try again in 2 minutes.',
  )
})

test('error mapping does not change the selected resident role', () => {
  const state = selectResidentLoginRole('external_resident')

  resolveResidentLoginError(Object.assign(new Error('Unauthorized'), { status: 401 }))

  assert.equal(state.role, 'external_resident')
})
