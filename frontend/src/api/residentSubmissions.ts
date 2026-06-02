import { buildResidentDemoHeaders } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

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

export interface ResidentPostingCapability {
  postingCode: string
  supportsSecretaryEvents: boolean
}

export interface ResidentAvailableEvent {
  id: string
  teachingName: string
  eventDate: string
  startTime: string
  endTime?: string
  postingCode: string
  sessionType?: string
  sessionTypeName?: string
  durationHours?: number
  isGlobal: boolean
  isAdhoc: boolean
  alreadySubmitted: boolean
}

export interface ResidentEventsResponse {
  events: ResidentAvailableEvent[]
  reason?: string | null
  adHocAllowed?: boolean
  message?: string | null
  postingCapabilities: ResidentPostingCapability[]
}

export interface ResidentAttendanceSubmitResponse {
  submitted: number
  submittedEvents: ResidentAvailableEvent[]
  errors: string[]
  complianceWarning?: string | null
}

export interface ResidentAdhocSubmitResponse {
  event: ResidentAvailableEvent
  attendance: {
    id: string
    residentId: string
    teachingEventId: string
    status: string
    postingCode?: string
  }
  complianceWarning?: string | null
}

export interface ResidentAttendanceHistoryRow {
  attendanceId: string
  teachingEventId: string
  teachingName: string
  eventDate: string
  startTime: string
  endTime?: string
  durationHours?: number
  isAdhoc: boolean
  postingCode: string
  status: string
  submittedAt?: string
}

const toResidentEvent = (value: Record<string, unknown>): ResidentAvailableEvent => ({
  id: String(value.id ?? ''),
  teachingName: String(value.teaching_name ?? ''),
  eventDate: String(value.event_date ?? ''),
  startTime: String(value.start_time ?? ''),
  endTime: value.end_time ? String(value.end_time) : undefined,
  postingCode: String(value.posting_code ?? ''),
  sessionType: value.session_type ? String(value.session_type) : undefined,
  sessionTypeName: value.session_type_name ? String(value.session_type_name) : undefined,
  durationHours: toNumber(value.duration_hours),
  isGlobal: Boolean(value.is_global),
  isAdhoc: Boolean(value.is_adhoc),
  alreadySubmitted: Boolean(value.already_submitted),
})

const toPostingCapability = (value: Record<string, unknown>): ResidentPostingCapability => ({
  postingCode: String(value.posting_code ?? ''),
  supportsSecretaryEvents: Boolean(value.supports_secretary_events),
})

const toHistoryRow = (value: Record<string, unknown>): ResidentAttendanceHistoryRow => ({
  attendanceId: String(value.attendance_id ?? ''),
  teachingEventId: String(value.teaching_event_id ?? ''),
  teachingName: String(value.teaching_name ?? ''),
  eventDate: String(value.event_date ?? ''),
  startTime: String(value.start_time ?? ''),
  endTime: value.end_time ? String(value.end_time) : undefined,
  durationHours: toNumber(value.duration_hours),
  isAdhoc: Boolean(value.is_adhoc),
  postingCode: String(value.posting_code ?? ''),
  status: String(value.status ?? ''),
  submittedAt: value.submitted_at ? String(value.submitted_at) : undefined,
})

export const listResidentEvents = async (): Promise<ResidentEventsResponse> => {
  try {
    const response = await httpClient.get('/resident/events', {
      headers: buildResidentDemoHeaders(),
    })
    const payload =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    const eventRows = Array.isArray(payload.events) ? payload.events : []
    const capabilityRows = Array.isArray(payload.posting_capabilities) ? payload.posting_capabilities : []
    return {
      events: eventRows
        .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
        .map(toResidentEvent),
      reason: typeof payload.reason === 'string' ? payload.reason : null,
      adHocAllowed: typeof payload.ad_hoc_allowed === 'boolean' ? payload.ad_hoc_allowed : undefined,
      message: typeof payload.message === 'string' ? payload.message : null,
      postingCapabilities: capabilityRows
        .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
        .map(toPostingCapability),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const submitResidentAttendance = async (
  eventIds: string[],
): Promise<ResidentAttendanceSubmitResponse> => {
  try {
    const response = await httpClient.post(
      '/resident/attendance',
      {
        event_ids: eventIds,
      },
      {
        headers: buildResidentDemoHeaders(),
      },
    )
    const payload =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    const submittedEvents = Array.isArray(payload.submitted_events) ? payload.submitted_events : []
    return {
      submitted: toNumber(payload.submitted) ?? 0,
      submittedEvents: submittedEvents
        .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
        .map(toResidentEvent),
      errors: Array.isArray(payload.errors)
        ? payload.errors.filter((entry): entry is string => typeof entry === 'string')
        : [],
      complianceWarning:
        typeof payload.compliance_warning === 'string' ? payload.compliance_warning : null,
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const submitResidentAdhocTeaching = async (payload: {
  date: string
  startTime: string
  teachingName: string
}): Promise<ResidentAdhocSubmitResponse> => {
  try {
    const response = await httpClient.post(
      '/resident/adhoc-teaching',
      {
        date: payload.date,
        start_time: payload.startTime,
        teaching_name: payload.teachingName,
      },
      {
        headers: buildResidentDemoHeaders(),
      },
    )
    const body =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    const event =
      typeof body.event === 'object' && body.event !== null
        ? toResidentEvent(body.event as Record<string, unknown>)
        : toResidentEvent({})
    const attendance =
      typeof body.attendance === 'object' && body.attendance !== null
        ? (body.attendance as Record<string, unknown>)
        : {}
    return {
      event,
      attendance: {
        id: String(attendance.id ?? ''),
        residentId: String(attendance.resident_id ?? ''),
        teachingEventId: String(attendance.teaching_event_id ?? ''),
        status: String(attendance.status ?? ''),
        postingCode: attendance.posting_code ? String(attendance.posting_code) : undefined,
      },
      complianceWarning:
        typeof body.compliance_warning === 'string' ? body.compliance_warning : null,
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const listResidentAttendanceHistory = async (): Promise<ResidentAttendanceHistoryRow[]> => {
  try {
    const response = await httpClient.get('/resident/attendance-history', {
      headers: buildResidentDemoHeaders(),
    })
    const payload =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    const rows = Array.isArray(payload.attendance) ? payload.attendance : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toHistoryRow)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
