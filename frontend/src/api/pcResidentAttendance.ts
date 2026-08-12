import { buildAdminDemoHeaders } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export type PcResidentAttendanceSourceFilter =
  | 'department_secretary'
  | 'programme_pc'
  | 'adhoc'

export type PcResidentAttendanceStatus = 'submitted' | 'flagged' | 'removed'

export interface PcResidentAttendanceRequestContext {
  adminId: string
  programmeScope: string[]
}

export interface PcResidentAttendanceSummary {
  residentId: string
  name: string
  mcr: string
  programmeCode: string
  rYear?: string | null
  currentPostingCode?: string | null
  currentPostingLabel?: string | null
}

export interface PcResidentAttendanceOverviewItem extends PcResidentAttendanceSummary {
  attendanceCount: number
}

export interface PcResidentAttendanceOverviewResponse {
  items: PcResidentAttendanceOverviewItem[]
  total: number
  limit: number
  offset: number
}

export interface PcResidentAttendanceHistoryItem {
  attendanceId: string
  teachingEventId: string
  teachingName: string
  detailsOfSession?: string | null
  eventDate: string
  startTime: string
  endTime?: string | null
  postingCode: string
  postingLabel?: string | null
  source: string
  status: string
  submittedDuringLoa: boolean
  loaType?: string | null
  submittedAt: string
}

export interface PcResidentAttendanceDetailResponse {
  resident: PcResidentAttendanceSummary
  items: PcResidentAttendanceHistoryItem[]
  total: number
  limit: number
  offset: number
}

export interface PcResidentAttendanceOverviewFilters {
  programmeCode?: string
  search?: string
  postingCode?: string
  limit?: number
  offset?: number
}

export interface PcResidentAttendanceHistoryFilters {
  reportingPeriodId?: string
  postingCode?: string
  dateFrom?: string
  dateTo?: string
  source?: PcResidentAttendanceSourceFilter
  status?: PcResidentAttendanceStatus
  limit?: number
  offset?: number
}

const toRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}

const toRecordArray = (value: unknown): Record<string, unknown>[] =>
  Array.isArray(value) ? value.map(toRecord) : []

const optionalString = (value: unknown): string | null =>
  typeof value === 'string' && value.trim().length > 0 ? value : null

const finiteNumber = (value: unknown, fallback = 0): number => {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export const toPcResidentAttendanceSummary = (
  value: Record<string, unknown>,
): PcResidentAttendanceSummary => ({
  residentId: String(value.resident_id ?? ''),
  name: String(value.name ?? ''),
  mcr: String(value.mcr ?? ''),
  programmeCode: String(value.programme_code ?? ''),
  rYear: optionalString(value.r_year),
  currentPostingCode: optionalString(value.current_posting_code),
  currentPostingLabel: optionalString(value.current_posting_label),
})

export const toPcResidentAttendanceOverviewItem = (
  value: Record<string, unknown>,
): PcResidentAttendanceOverviewItem => ({
  ...toPcResidentAttendanceSummary(value),
  attendanceCount: finiteNumber(value.attendance_count),
})

export const toPcResidentAttendanceHistoryItem = (
  value: Record<string, unknown>,
): PcResidentAttendanceHistoryItem => ({
  attendanceId: String(value.attendance_id ?? ''),
  teachingEventId: String(value.teaching_event_id ?? ''),
  teachingName: String(value.teaching_name ?? ''),
  detailsOfSession: optionalString(value.details_of_session),
  eventDate: String(value.event_date ?? ''),
  startTime: String(value.start_time ?? ''),
  endTime: optionalString(value.end_time),
  postingCode: String(value.posting_code ?? ''),
  postingLabel: optionalString(value.posting_label),
  source: String(value.source ?? ''),
  status: String(value.status ?? ''),
  submittedDuringLoa: Boolean(value.submitted_during_loa),
  loaType: optionalString(value.loa_type),
  submittedAt: String(value.submitted_at ?? ''),
})

export const buildPcResidentAttendanceOverviewParams = (
  filters: PcResidentAttendanceOverviewFilters,
) => ({
  programme_code: filters.programmeCode?.trim() || undefined,
  search: filters.search?.trim() || undefined,
  posting_code: filters.postingCode?.trim() || undefined,
  limit: filters.limit,
  offset: filters.offset,
})

export const buildPcResidentAttendanceHistoryParams = (
  filters: PcResidentAttendanceHistoryFilters,
) => ({
  reporting_period_id: filters.reportingPeriodId?.trim() || undefined,
  posting_code: filters.postingCode?.trim() || undefined,
  date_from: filters.dateFrom || undefined,
  date_to: filters.dateTo || undefined,
  source: filters.source || undefined,
  status: filters.status || undefined,
  limit: filters.limit,
  offset: filters.offset,
})

const headersFor = ({ adminId, programmeScope }: PcResidentAttendanceRequestContext) =>
  buildAdminDemoHeaders(adminId, programmeScope, 'programme')

export const listPcResidentAttendance = async (
  context: PcResidentAttendanceRequestContext,
  filters: PcResidentAttendanceOverviewFilters,
): Promise<PcResidentAttendanceOverviewResponse> => {
  try {
    const response = await httpClient.get('/admin/resident-attendance', {
      headers: headersFor(context),
      params: buildPcResidentAttendanceOverviewParams(filters),
    })
    const payload = toRecord(response.data)
    return {
      items: toRecordArray(payload.items).map(toPcResidentAttendanceOverviewItem),
      total: finiteNumber(payload.total),
      limit: finiteNumber(payload.limit, filters.limit ?? 50),
      offset: finiteNumber(payload.offset, filters.offset ?? 0),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const getPcResidentAttendance = async (
  context: PcResidentAttendanceRequestContext,
  residentId: string,
  filters: PcResidentAttendanceHistoryFilters,
): Promise<PcResidentAttendanceDetailResponse> => {
  try {
    const response = await httpClient.get(
      `/admin/resident-attendance/${encodeURIComponent(residentId)}`,
      {
        headers: headersFor(context),
        params: buildPcResidentAttendanceHistoryParams(filters),
      },
    )
    const payload = toRecord(response.data)
    return {
      resident: toPcResidentAttendanceSummary(toRecord(payload.resident)),
      items: toRecordArray(payload.items).map(toPcResidentAttendanceHistoryItem),
      total: finiteNumber(payload.total),
      limit: finiteNumber(payload.limit, filters.limit ?? 50),
      offset: finiteNumber(payload.offset, filters.offset ?? 0),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}
