import type { AuthIdentity } from '../types/auth'

export type ResidentScheduledEventsState =
  | 'events_loading'
  | 'error'
  | 'no_active_periods'
  | 'empty'
  | 'ready'

export const getResidentScheduledEventsState = (input: {
  activePeriodCount: number
  eventsLoading: boolean
  eventsError: string | null
  eventCount: number
}): ResidentScheduledEventsState => {
  if (input.eventsLoading) {
    return 'events_loading'
  }
  if (input.eventsError) {
    return 'error'
  }
  if (input.activePeriodCount === 0) {
    return 'no_active_periods'
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
