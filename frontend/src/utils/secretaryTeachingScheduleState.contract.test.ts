import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isCurrentTeachingSourceEligible,
  poolStartTimeValidationError,
  resolveSecretaryEventProgrammeContext,
  serverComputedPoolEndTime,
  shouldTemporarilyRetainPoolSource,
} from './secretaryTeachingScheduleState.ts'

test('pool-backed events use their persisted source programme rather than display text', () => {
  assert.deepEqual(
    resolveSecretaryEventProgrammeContext({
      teachingNameId: 'teaching-name-id',
      sourceProgrammeCode: ' CARD ',
    }),
    { kind: 'pool_backed', programmeCode: 'CARD' },
  )
  assert.deepEqual(
    resolveSecretaryEventProgrammeContext({ teachingNameId: 'teaching-name-id' }),
    { kind: 'missing_pool_programme' },
  )
  assert.deepEqual(
    resolveSecretaryEventProgrammeContext({ sourceProgrammeCode: 'GERI' }),
    { kind: 'pool_backed', programmeCode: 'GERI' },
  )
  assert.deepEqual(
    resolveSecretaryEventProgrammeContext({ globalSessionTypeId: 'global-source-id' }),
    { kind: 'not_pool_backed' },
  )
  assert.deepEqual(resolveSecretaryEventProgrammeContext({}), { kind: 'not_pool_backed' })
})

test('a deleted pool ID retains its immutable programme snapshot for exact programme selection', () => {
  const deletedPoolSource = { sourceProgrammeCode: 'CARD' }

  assert.equal(
    shouldTemporarilyRetainPoolSource({
      event: deletedPoolSource,
      selectedProgrammeCode: 'CARD',
      optionsState: 'loading',
      programmeSwitchPending: true,
      sourceIsAvailable: false,
    }),
    false,
  )
  assert.deepEqual(
    resolveSecretaryEventProgrammeContext(deletedPoolSource),
    { kind: 'pool_backed', programmeCode: 'CARD' },
  )
  assert.equal(
    isCurrentTeachingSourceEligible('', [{ sourceKey: 'teaching-name:replacement-id' }]),
    false,
  )
})

test('missing pool sources are omitted after an authoritative response and cannot save', () => {
  const inactivePoolSource = {
    teachingNameId: 'deleted-or-inactive-pool-id',
    sourceProgrammeCode: 'GERI',
  }

  assert.equal(
    shouldTemporarilyRetainPoolSource({
      event: inactivePoolSource,
      selectedProgrammeCode: 'GERI',
      optionsState: 'loading',
      programmeSwitchPending: true,
      sourceIsAvailable: false,
    }),
    true,
  )
  assert.equal(
    shouldTemporarilyRetainPoolSource({
      event: inactivePoolSource,
      selectedProgrammeCode: 'GERI',
      optionsState: 'ready',
      programmeSwitchPending: true,
      sourceIsAvailable: false,
    }),
    false,
  )
  assert.equal(
    shouldTemporarilyRetainPoolSource({
      event: inactivePoolSource,
      selectedProgrammeCode: 'CARD',
      optionsState: 'loading',
      programmeSwitchPending: true,
      sourceIsAvailable: false,
    }),
    false,
  )
  assert.equal(
    shouldTemporarilyRetainPoolSource({
      event: inactivePoolSource,
      selectedProgrammeCode: 'GERI',
      optionsState: 'loading',
      programmeSwitchPending: false,
      sourceIsAvailable: false,
    }),
    false,
  )
  assert.equal(
    isCurrentTeachingSourceEligible('deleted-or-inactive-pool-id', [
      { sourceKey: 'teaching-name:active-id' },
    ]),
    false,
  )
  assert.equal(
    isCurrentTeachingSourceEligible('teaching-name:active-id', [
      { sourceKey: 'teaching-name:active-id' },
    ]),
    true,
  )
})

test('the fixed pool duration preview matches the server-owned one-hour boundary', () => {
  assert.equal(serverComputedPoolEndTime('10:15'), '11:15')
  assert.equal(serverComputedPoolEndTime('23:00'), '00:00')
  assert.equal(serverComputedPoolEndTime('24:00'), null)
  assert.equal(serverComputedPoolEndTime('not-a-time'), null)
  assert.equal(poolStartTimeValidationError('23:00'), null)
  assert.equal(
    poolStartTimeValidationError('23:15'),
    'Pool-backed teaching events must start no later than 23:00.',
  )
})
