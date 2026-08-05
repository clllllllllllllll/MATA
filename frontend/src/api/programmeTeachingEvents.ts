import { buildAdminDemoHeaders } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface ProgrammeTeachingEvent {
  id: string
  postingCode: string
  createdForProgrammeCode?: string
  teachingName: string
  teachingNameId?: string
  globalSessionTypeId?: string
  eventDate: string
  startTime: string
  endTime?: string
  durationHours?: number
  sessionTypeId?: string
  sessionTypeName?: string
  seriesId?: string
  cmePointsAwarded: boolean
  smcEventCode?: string
  isAdhoc: boolean
  createdByRole?: string
  attendanceCount: number
  externalAttendanceCount: number
  hasAttendance: boolean
  createdAt?: string
  updatedAt?: string
}

export interface ProgrammeTeachingNameOption {
  sourceKey: string
  keyword: string
  teachingNameId?: string
  globalSessionTypeId?: string
  sessionTypeId?: string
  sessionType?: string
  durationHours?: number
  isTracked?: boolean
  isGlobal: boolean
  postingCodes: string[]
}

export interface ProgrammeTeachingEventPayload {
  programmeCode: string
  postingCode: string
  teachingNameId?: string
  globalSessionTypeId?: string
  eventDate: string
  startTime: string
  cmePointsAwarded: boolean
  smcEventCode?: string
}

export interface ProgrammeTeachingEventDuplicatePayload {
  programmeCode: string
  eventDate: string
  startTime?: string
  postingCode?: string
  teachingNameId?: string
  globalSessionTypeId?: string
  cmePointsAwarded?: boolean
  smcEventCode?: string
}

interface ProgrammePcRequestContext {
  adminId: string
  adminProgrammes: string[]
}

const toNumber = (value: unknown): number | undefined => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) {
      return parsed
    }
  }
  return undefined
}

const optionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value : undefined

const sourceKeyFromIds = (
  teachingNameId?: string,
  globalSessionTypeId?: string,
): string | undefined => {
  if ((teachingNameId === undefined) === (globalSessionTypeId === undefined)) {
    return undefined
  }
  return teachingNameId
    ? `teaching-name:${teachingNameId}`
    : `global-session-type:${globalSessionTypeId}`
}

const toTeachingEvent = (value: Record<string, unknown>): ProgrammeTeachingEvent => ({
  id: String(value.id ?? ''),
  postingCode: String(value.posting_code ?? ''),
  createdForProgrammeCode: optionalString(value.created_for_programme_code),
  teachingName: String(value.teaching_name ?? ''),
  teachingNameId: optionalString(value.teaching_name_id),
  globalSessionTypeId: optionalString(value.global_session_type_id),
  eventDate: String(value.event_date ?? ''),
  startTime: String(value.start_time ?? ''),
  endTime: optionalString(value.end_time),
  durationHours: toNumber(value.duration_hours),
  sessionTypeId: optionalString(value.session_type_id),
  sessionTypeName: optionalString(value.session_type_name) ?? optionalString(value.session_type),
  seriesId: optionalString(value.series_id),
  cmePointsAwarded: Boolean(value.cme_points_awarded),
  smcEventCode: optionalString(value.smc_event_code),
  isAdhoc: Boolean(value.is_adhoc),
  createdByRole: optionalString(value.created_by_role),
  attendanceCount: toNumber(value.attendance_count) ?? 0,
  externalAttendanceCount: toNumber(value.external_attendance_count) ?? 0,
  hasAttendance: Boolean(value.has_attendance),
  createdAt: optionalString(value.created_at),
  updatedAt: optionalString(value.updated_at),
})

const toTeachingNameOption = (value: Record<string, unknown>): ProgrammeTeachingNameOption => {
  const teachingNameId = optionalString(value.teaching_name_id)
  const globalSessionTypeId = optionalString(value.global_session_type_id)
  return {
    sourceKey: sourceKeyFromIds(teachingNameId, globalSessionTypeId) ?? '',
    keyword: String(value.keyword ?? ''),
    teachingNameId,
    globalSessionTypeId,
    sessionTypeId: optionalString(value.session_type_id),
    sessionType: optionalString(value.session_type),
    durationHours: toNumber(value.duration_hours),
    isTracked: typeof value.is_tracked === 'boolean' ? value.is_tracked : undefined,
    isGlobal: Boolean(value.is_global),
    postingCodes: Array.isArray(value.posting_codes)
      ? value.posting_codes
          .filter((entry): entry is string => typeof entry === 'string' && entry.trim().length > 0)
          .map((entry) => entry.trim())
      : [],
  }
}

const toApiPayload = (payload: ProgrammeTeachingEventPayload): Record<string, unknown> => ({
  programme_code: payload.programmeCode,
  posting_code: payload.postingCode,
  teaching_name_id: payload.teachingNameId ?? null,
  global_session_type_id: payload.globalSessionTypeId ?? null,
  event_date: payload.eventDate,
  start_time: payload.startTime,
  cme_points_awarded: payload.cmePointsAwarded,
  smc_event_code: payload.smcEventCode ?? null,
})

const toDuplicateApiPayload = (payload: ProgrammeTeachingEventDuplicatePayload): Record<string, unknown> => ({
  programme_code: payload.programmeCode,
  event_date: payload.eventDate,
  start_time: payload.startTime ?? null,
  posting_code: payload.postingCode ?? null,
  teaching_name_id: payload.teachingNameId ?? null,
  global_session_type_id: payload.globalSessionTypeId ?? null,
  cme_points_awarded: payload.cmePointsAwarded ?? null,
  smc_event_code: payload.smcEventCode ?? null,
})

export const listProgrammeTeachingEvents = async (
  params: ProgrammePcRequestContext & {
    programmeCode?: string
    reportingPeriodId?: string
    dateFrom?: string
    dateTo?: string
    postingCode?: string
  },
): Promise<ProgrammeTeachingEvent[]> => {
  try {
    const response = await httpClient.get('/admin/programme-teaching-events', {
      params: {
        programme_code: params.programmeCode || undefined,
        reporting_period_id: params.reportingPeriodId || undefined,
        date_from: params.dateFrom || undefined,
        date_to: params.dateTo || undefined,
        posting_code: params.postingCode || undefined,
      },
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'programme'),
    })
    const rows = (response.data as { events?: unknown })?.events
    const events = Array.isArray(rows) ? rows : []
    return events
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toTeachingEvent)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const listProgrammeTeachingNameOptions = async (
  params: ProgrammePcRequestContext & {
    programmeCode: string
    reportingPeriodId?: string
    eventDate?: string
  },
): Promise<ProgrammeTeachingNameOption[]> => {
  try {
    const response = await httpClient.get('/admin/programme-teaching-name-options', {
      params: {
        programme_code: params.programmeCode,
        reporting_period_id: params.reportingPeriodId || undefined,
        event_date: params.eventDate || undefined,
      },
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'programme'),
    })
    const rows = (response.data as { options?: unknown })?.options
    const options = Array.isArray(rows) ? rows : []
    return options
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toTeachingNameOption)
      .filter((row) => row.sourceKey.length > 0 && row.keyword.trim().length > 0)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createProgrammeTeachingEvent = async (
  params: ProgrammePcRequestContext & { payload: ProgrammeTeachingEventPayload },
): Promise<ProgrammeTeachingEvent> => {
  try {
    const response = await httpClient.post(
      '/admin/programme-teaching-events',
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'programme'),
      },
    )
    return toTeachingEvent(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateProgrammeTeachingEvent = async (
  params: ProgrammePcRequestContext & {
    eventId: string
    payload: ProgrammeTeachingEventPayload
  },
): Promise<ProgrammeTeachingEvent> => {
  try {
    const response = await httpClient.put(
      `/admin/programme-teaching-events/${params.eventId}`,
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'programme'),
      },
    )
    return toTeachingEvent(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const duplicateProgrammeTeachingEvent = async (
  params: ProgrammePcRequestContext & {
    eventId: string
    payload: ProgrammeTeachingEventDuplicatePayload
  },
): Promise<ProgrammeTeachingEvent> => {
  try {
    const response = await httpClient.post(
      `/admin/programme-teaching-events/${params.eventId}/duplicate`,
      toDuplicateApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'programme'),
      },
    )
    return toTeachingEvent(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deleteProgrammeTeachingEvent = async (
  params: ProgrammePcRequestContext & {
    eventId: string
    programmeCode: string
  },
): Promise<{ deletedCount: number }> => {
  try {
    const response = await httpClient.delete(`/admin/programme-teaching-events/${params.eventId}`, {
      params: { programme_code: params.programmeCode },
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'programme'),
    })
    const row =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    return { deletedCount: toNumber(row.deleted_count) ?? 0 }
  } catch (error) {
    throw toApiRequestError(error)
  }
}
