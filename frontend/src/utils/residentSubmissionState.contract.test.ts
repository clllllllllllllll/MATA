import {
  getResidentPortalIdentitySubtitle,
  getResidentScheduledEventsState,
} from './residentSubmissionState.ts'
import type { AuthIdentity } from '../types/auth.ts'

const assertEqual = <T>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const baseState = {
  periodsLoading: false,
  periodsError: null,
  activePeriodCount: 1,
  eventsLoading: false,
  eventsError: null,
  eventCount: 0,
}

assertEqual(
  getResidentScheduledEventsState({ ...baseState, periodsLoading: true }),
  'periods_loading',
  'reporting-period loading is distinct',
)
assertEqual(
  getResidentScheduledEventsState({ ...baseState, eventsLoading: true }),
  'events_loading',
  'event loading is distinct',
)
assertEqual(
  getResidentScheduledEventsState({ ...baseState, eventsError: 'network' }),
  'error',
  'event request errors are distinct',
)
assertEqual(
  getResidentScheduledEventsState({ ...baseState, activePeriodCount: 0 }),
  'no_active_periods',
  'no active periods is distinct',
)
assertEqual(
  getResidentScheduledEventsState(baseState),
  'empty',
  'active periods with no events is distinct',
)
assertEqual(
  getResidentScheduledEventsState({ ...baseState, eventCount: 1 }),
  'ready',
  'eligible event state is ready',
)

const nativeIdentity: AuthIdentity = {
  role: 'resident',
  subjectId: 'resident-1',
  name: 'Actual Resident',
  programmeCode: 'GERI',
  mcr: 'M64471D',
}
assertEqual(
  getResidentPortalIdentitySubtitle(nativeIdentity),
  'GERI - MCR M64471D',
  'native resident subtitle uses authenticated identity',
)

const externalIdentity: AuthIdentity = {
  role: 'external_resident',
  subjectId: 'external-1',
  name: 'External Resident',
  homeCluster: 'NUH',
  mcr: 'M75582E',
}
assertEqual(
  getResidentPortalIdentitySubtitle(externalIdentity),
  'NUH - MCR M75582E',
  'external resident subtitle uses authenticated identity',
)
