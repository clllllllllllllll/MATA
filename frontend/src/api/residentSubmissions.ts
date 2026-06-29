import { buildResidentDemoHeaders } from './authHeaders'
import { ApiRequestError, httpClient, toApiRequestError } from './http'

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

export interface ResidentFilterOption {
  label: string
  postingCode?: string
  teachingName?: string
}

export interface ResidentEventFilterOptions {
  dateFrom?: string
  dateTo?: string
  postingOptions: ResidentFilterOption[]
  teachingNameOptions: ResidentFilterOption[]
}

export interface ResidentEventFilters {
  dateFrom?: string
  dateTo?: string
  teachingName?: string
  postingCode?: string
}

export interface ResidentAvailableEvent {
  id: string
  teachingName: string
  eventDate: string
  startTime: string
  endTime?: string
  postingCode: string
  detailsOfSession?: string
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
  filterOptions: ResidentEventFilterOptions
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

export interface ResidentAdhocTeachingOption {
  teachingName: string
  keyword: string
  sessionType?: string
  sessionTypeName?: string
  sessionTypeId?: string
  durationHours?: number
  postingCode: string
  postingLabel?: string
  reportingPeriodId?: string
  rYear?: string
  isTracked: boolean
  isGlobal: boolean
}

export interface ResidentAdhocOptionsResponse {
  date: string
  teachingDate: string
  available: boolean
  reason?: string | null
  message?: string | null
  reportingPeriodId?: string | null
  postingCode?: string | null
  postingLabel?: string | null
  rYear?: string | null
  options: ResidentAdhocTeachingOption[]
}

export interface ResidentAttendanceFilters {
  dateFrom?: string
  dateTo?: string
  postingCode?: string
  teachingName?: string
  source?: 'scheduled' | 'adhoc' | ''
  status?: 'submitted' | 'removed' | ''
  limit?: number
  offset?: number
}

export interface ResidentAttendanceHistoryRow {
  attendanceId: string
  teachingEventId: string
  teachingName: string
  detailsOfSession?: string
  eventDate: string
  startTime: string
  endTime?: string
  durationHours?: number
  isAdhoc: boolean
  source: 'scheduled' | 'adhoc'
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
  detailsOfSession: value.details_of_session ? String(value.details_of_session) : undefined,
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

const toFilterOption = (value: Record<string, unknown>): ResidentFilterOption => ({
  label: String(value.label ?? value.posting_code ?? value.teaching_name ?? ''),
  postingCode: value.posting_code ? String(value.posting_code) : undefined,
  teachingName: value.teaching_name ? String(value.teaching_name) : undefined,
})

const toEventFilterOptions = (value: unknown): ResidentEventFilterOptions => {
  const payload = typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : {}
  const postingRows = Array.isArray(payload.posting_options) ? payload.posting_options : []
  const teachingRows = Array.isArray(payload.teaching_name_options) ? payload.teaching_name_options : []
  return {
    dateFrom: payload.date_from ? String(payload.date_from) : undefined,
    dateTo: payload.date_to ? String(payload.date_to) : undefined,
    postingOptions: postingRows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toFilterOption),
    teachingNameOptions: teachingRows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toFilterOption),
  }
}

const toAdhocOption = (value: Record<string, unknown>): ResidentAdhocTeachingOption => ({
  teachingName: String(value.teaching_name ?? ''),
  keyword: String(value.keyword ?? value.teaching_name ?? ''),
  sessionType: value.session_type ? String(value.session_type) : undefined,
  sessionTypeName: value.session_type_name ? String(value.session_type_name) : undefined,
  sessionTypeId: value.session_type_id ? String(value.session_type_id) : undefined,
  durationHours: toNumber(value.duration_hours),
  postingCode: String(value.posting_code ?? ''),
  postingLabel: value.posting_label ? String(value.posting_label) : undefined,
  reportingPeriodId: value.reporting_period_id ? String(value.reporting_period_id) : undefined,
  rYear: value.r_year ? String(value.r_year) : undefined,
  isTracked: Boolean(value.is_tracked),
  isGlobal: Boolean(value.is_global),
})

const toHistoryRow = (value: Record<string, unknown>): ResidentAttendanceHistoryRow => ({
  attendanceId: String(value.attendance_id ?? ''),
  teachingEventId: String(value.teaching_event_id ?? ''),
  teachingName: String(value.teaching_name ?? ''),
  detailsOfSession: value.details_of_session ? String(value.details_of_session) : undefined,
  eventDate: String(value.event_date ?? ''),
  startTime: String(value.start_time ?? ''),
  endTime: value.end_time ? String(value.end_time) : undefined,
  durationHours: toNumber(value.duration_hours),
  isAdhoc: Boolean(value.is_adhoc),
  source: value.source === 'adhoc' || Boolean(value.is_adhoc) ? 'adhoc' : 'scheduled',
  postingCode: String(value.posting_code ?? ''),
  status: String(value.status ?? ''),
  submittedAt: value.submitted_at ? String(value.submitted_at) : undefined,
})

const buildParams = (values: Record<string, string | number | undefined>) => {
  const params: Record<string, string | number> = {}
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      params[key] = value
    }
  })
  return params
}

export const listResidentEvents = async (
  filters: ResidentEventFilters = {},
): Promise<ResidentEventsResponse> => {
  try {
    const response = await httpClient.get('/resident/events', {
      headers: buildResidentDemoHeaders(),
      params: buildParams({
        date_from: filters.dateFrom,
        date_to: filters.dateTo,
        teaching_name: filters.teachingName,
        posting_code: filters.postingCode,
      }),
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
      filterOptions: toEventFilterOptions(payload.filter_options),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

const ADHOC_OPTIONS_PATH = '/resident/adhoc-teaching-options'
const ADHOC_OPTIONS_ALIAS_PATH = '/resident/adhoc-teaching/options'

export const getResidentAdhocTeachingOptions = async (
  teachingDate: string,
): Promise<ResidentAdhocOptionsResponse> => {
  try {
    let response
    try {
      response = await httpClient.get(ADHOC_OPTIONS_PATH, {
        headers: buildResidentDemoHeaders(),
        params: { date: teachingDate },
      })
    } catch (error) {
      const requestError = toApiRequestError(error)
      if (requestError.status !== 404) {
        throw requestError
      }
      response = await httpClient.get(ADHOC_OPTIONS_ALIAS_PATH, {
        headers: buildResidentDemoHeaders(),
        params: { teaching_date: teachingDate },
      })
    }
    const payload =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    const options = Array.isArray(payload.options) ? payload.options : []
    return {
      date: String(payload.date ?? teachingDate),
      teachingDate: String(payload.teaching_date ?? payload.date ?? teachingDate),
      available: Boolean(payload.available),
      reason: typeof payload.reason === 'string' ? payload.reason : null,
      message: typeof payload.message === 'string' ? payload.message : null,
      reportingPeriodId: payload.reporting_period_id ? String(payload.reporting_period_id) : null,
      postingCode: payload.posting_code ? String(payload.posting_code) : null,
      postingLabel: payload.posting_label ? String(payload.posting_label) : null,
      rYear: payload.r_year ? String(payload.r_year) : null,
      options: options
        .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
        .map(toAdhocOption),
    }
  } catch (error) {
    throw error instanceof ApiRequestError ? error : toApiRequestError(error)
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
  teachingDate: string
  startTime: string
  teachingName: string
  detailsOfSession?: string
}): Promise<ResidentAdhocSubmitResponse> => {
  try {
    const response = await httpClient.post(
      '/resident/adhoc-teaching',
      {
        teaching_date: payload.teachingDate,
        start_time: payload.startTime,
        teaching_name: payload.teachingName,
        details_of_session: payload.detailsOfSession || undefined,
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

export const listResidentAttendance = async (
  filters: ResidentAttendanceFilters = {},
): Promise<ResidentAttendanceHistoryRow[]> => {
  try {
    const response = await httpClient.get('/resident/attendance', {
      headers: buildResidentDemoHeaders(),
      params: buildParams({
        date_from: filters.dateFrom,
        date_to: filters.dateTo,
        posting_code: filters.postingCode,
        teaching_name: filters.teachingName,
        source: filters.source,
        status: filters.status,
        limit: filters.limit,
        offset: filters.offset,
      }),
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

export const removeResidentAttendance = async (attendanceId: string): Promise<{ status: string }> => {
  try {
    const response = await httpClient.delete(`/resident/attendance/${attendanceId}`, {
      headers: buildResidentDemoHeaders(),
    })
    const payload =
      typeof response.data === 'object' && response.data !== null
        ? (response.data as Record<string, unknown>)
        : {}
    return { status: String(payload.status ?? 'removed') }
  } catch (error) {
    throw toApiRequestError(error)
  }
}
