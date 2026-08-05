import { httpClient, toApiRequestError } from './http'
import { buildSecretaryDemoHeaders } from './authHeaders'
import type { ReportingPeriodOption } from '../types/upload'
import { parseReportingPeriodListResponse } from '../utils/reportingPeriodResponse'

export interface SecretaryTeachingEvent {
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
  hasAttendance?: boolean
  createdByRole?: string
  createdAt?: string
  updatedAt?: string
}

export interface TeachingNameOption {
  sourceKey: string
  keyword: string
  teachingNameId?: string
  globalSessionTypeId?: string
  sessionTypeId?: string
  sessionType?: string
  durationHours?: number
  isTracked?: boolean
  isGlobal?: boolean
  postingCodes?: string[]
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

export const sourceKeyForSecretaryTeachingEvent = (
  event: Pick<SecretaryTeachingEvent, 'teachingNameId' | 'globalSessionTypeId'>,
): string => sourceKeyFromIds(event.teachingNameId, event.globalSessionTypeId) ?? ''

const toTeachingEvent = (value: Record<string, unknown>): SecretaryTeachingEvent => ({
  id: String(value.id ?? ''),
  postingCode: String(value.posting_code ?? ''),
  createdForProgrammeCode: value.created_for_programme_code ? String(value.created_for_programme_code) : undefined,
  teachingName: String(value.teaching_name ?? ''),
  teachingNameId: optionalString(value.teaching_name_id),
  globalSessionTypeId: optionalString(value.global_session_type_id),
  eventDate: String(value.event_date ?? ''),
  startTime: String(value.start_time ?? ''),
  endTime: value.end_time ? String(value.end_time) : undefined,
  durationHours: toNumber(value.duration_hours),
  sessionTypeId: value.session_type_id ? String(value.session_type_id) : undefined,
  sessionTypeName:
    value.session_type_name
      ? String(value.session_type_name)
      : value.session_type
        ? String(value.session_type)
        : undefined,
  seriesId: value.series_id ? String(value.series_id) : undefined,
  cmePointsAwarded: Boolean(value.cme_points_awarded),
  smcEventCode: value.smc_event_code ? String(value.smc_event_code) : undefined,
  isAdhoc: Boolean(value.is_adhoc),
  hasAttendance: Boolean(value.has_attendance),
  createdByRole: value.created_by_role ? String(value.created_by_role) : undefined,
  createdAt: value.created_at ? String(value.created_at) : undefined,
  updatedAt: value.updated_at ? String(value.updated_at) : undefined,
})

const toTeachingNameOption = (value: Record<string, unknown>): TeachingNameOption => {
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
    isGlobal: typeof value.is_global === 'boolean' ? value.is_global : undefined,
    postingCodes: Array.isArray(value.posting_codes)
      ? value.posting_codes
          .filter((entry): entry is string => typeof entry === 'string' && entry.trim().length > 0)
          .map((entry) => entry.trim())
      : undefined,
  }
}

export const listSecretaryTeachingEvents = async (params?: {
  dateFrom?: string
  dateTo?: string
}): Promise<SecretaryTeachingEvent[]> => {
  try {
    const response = await httpClient.get('/secretary/teaching-events', {
      params: {
        date_from: params?.dateFrom || undefined,
        date_to: params?.dateTo || undefined,
      },
      headers: buildSecretaryDemoHeaders(),
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

export const listSecretaryReportingPeriods = async (): Promise<ReportingPeriodOption[]> => {
  try {
    const response = await httpClient.get('/secretary/reporting-periods', {
      headers: buildSecretaryDemoHeaders(),
    })
    return parseReportingPeriodListResponse(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const listSecretaryTeachingNameOptions = async (params?: {
  reportingPeriodId?: string
  eventDate?: string
}): Promise<TeachingNameOption[]> => {
  try {
    const response = await httpClient.get('/secretary/teaching-name-options', {
      params: {
        reporting_period_id: params?.reportingPeriodId || undefined,
        event_date: params?.eventDate || undefined,
      },
      headers: buildSecretaryDemoHeaders(),
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

export interface CreateSecretaryTeachingEventRequest {
  teachingNameId?: string
  globalSessionTypeId?: string
  eventDate: string
  startTime: string
  cmePointsAwarded: boolean
  smcEventCode?: string
}

export const createSecretaryTeachingEvent = async (
  payload: CreateSecretaryTeachingEventRequest,
  actorName?: string,
): Promise<SecretaryTeachingEvent> => {
  try {
    const response = await httpClient.post(
      '/secretary/teaching-events',
      {
        teaching_name_id: payload.teachingNameId ?? null,
        global_session_type_id: payload.globalSessionTypeId ?? null,
        event_date: payload.eventDate,
        start_time: payload.startTime,
        cme_points_awarded: payload.cmePointsAwarded,
        smc_event_code: payload.smcEventCode ?? null,
      },
      {
        headers: buildSecretaryDemoHeaders({ actorName }),
      },
    )
    const row =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    return toTeachingEvent(row)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export interface UpdateSecretaryTeachingEventRequest {
  teachingNameId?: string
  globalSessionTypeId?: string
  eventDate: string
  startTime: string
  cmePointsAwarded: boolean
  smcEventCode?: string
}

export const updateSecretaryTeachingEvent = async (
  eventId: string,
  payload: UpdateSecretaryTeachingEventRequest,
  actorName?: string,
): Promise<SecretaryTeachingEvent> => {
  try {
    const response = await httpClient.put(
      `/secretary/teaching-events/${eventId}`,
      {
        teaching_name_id: payload.teachingNameId ?? null,
        global_session_type_id: payload.globalSessionTypeId ?? null,
        event_date: payload.eventDate,
        start_time: payload.startTime,
        cme_points_awarded: payload.cmePointsAwarded,
        smc_event_code: payload.smcEventCode ?? null,
      },
      {
        headers: buildSecretaryDemoHeaders({ actorName }),
      },
    )
    const row =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    return toTeachingEvent(row)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deleteSecretaryTeachingEvent = async (
  eventId: string,
  actorName?: string,
): Promise<{ deletedCount: number }> => {
  try {
    const response = await httpClient.delete(`/secretary/teaching-events/${eventId}`, {
      headers: buildSecretaryDemoHeaders({ actorName }),
    })
    const row =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    const deletedCount = typeof row.deleted_count === 'number' ? row.deleted_count : Number(row.deleted_count ?? 0)
    return { deletedCount: Number.isFinite(deletedCount) ? deletedCount : 0 }
  } catch (error) {
    throw toApiRequestError(error)
  }
}
