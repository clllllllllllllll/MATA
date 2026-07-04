import { buildAdminDemoHeaders } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface AdminExternalAttendanceFilters {
  programmeCode?: string
  homeCluster?: string
  postingCode?: string
  mcr?: string
  status?: string
  dateFrom?: string
  dateTo?: string
  limit?: number
  offset?: number
}

export interface AdminExternalAttendanceListItem {
  id: string
  externalResidentId: string
  residentName: string
  mcr: string
  homeCluster: string
  currentNhgPostingCode?: string | null
  attendancePostingCode?: string | null
  postingCode: string
  postingDisplayName?: string | null
  teachingEventId: string
  teachingName: string
  detailsOfSession?: string | null
  eventDate: string
  startTime: string
  endTime?: string | null
  durationHours?: number | null
  source: string
  isAdhoc: boolean
  status: string
  submittedAt: string
}

export interface AdminExternalAttendanceSummary {
  totalRecords: number
  submittedCount: number
  flaggedCount: number
  removedCount: number
  adhocCount: number
}

export interface AdminExternalAttendanceListResponse {
  items: AdminExternalAttendanceListItem[]
  total: number
  limit: number
  offset: number
  summary: AdminExternalAttendanceSummary
}

const toNumber = (value: unknown): number => {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

const toItem = (value: Record<string, unknown>): AdminExternalAttendanceListItem => ({
  id: String(value.id ?? ''),
  externalResidentId: String(value.external_resident_id ?? ''),
  residentName: String(value.resident_name ?? ''),
  mcr: String(value.mcr ?? ''),
  homeCluster: String(value.home_cluster ?? ''),
  currentNhgPostingCode: value.current_nhg_posting_code ? String(value.current_nhg_posting_code) : null,
  attendancePostingCode: value.attendance_posting_code ? String(value.attendance_posting_code) : null,
  postingCode: String(value.posting_code ?? ''),
  postingDisplayName: value.posting_display_name ? String(value.posting_display_name) : null,
  teachingEventId: String(value.teaching_event_id ?? ''),
  teachingName: String(value.teaching_name ?? ''),
  detailsOfSession: value.details_of_session ? String(value.details_of_session) : null,
  eventDate: String(value.event_date ?? ''),
  startTime: String(value.start_time ?? ''),
  endTime: value.end_time ? String(value.end_time) : null,
  durationHours: value.duration_hours === null || value.duration_hours === undefined ? null : toNumber(value.duration_hours),
  source: String(value.source ?? ''),
  isAdhoc: Boolean(value.is_adhoc),
  status: String(value.status ?? ''),
  submittedAt: String(value.submitted_at ?? ''),
})

const buildParams = (filters: AdminExternalAttendanceFilters) => ({
  programme_code: filters.programmeCode || undefined,
  home_cluster: filters.homeCluster || undefined,
  posting_code: filters.postingCode || undefined,
  mcr: filters.mcr || undefined,
  status: filters.status || undefined,
  date_from: filters.dateFrom || undefined,
  date_to: filters.dateTo || undefined,
  limit: filters.limit,
  offset: filters.offset,
})

export const listAdminExternalAttendance = async (
  filters: AdminExternalAttendanceFilters,
): Promise<AdminExternalAttendanceListResponse> => {
  try {
    const response = await httpClient.get('/admin/external-attendance', {
      headers: buildAdminDemoHeaders('', []),
      params: buildParams(filters),
    })
    const payload = typeof response.data === 'object' && response.data !== null
      ? (response.data as Record<string, unknown>)
      : {}
    const rows = Array.isArray(payload.items) ? payload.items : []
    const summary = typeof payload.summary === 'object' && payload.summary !== null
      ? (payload.summary as Record<string, unknown>)
      : {}
    return {
      items: rows
        .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
        .map(toItem),
      total: toNumber(payload.total),
      limit: toNumber(payload.limit),
      offset: toNumber(payload.offset),
      summary: {
        totalRecords: toNumber(summary.total_records),
        submittedCount: toNumber(summary.submitted_count),
        flaggedCount: toNumber(summary.flagged_count),
        removedCount: toNumber(summary.removed_count),
        adhocCount: toNumber(summary.adhoc_count),
      },
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const downloadAdminExternalAttendanceXlsx = async (
  filters: AdminExternalAttendanceFilters,
): Promise<Blob> => {
  try {
    const response = await httpClient.get('/admin/external-attendance/export.xlsx', {
      headers: buildAdminDemoHeaders('', []),
      params: buildParams(filters),
      responseType: 'blob',
      skipMemoryCacheClear: true,
    })
    return response.data instanceof Blob
      ? response.data
      : new Blob([response.data], {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
  } catch (error) {
    throw toApiRequestError(error)
  }
}
