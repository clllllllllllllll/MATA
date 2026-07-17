import type { AuthIdentity } from '../types/auth'

export type ResidentScheduledEventsState =
  | 'periods_loading'
  | 'events_loading'
  | 'error'
  | 'no_active_periods'
  | 'empty'
  | 'ready'

export const getResidentScheduledEventsState = (input: {
  periodsLoading: boolean
  periodsError: string | null
  activePeriodCount: number
  eventsLoading: boolean
  eventsError: string | null
  eventCount: number
}): ResidentScheduledEventsState => {
  if (input.periodsLoading) {
    return 'periods_loading'
  }
  if (input.periodsError) {
    return 'error'
  }
  if (input.activePeriodCount === 0) {
    return 'no_active_periods'
  }
  if (input.eventsLoading) {
    return 'events_loading'
  }
  if (input.eventsError) {
    return 'error'
  }
  return input.eventCount > 0 ? 'ready' : 'empty'
}

export const getResidentPortalIdentitySubtitle = (identity: AuthIdentity | null): string => {
  if (identity?.role === 'resident') {
    return `${identity.programmeCode} - MCR ${identity.mcr}`
  }
  if (identity?.role === 'external_resident') {
    return `${identity.homeCluster} - MCR ${identity.mcr}`
  }
  return 'Loading authenticated resident identity...'
}
