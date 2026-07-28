/// <reference types="node" />

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import type { AuthIdentity } from '../types/auth'
import { protectedRouteAuthorityKey } from './protectedRouteAuthorityKey.ts'

const appSource = readFileSync(
  fileURLToPath(new URL('../App.tsx', import.meta.url)),
  'utf8',
)
const externalAttendanceSource = readFileSync(
  fileURLToPath(new URL('../pages/admin/AdminExternalAttendancePage.tsx', import.meta.url)),
  'utf8',
)

const residentIdentity: AuthIdentity = {
  role: 'resident',
  subjectId: 'resident-subject-a',
  name: 'Resident A',
  mcr: 'resident-identifier-a',
  programmeCode: 'DERM',
  currentPostingCode: 'POST-A',
  currentPostingLabel: 'Posting A',
}

test('protected route authority keys exclude personal display and credential fields', () => {
  const originalKey = protectedRouteAuthorityKey(residentIdentity)
  const displayOnlyChange = protectedRouteAuthorityKey({
    ...residentIdentity,
    name: 'Renamed Resident',
    mcr: 'replacement-resident-identifier',
    currentPostingLabel: 'Renamed Posting',
  })

  assert.equal(displayOnlyChange, originalKey)
  assert.equal(originalKey.includes(residentIdentity.mcr), false)
  assert.equal(originalKey.includes(residentIdentity.name ?? ''), false)
})

test('protected route authority keys change with subject or authorization scope', () => {
  const originalKey = protectedRouteAuthorityKey(residentIdentity)

  assert.notEqual(
    protectedRouteAuthorityKey({ ...residentIdentity, subjectId: 'resident-subject-b' }),
    originalKey,
  )
  assert.notEqual(
    protectedRouteAuthorityKey({ ...residentIdentity, programmeCode: 'ENT' }),
    originalKey,
  )
  assert.notEqual(
    protectedRouteAuthorityKey({ ...residentIdentity, currentPostingCode: 'POST-B' }),
    originalKey,
  )

  const programmePc: AuthIdentity = {
    role: 'programme_pc',
    subjectId: 'pc-subject',
    name: 'PC',
    email: 'pc@example.invalid',
    adminLevel: 'programme',
    programmeScope: ['ENT', 'DERM', 'ENT'],
    staffActorNameRequired: false,
  }
  assert.equal(
    protectedRouteAuthorityKey(programmePc),
    protectedRouteAuthorityKey({
      ...programmePc,
      programmeScope: ['DERM', 'ENT'],
    }),
  )
  assert.notEqual(
    protectedRouteAuthorityKey(programmePc),
    protectedRouteAuthorityKey({
      ...programmePc,
      programmeScope: ['DERM'],
    }),
  )
})

test('the protected route subtree remounts and export completion is auth-fenced', () => {
  assert.match(
    appSource,
    /const protectedAuthorityKey = protectedRouteAuthorityKey\(identity\)/,
  )
  assert.match(appSource, /<AppRoutes key=\{protectedAuthorityKey\} \/>/)
  assert.match(
    externalAttendanceSource,
    /captureProtectedAsyncRequestFence\(\s*'admin\.external-attendance\.export'/,
  )
  assert.match(
    externalAttendanceSource,
    /if \(!isCurrentRequest\(\)\) \{\s+return\s+\}\s+downloadBlob\(blob\)/,
  )
})
