export interface SecretaryEventSourceContext {
  teachingNameId?: string
  globalSessionTypeId?: string
  sourceProgrammeCode?: string
}

export type SecretaryEventProgrammeContext =
  | { kind: 'not_pool_backed' }
  | { kind: 'missing_pool_programme' }
  | { kind: 'pool_backed'; programmeCode: string }

export const resolveSecretaryEventProgrammeContext = (
  event: SecretaryEventSourceContext,
): SecretaryEventProgrammeContext => {
  const programmeCode = event.sourceProgrammeCode?.trim()
  if (programmeCode) {
    return { kind: 'pool_backed', programmeCode }
  }
  if (event.teachingNameId) {
    return { kind: 'missing_pool_programme' }
  }
  return { kind: 'not_pool_backed' }
}

export const shouldTemporarilyRetainPoolSource = ({
  event,
  selectedProgrammeCode,
  optionsState,
  programmeSwitchPending,
  sourceIsAvailable,
}: {
  event: SecretaryEventSourceContext
  selectedProgrammeCode: string
  optionsState: 'loading' | 'ready' | 'empty' | 'error' | 'unavailable'
  programmeSwitchPending: boolean
  sourceIsAvailable: boolean
}): boolean => {
  const programmeContext = resolveSecretaryEventProgrammeContext(event)
  return (
    programmeContext.kind === 'pool_backed'
    && Boolean(event.teachingNameId)
    && programmeContext.programmeCode === selectedProgrammeCode
    && optionsState === 'loading'
    && programmeSwitchPending
    && !sourceIsAvailable
  )
}

export const isCurrentTeachingSourceEligible = (
  sourceKey: string,
  currentOptions: ReadonlyArray<{ sourceKey: string }>,
): boolean => sourceKey.length > 0 && currentOptions.some((option) => option.sourceKey === sourceKey)

export const serverComputedPoolEndTime = (
  startTime: string,
  durationHours = 1,
): string | null => {
  const match = /^(?<hour>[01]\d|2[0-3]):(?<minute>[0-5]\d)$/.exec(startTime)
  if (!match?.groups || !Number.isFinite(durationHours) || durationHours <= 0) {
    return null
  }
  const startMinutes = Number(match.groups.hour) * 60 + Number(match.groups.minute)
  const endMinutes = (startMinutes + Math.round(durationHours * 60)) % (24 * 60)
  const hour = Math.floor(endMinutes / 60)
  const minute = endMinutes % 60
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`
}

export const poolStartTimeValidationError = (startTime: string): string | null =>
  startTime > '23:00'
    ? 'Pool-backed teaching events must start no later than 23:00.'
    : null
