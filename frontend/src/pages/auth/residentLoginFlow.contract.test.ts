/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import {
  createResidentLoginPayload,
  type ResidentLoginPayload,
} from '../../api/loginPayloads.ts'
import { resolveResidentLoginError } from '../../api/loginErrorMessages.ts'
import type { StoredAuthSession } from '../../types/auth.ts'
import { submitSharedResidentLogin } from './residentLoginFlow.ts'

type AuthenticatedResidentRole = 'resident' | 'external_resident'

const sessionForRole = (role: AuthenticatedResidentRole): StoredAuthSession => ({
  mode: 'supabase',
  accessToken: role === 'resident' ? 'mata-native-token' : 'mata-external-token',
  tokenType: 'bearer',
  createdAt: '2026-07-16T00:00:00.000Z',
  identity: role === 'resident'
    ? {
        role: 'resident',
        subjectId: 'native-resident-id',
        name: 'Synthetic Native Resident',
        mcr: 'M90001Z',
        programmeCode: 'GRM',
      }
    : {
        role: 'external_resident',
        subjectId: 'external-resident-id',
        name: 'Synthetic Non-NHG Resident',
        mcr: 'M90001Z',
        homeCluster: 'NUH',
      },
})

test('shared MCR submit sends one normalized neutral request and redirects a native response', async () => {
  const requests: ResidentLoginPayload[] = []

  const result = await submitSharedResidentLogin({
    rawMcr: '  m90001z  ',
    authenticate: async (payload) => {
      requests.push(payload)
      return sessionForRole('resident')
    },
  })

  assert.deepEqual(requests, [{ role: 'resident', mcr: 'M90001Z' }])
  assert.equal(result.session.accessToken, 'mata-native-token')
  assert.equal(result.redirectPath, '/resident/submissions')
})

test('shared MCR submit keeps the neutral request and redirects an external response', async () => {
  const requests: ResidentLoginPayload[] = []

  const result = await submitSharedResidentLogin({
    rawMcr: '  m90001z  ',
    authenticate: async (payload) => {
      requests.push(payload)
      return sessionForRole('external_resident')
    },
  })

  assert.deepEqual(requests, [{ role: 'resident', mcr: 'M90001Z' }])
  assert.equal(result.session.accessToken, 'mata-external-token')
  assert.equal(result.redirectPath, '/external/submissions')
})

test('an external-looking MCR prefix does not change the neutral request role', async () => {
  const requests: ResidentLoginPayload[] = []

  await submitSharedResidentLogin({
    rawMcr: ' e90001z ',
    authenticate: async (payload) => {
      requests.push(payload)
      return sessionForRole('external_resident')
    },
  })

  assert.deepEqual(requests, [{ role: 'resident', mcr: 'E90001Z' }])
})

test('a failed shared login makes one request and does not retry another role', async () => {
  const requests: ResidentLoginPayload[] = []

  await assert.rejects(
    submitSharedResidentLogin({
      rawMcr: ' M90001Z ',
      authenticate: async (payload) => {
        requests.push(payload)
        throw new Error('Unauthorized')
      },
    }),
  )

  assert.deepEqual(requests, [{ role: 'resident', mcr: 'M90001Z' }])
})

test('an unexpected staff response is rejected before a resident session can be returned', async () => {
  const requests: ResidentLoginPayload[] = []
  const staffSession: StoredAuthSession = {
    mode: 'supabase',
    accessToken: 'unexpected-staff-token',
    tokenType: 'bearer',
    createdAt: '2026-07-16T00:00:00.000Z',
    identity: {
      role: 'programme_pc',
      subjectId: 'unexpected-staff-id',
      name: 'Synthetic Staff Account',
      adminLevel: 'programme',
      programmeScope: ['GRM'],
      staffActorNameRequired: false,
    },
  }

  await assert.rejects(
    submitSharedResidentLogin({
      rawMcr: 'M90001Z',
      authenticate: async (payload) => {
        requests.push(payload)
        return staffSession
      },
    }),
    /invalid role/,
  )

  assert.deepEqual(requests, [{ role: 'resident', mcr: 'M90001Z' }])
})

test('MCR normalization is fixed to the shared neutral resident payload', () => {
  assert.deepEqual(createResidentLoginPayload('\t m12345a \n'), {
    role: 'resident',
    mcr: 'M12345A',
  })
})

test('ordinary auth, validation, and network failures map to the exact generic message', () => {
  const network = Object.assign(new Error('https://internal.example failed'), { isNetworkError: true })

  for (const status of [401, 403, 404, 409, 422]) {
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
