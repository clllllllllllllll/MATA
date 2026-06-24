import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface AdminSecretaryEventListItem {
  id: string
  teachingName: string
  postingCode: string
  postingDisplayName?: string | null
  eventDate: string
  startTime: string
  endTime?: string | null
  durationHours?: number | null
  cmePointsAwarded: boolean
  smcEventCode?: string | null
  sessionTypeId?: string | null
  sessionTypeName?: string | null
  seriesId?: string | null
  isRecurring: boolean
  attendanceCount: number
  externalAttendanceCount: number
  hasAttendance: boolean
  createdByRole?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export interface AdminSecretaryEventListSummary {
  totalEvents: number
  withAttendance: number
  withoutAttendance: number
  totalAttendanceCount: number
  totalExternalAttendanceCount: number
}

export interface AdminSecretaryEventListResponse {
  items: AdminSecretaryEventListItem[]
  total: number
  limit: number
  offset: number
  summary: AdminSecretaryEventListSummary
}

export interface AdminSecretaryEventPostingMetadata {
  code: string
  displayName?: string | null
  institution?: string | null
  department?: string | null
}

export interface AdminSecretaryEventRecurrenceMetadata {
  seriesId: string
  recurrencePattern?: string | null
  recurrenceInterval?: number | null
  daysOfWeek: string[]
  endType?: string | null
  endDate?: string | null
  endAfterCount?: number | null
}

export interface AdminSecretaryEventAttendanceCounts {
  native: number
  external: number
  total: number
}

export interface AdminSecretaryEventDetail extends AdminSecretaryEventListItem {
  posting: AdminSecretaryEventPostingMetadata
  recurrence?: AdminSecretaryEventRecurrenceMetadata | null
  attendanceCounts: AdminSecretaryEventAttendanceCounts
  notes: {
    eventSource: string
    sessionTypeAuthority: string
  }
}

export interface ListAdminSecretaryEventsParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  reportingPeriodId?: string
  postingCode?: string
  dateFrom?: string
  dateTo?: string
  teachingName?: string
  search?: string
  hasAttendance?: boolean | null
  sessionTypeId?: string
  seriesId?: string
  limit?: number
  offset?: number
}

export interface GetAdminSecretaryEventParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  eventId: string
}

const toRecord = (value: unknown): Record<string, unknown> => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return {}
  }
  return value as Record<string, unknown>
}

const toRecordArray = (value: unknown): Record<string, unknown>[] => {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item): item is Record<string, unknown> => {
    return typeof item === 'object' && item !== null && !Array.isArray(item)
  })
}

const optionalString = (value: unknown): string | null => {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || null
}

const finiteNumber = (value: unknown, fallback = 0): number => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : fallback
  }
  return fallback
}

const optionalNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') {
    return null
  }
  const parsed = finiteNumber(value, Number.NaN)
  return Number.isFinite(parsed) ? parsed : null
}

const toBoolean = (value: unknown): boolean => value === true || value === 'true'

const toStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => String(item)).filter(Boolean)
}

const addStringParam = (
  queryParams: Record<string, string | number | boolean>,
  key: string,
  value?: string | null,
) => {
  const text = value?.trim()
  if (text) {
    queryParams[key] = text
  }
}

const toListItem = (value: Record<string, unknown>): AdminSecretaryEventListItem => ({
  id: String(value.id ?? ''),
  teachingName: String(value.teaching_name ?? ''),
  postingCode: String(value.posting_code ?? ''),
  postingDisplayName: optionalString(value.posting_display_name),
  eventDate: String(value.event_date ?? ''),
  startTime: String(value.start_time ?? ''),
  endTime: optionalString(value.end_time),
  durationHours: optionalNumber(value.duration_hours),
  cmePointsAwarded: toBoolean(value.cme_points_awarded),
  smcEventCode: optionalString(value.smc_event_code),
  sessionTypeId: optionalString(value.session_type_id),
  sessionTypeName: optionalString(value.session_type_name),
  seriesId: optionalString(value.series_id),
  isRecurring: toBoolean(value.is_recurring),
  attendanceCount: finiteNumber(value.attendance_count),
  externalAttendanceCount: finiteNumber(value.external_attendance_count),
  hasAttendance: toBoolean(value.has_attendance),
  createdByRole: optionalString(value.created_by_role),
  createdAt: optionalString(value.created_at),
  updatedAt: optionalString(value.updated_at),
})

const toSummary = (value: unknown): AdminSecretaryEventListSummary => {
  const record = toRecord(value)
  return {
    totalEvents: finiteNumber(record.total_events),
    withAttendance: finiteNumber(record.with_attendance),
    withoutAttendance: finiteNumber(record.without_attendance),
    totalAttendanceCount: finiteNumber(record.total_attendance_count),
    totalExternalAttendanceCount: finiteNumber(record.total_external_attendance_count),
  }
}

const toPosting = (value: unknown): AdminSecretaryEventPostingMetadata => {
  const record = toRecord(value)
  return {
    code: String(record.code ?? ''),
    displayName: optionalString(record.display_name),
    institution: optionalString(record.institution),
    department: optionalString(record.department),
  }
}

const toRecurrence = (value: unknown): AdminSecretaryEventRecurrenceMetadata | null => {
  const record = toRecord(value)
  const seriesId = optionalString(record.series_id)
  if (!seriesId) {
    return null
  }
  return {
    seriesId,
    recurrencePattern: optionalString(record.recurrence_pattern),
    recurrenceInterval: optionalNumber(record.recurrence_interval),
    daysOfWeek: toStringArray(record.days_of_week),
    endType: optionalString(record.end_type),
    endDate: optionalString(record.end_date),
    endAfterCount: optionalNumber(record.end_after_count),
  }
}

const toAttendanceCounts = (value: unknown): AdminSecretaryEventAttendanceCounts => {
  const record = toRecord(value)
  return {
    native: finiteNumber(record.native),
    external: finiteNumber(record.external),
    total: finiteNumber(record.total),
  }
}

const toDetail = (value: Record<string, unknown>): AdminSecretaryEventDetail => ({
  ...toListItem(value),
  posting: toPosting(value.posting),
  recurrence: toRecurrence(value.recurrence),
  attendanceCounts: toAttendanceCounts(value.attendance_counts),
  notes: {
    eventSource: optionalString(toRecord(value.notes).event_source) ?? 'secretary_scheduled',
    sessionTypeAuthority:
      optionalString(toRecord(value.notes).session_type_authority) ?? 'display_only',
  },
})

const headersFor = (
  adminId: string,
  adminProgrammes: string[],
  adminLevel: AdminDemoLevel = 'master',
) => buildAdminDemoHeaders(adminId, adminProgrammes, adminLevel)

export const listAdminSecretaryEvents = async (
  params: ListAdminSecretaryEventsParams,
): Promise<AdminSecretaryEventListResponse> => {
  const queryParams: Record<string, string | number | boolean> = {}
  addStringParam(queryParams, 'reporting_period_id', params.reportingPeriodId)
  addStringParam(queryParams, 'posting_code', params.postingCode)
  addStringParam(queryParams, 'date_from', params.dateFrom)
  addStringParam(queryParams, 'date_to', params.dateTo)
  addStringParam(queryParams, 'teaching_name', params.teachingName)
  addStringParam(queryParams, 'search', params.search)
  addStringParam(queryParams, 'session_type_id', params.sessionTypeId)
  addStringParam(queryParams, 'series_id', params.seriesId)
  if (typeof params.hasAttendance === 'boolean') {
    queryParams.has_attendance = params.hasAttendance
  }
  if (params.limit) {
    queryParams.limit = params.limit
  }
  if (params.offset) {
    queryParams.offset = params.offset
  }

  try {
    const response = await httpClient.get('/admin/secretary-events', {
      headers: headersFor(params.adminId, params.adminProgrammes, params.adminLevel),
      params: queryParams,
    })
    const payload = toRecord(response.data)
    return {
      items: toRecordArray(payload.items).map(toListItem),
      total: finiteNumber(payload.total),
      limit: finiteNumber(payload.limit, params.limit ?? 50),
      offset: finiteNumber(payload.offset, params.offset ?? 0),
      summary: toSummary(payload.summary),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const getAdminSecretaryEvent = async ({
  adminId,
  adminProgrammes,
  adminLevel = 'master',
  eventId,
}: GetAdminSecretaryEventParams): Promise<AdminSecretaryEventDetail> => {
  try {
    const response = await httpClient.get(`/admin/secretary-events/${encodeURIComponent(eventId)}`, {
      headers: headersFor(adminId, adminProgrammes, adminLevel),
    })
    return toDetail(toRecord(response.data))
  } catch (error) {
    throw toApiRequestError(error)
  }
}
