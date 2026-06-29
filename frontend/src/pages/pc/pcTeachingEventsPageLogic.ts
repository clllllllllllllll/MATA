import type {
  ProgrammeTeachingEvent,
  ProgrammeTeachingEventPayload,
  ProgrammeTeachingNameOption,
} from '../../api/programmeTeachingEvents'
import { teachingEventCreatedByDisplay } from '../../utils/teachingEventSource.ts'

export interface ProgrammeTeachingEventFormState {
  programmeCode: string
  postingCode: string
  teachingName: string
  eventDate: string
  startTime: string
  cmePointsAwarded: boolean
  smcEventCode: string
}

export const EMPTY_PROGRAMME_TEACHING_EVENT_FORM: ProgrammeTeachingEventFormState = {
  programmeCode: '',
  postingCode: '',
  teachingName: '',
  eventDate: '',
  startTime: '',
  cmePointsAwarded: false,
  smcEventCode: '',
}

export const createdByRoleLabel = (createdByRole?: string | null): string =>
  teachingEventCreatedByDisplay(createdByRole)

export const canMutateProgrammeTeachingEvent = (event?: Pick<ProgrammeTeachingEvent, 'hasAttendance'> | null) =>
  event ? !event.hasAttendance : false

export const postingOptionsForTeachingName = (
  options: ProgrammeTeachingNameOption[],
  teachingName: string,
): string[] => {
  const selectedKeyword = teachingName.trim()
  if (!selectedKeyword) {
    return []
  }
  return options.find((option) => option.keyword.trim() === selectedKeyword)?.postingCodes ?? []
}

export const buildProgrammeTeachingEventPayload = (
  formState: ProgrammeTeachingEventFormState,
): ProgrammeTeachingEventPayload => ({
  programmeCode: formState.programmeCode.trim(),
  postingCode: formState.postingCode.trim(),
  teachingName: formState.teachingName.trim(),
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
  teachingName: event.teachingName,
  eventDate: event.eventDate,
  startTime: event.startTime.slice(0, 5),
  cmePointsAwarded: event.cmePointsAwarded,
  smcEventCode: event.smcEventCode ?? '',
})
