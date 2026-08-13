import type {
  ProgrammeTeachingEvent,
  ProgrammeTeachingEventPayload,
  ProgrammeTeachingNameOption,
} from '../../api/programmeTeachingEvents'
import { teachingEventCreatedByDisplay } from '../../utils/teachingEventSource.ts'

export interface ProgrammeTeachingEventFormState {
  programmeCode: string
  postingCode: string
  sourceKey: string
  eventDate: string
  startTime: string
  cmePointsAwarded: boolean
  smcEventCode: string
}

export const EMPTY_PROGRAMME_TEACHING_EVENT_FORM: ProgrammeTeachingEventFormState = {
  programmeCode: '',
  postingCode: '',
  sourceKey: '',
  eventDate: '',
  startTime: '',
  cmePointsAwarded: false,
  smcEventCode: '',
}

export const createdByRoleLabel = (createdByRole?: string | null): string =>
  teachingEventCreatedByDisplay(createdByRole)

export const canMutateProgrammeTeachingEvent = (event?: Pick<ProgrammeTeachingEvent, 'hasAttendance'> | null) =>
  event ? !event.hasAttendance : false

export const postingOptionsForSource = (
  options: ProgrammeTeachingNameOption[],
  sourceKey: string,
): string[] => {
  const selectedSourceKey = sourceKey.trim()
  if (!selectedSourceKey) {
    return []
  }
  return options.find((option) => option.sourceKey === selectedSourceKey)?.postingCodes ?? []
}

export const buildProgrammeTeachingEventPayload = (
  formState: ProgrammeTeachingEventFormState,
  selectedOption?: ProgrammeTeachingNameOption,
): ProgrammeTeachingEventPayload => ({
  programmeCode: formState.programmeCode.trim(),
  postingCode: formState.postingCode.trim(),
  teachingNameId: selectedOption?.teachingNameId,
  globalSessionTypeId: selectedOption?.globalSessionTypeId,
  eventDate: formState.eventDate,
  startTime: formState.startTime,
  cmePointsAwarded: formState.cmePointsAwarded,
  smcEventCode: formState.smcEventCode.trim() || undefined,
})

export const formStateFromEvent = (
  event: ProgrammeTeachingEvent,
  fallbackProgrammeCode: string,
): ProgrammeTeachingEventFormState => ({
  programmeCode: event.createdForProgrammeCode || fallbackProgrammeCode,
  postingCode: event.postingCode,
  sourceKey: event.teachingNameId
    ? `teaching-name:${event.teachingNameId}`
    : event.globalSessionTypeId
      ? `global-session-type:${event.globalSessionTypeId}`
      : '',
  eventDate: event.eventDate,
  startTime: event.startTime.slice(0, 5),
  cmePointsAwarded: event.cmePointsAwarded,
  smcEventCode: event.smcEventCode ?? '',
})
