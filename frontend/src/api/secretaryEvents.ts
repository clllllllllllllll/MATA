import { httpClient, toApiRequestError } from './http'
import { buildSecretaryDemoHeaders } from './authHeaders'

export interface SecretaryTeachingEvent {
  id: string
  postingCode: string
  teachingName: string
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
  createdAt?: string
  updatedAt?: string
}

export interface TeachingNameOption {
  keyword: string
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

const toTeachingEvent = (value: Record<string, unknown>): SecretaryTeachingEvent => ({
  id: String(value.id ?? ''),
  postingCode: String(value.posting_code ?? ''),
  teachingName: String(value.teaching_name ?? ''),
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
  createdByRole: value.created_by_role ? String(value.created_by_role) : undefined,
  createdAt: value.created_at ? String(value.created_at) : undefined,
  updatedAt: value.updated_at ? String(value.updated_at) : undefined,
})

const toTeachingNameOption = (value: Record<string, unknown>): TeachingNameOption => ({
  keyword: String(value.keyword ?? ''),
  sessionTypeId: value.session_type_id ? String(value.session_type_id) : undefined,
  sessionType: value.session_type ? String(value.session_type) : undefined,
  durationHours: toNumber(value.duration_hours),
  isTracked: typeof value.is_tracked === 'boolean' ? value.is_tracked : undefined,
  isGlobal: typeof value.is_global === 'boolean' ? value.is_global : undefined,
  postingCodes: Array.isArray(value.posting_codes)
    ? value.posting_codes
        .filter((entry): entry is string => typeof entry === 'string' && entry.trim().length > 0)
        .map((entry) => entry.trim())
    : undefined,
})

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

export const listSecretaryTeachingNameOptions = async (): Promise<TeachingNameOption[]> => {
  try {
    const response = await httpClient.get('/secretary/teaching-name-options', {
      headers: buildSecretaryDemoHeaders(),
    })
    const rows = (response.data as { options?: unknown })?.options
    const options = Array.isArray(rows) ? rows : []
    const mapped = options
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toTeachingNameOption)
      .filter((row) => row.keyword.trim().length > 0)

    const deduped = new Map<string, TeachingNameOption>()
    mapped.forEach((option) => {
      const keyword = option.keyword.trim()
      if (!deduped.has(keyword)) {
        deduped.set(keyword, {
          ...option,
          keyword,
        })
      }
    })
    return [...deduped.values()]
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export interface CreateSecretaryTeachingEventRequest {
  teachingName: string
  eventDate: string
  startTime: string
  cmePointsAwarded: boolean
  smcEventCode?: string
}

export const createSecretaryTeachingEvent = async (
  payload: CreateSecretaryTeachingEventRequest,
): Promise<SecretaryTeachingEvent> => {
  try {
    const response = await httpClient.post(
      '/secretary/teaching-events',
      {
        teaching_name: payload.teachingName,
        event_date: payload.eventDate,
        start_time: payload.startTime,
        cme_points_awarded: payload.cmePointsAwarded,
        smc_event_code: payload.smcEventCode ?? null,
      },
      {
        headers: buildSecretaryDemoHeaders(),
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

export const deleteSecretaryTeachingEvent = async (eventId: string): Promise<{ deletedCount: number }> => {
  try {
    const response = await httpClient.delete(`/secretary/teaching-events/${eventId}`, {
      headers: buildSecretaryDemoHeaders(),
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
