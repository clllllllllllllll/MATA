import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export type AdminResidentSubmissionSource = 'secretary_event' | 'adhoc'
export type AdminResidentSubmissionStatus = 'submitted' | 'flagged' | 'removed'

export interface AdminResidentSubmissionListItem {
  id: string
  residentId: string
  residentName: string
  mcr: string
  programmeCode?: string | null
  attendancePostingCode?: string | null
  postingCode: string
  postingDisplayName?: string | null
  teachingEventId: string
  teachingName: string
  eventDate: string
  startTime: string
  endTime?: string | null
  durationHours?: number | null
  source: string
  isAdhoc: boolean
  status: string
  submittedDuringLoa: boolean
  loaType?: string | null
  submittedAt: string
  sessionTypeId?: string | null
  sessionTypeName?: string | null
  cmePointsAwarded: boolean
  smcEventCode?: string | null
  createdByRole?: string | null
}

export interface AdminResidentSubmissionListSummary {
  totalSubmissions: number
  submittedCount: number
  flaggedCount: number
  removedCount: number
  secretaryEventCount: number
  adhocCount: number
}

export interface AdminResidentSubmissionListResponse {
  items: AdminResidentSubmissionListItem[]
  total: number
  limit: number
  offset: number
  summary: AdminResidentSubmissionListSummary
}

export interface AdminResidentSubmissionAttendanceMetadata {
  id: string
  residentId: string
  teachingEventId: string
  status: string
  submittedDuringLoa: boolean
  loaType?: string | null
  attendancePostingCode?: string | null
  submittedAt: string
  createdAt?: string | null
  updatedAt?: string | null
}

export interface AdminResidentSubmissionResidentMetadata {
  id: string
  name: string
  mcr: string
  programmeCode?: string | null
  rYear?: string | null
  classification?: string | null
  status?: string | null
  identityLabel: string
}

export interface AdminResidentSubmissionEventMetadata {
  id: string
  teachingName: string
  eventDate: string
  startTime: string
  endTime?: string | null
  durationHours?: number | null
  sessionTypeId?: string | null
  sessionTypeName?: string | null
  cmePointsAwarded: boolean
  smcEventCode?: string | null
  isAdhoc: boolean
  source: string
  createdByRole?: string | null
  createdAt?: string | null
  updatedAt?: string | null
}

export interface AdminResidentSubmissionPostingMetadata {
  code: string
  displayName?: string | null
  institution?: string | null
  department?: string | null
}

export interface AdminResidentSubmissionDetail extends AdminResidentSubmissionListItem {
  attendanceRecord: AdminResidentSubmissionAttendanceMetadata
  resident: AdminResidentSubmissionResidentMetadata
  event: AdminResidentSubmissionEventMetadata
  posting: AdminResidentSubmissionPostingMetadata
  notes: {
    identityScope: string
    sessionTypeAuthority: string
    complianceIncluded?: boolean | null
  }
}

export interface ListAdminResidentSubmissionsParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  reportingPeriodId?: string
  programmeCode?: string
  postingCode?: string
  residentId?: string
  mcr?: string
  dateFrom?: string
  dateTo?: string
  source?: AdminResidentSubmissionSource
  isAdhoc?: boolean | null
  status?: AdminResidentSubmissionStatus
  search?: string
  teachingEventId?: string
  teachingName?: string
  sessionTypeId?: string
  submittedFrom?: string
  submittedTo?: string
  limit?: number
  offset?: number
}

export interface GetAdminResidentSubmissionParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  submissionId: string
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

const toListItem = (value: Record<string, unknown>): AdminResidentSubmissionListItem => ({
  id: String(value.id ?? ''),
  residentId: String(value.resident_id ?? ''),
  residentName: String(value.resident_name ?? ''),
  mcr: String(value.mcr ?? ''),
  programmeCode: optionalString(value.programme_code),
  attendancePostingCode: optionalString(value.attendance_posting_code),
  postingCode: String(value.posting_code ?? ''),
  postingDisplayName: optionalString(value.posting_display_name),
  teachingEventId: String(value.teaching_event_id ?? ''),
  teachingName: String(value.teaching_name ?? ''),
  eventDate: String(value.event_date ?? ''),
  startTime: String(value.start_time ?? ''),
  endTime: optionalString(value.end_time),
  durationHours: optionalNumber(value.duration_hours),
  source: String(value.source ?? ''),
  isAdhoc: toBoolean(value.is_adhoc),
  status: String(value.status ?? ''),
  submittedDuringLoa: toBoolean(value.submitted_during_loa),
  loaType: optionalString(value.loa_type),
  submittedAt: String(value.submitted_at ?? ''),
  sessionTypeId: optionalString(value.session_type_id),
  sessionTypeName: optionalString(value.session_type_name),
  cmePointsAwarded: toBoolean(value.cme_points_awarded),
  smcEventCode: optionalString(value.smc_event_code),
  createdByRole: optionalString(value.created_by_role),
})

const toSummary = (value: unknown): AdminResidentSubmissionListSummary => {
  const record = toRecord(value)
  return {
    totalSubmissions: finiteNumber(record.total_submissions),
    submittedCount: finiteNumber(record.submitted_count),
    flaggedCount: finiteNumber(record.flagged_count),
    removedCount: finiteNumber(record.removed_count),
    secretaryEventCount: finiteNumber(record.secretary_event_count),
    adhocCount: finiteNumber(record.adhoc_count),
  }
}

const toAttendanceRecord = (value: unknown): AdminResidentSubmissionAttendanceMetadata => {
  const record = toRecord(value)
  return {
    id: String(record.id ?? ''),
    residentId: String(record.resident_id ?? ''),
    teachingEventId: String(record.teaching_event_id ?? ''),
    status: String(record.status ?? ''),
    submittedDuringLoa: toBoolean(record.submitted_during_loa),
    loaType: optionalString(record.loa_type),
    attendancePostingCode: optionalString(record.attendance_posting_code),
    submittedAt: String(record.submitted_at ?? ''),
    createdAt: optionalString(record.created_at),
    updatedAt: optionalString(record.updated_at),
  }
}

const toResident = (value: unknown): AdminResidentSubmissionResidentMetadata => {
  const record = toRecord(value)
  return {
    id: String(record.id ?? ''),
    name: String(record.name ?? ''),
    mcr: String(record.mcr ?? ''),
    programmeCode: optionalString(record.programme_code),
    rYear: optionalString(record.r_year),
    classification: optionalString(record.classification),
    status: optionalString(record.status),
    identityLabel: optionalString(record.identity_label) ?? 'NHG Resident',
  }
}

const toEvent = (value: unknown): AdminResidentSubmissionEventMetadata => {
  const record = toRecord(value)
  return {
    id: String(record.id ?? ''),
    teachingName: String(record.teaching_name ?? ''),
    eventDate: String(record.event_date ?? ''),
    startTime: String(record.start_time ?? ''),
    endTime: optionalString(record.end_time),
    durationHours: optionalNumber(record.duration_hours),
    sessionTypeId: optionalString(record.session_type_id),
    sessionTypeName: optionalString(record.session_type_name),
    cmePointsAwarded: toBoolean(record.cme_points_awarded),
    smcEventCode: optionalString(record.smc_event_code),
    isAdhoc: toBoolean(record.is_adhoc),
    source: String(record.source ?? ''),
    createdByRole: optionalString(record.created_by_role),
    createdAt: optionalString(record.created_at),
    updatedAt: optionalString(record.updated_at),
  }
}

const toPosting = (value: unknown): AdminResidentSubmissionPostingMetadata => {
  const record = toRecord(value)
  return {
    code: String(record.code ?? ''),
    displayName: optionalString(record.display_name),
    institution: optionalString(record.institution),
    department: optionalString(record.department),
  }
}

const toDetail = (value: Record<string, unknown>): AdminResidentSubmissionDetail => {
  const notes = toRecord(value.notes)
  return {
    ...toListItem(value),
    attendanceRecord: toAttendanceRecord(value.attendance_record),
    resident: toResident(value.resident),
    event: toEvent(value.event),
    posting: toPosting(value.posting),
    notes: {
      identityScope:
        optionalString(notes.identity_scope) ?? 'nhg_resident_attendance_records_only',
      sessionTypeAuthority: optionalString(notes.session_type_authority) ?? 'display_only',
      complianceIncluded:
        typeof notes.compliance_included === 'boolean' ? notes.compliance_included : null,
    },
  }
}

const headersFor = (
  adminId: string,
  adminProgrammes: string[],
  adminLevel: AdminDemoLevel = 'master',
) => buildAdminDemoHeaders(adminId, adminProgrammes, adminLevel)

export const listAdminResidentSubmissions = async (
  params: ListAdminResidentSubmissionsParams,
): Promise<AdminResidentSubmissionListResponse> => {
  const queryParams: Record<string, string | number | boolean> = {}
  addStringParam(queryParams, 'reporting_period_id', params.reportingPeriodId)
  addStringParam(queryParams, 'programme_code', params.programmeCode)
  addStringParam(queryParams, 'posting_code', params.postingCode)
  addStringParam(queryParams, 'resident_id', params.residentId)
  addStringParam(queryParams, 'mcr', params.mcr)
  addStringParam(queryParams, 'date_from', params.dateFrom)
  addStringParam(queryParams, 'date_to', params.dateTo)
  addStringParam(queryParams, 'source', params.source)
  addStringParam(queryParams, 'status', params.status)
  addStringParam(queryParams, 'search', params.search)
  addStringParam(queryParams, 'teaching_event_id', params.teachingEventId)
  addStringParam(queryParams, 'teaching_name', params.teachingName)
  addStringParam(queryParams, 'session_type_id', params.sessionTypeId)
  addStringParam(queryParams, 'submitted_from', params.submittedFrom)
  addStringParam(queryParams, 'submitted_to', params.submittedTo)
  if (typeof params.isAdhoc === 'boolean') {
    queryParams.is_adhoc = params.isAdhoc
  }
  if (typeof params.limit === 'number') {
    queryParams.limit = params.limit
  }
  if (typeof params.offset === 'number') {
    queryParams.offset = params.offset
  }

  try {
    const response = await httpClient.get('/admin/resident-submissions', {
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

export const getAdminResidentSubmission = async ({
  adminId,
  adminProgrammes,
  adminLevel = 'master',
  submissionId,
}: GetAdminResidentSubmissionParams): Promise<AdminResidentSubmissionDetail> => {
  try {
    const response = await httpClient.get(
      `/admin/resident-submissions/${encodeURIComponent(submissionId)}`,
      {
        headers: headersFor(adminId, adminProgrammes, adminLevel),
      },
    )
    return toDetail(toRecord(response.data))
  } catch (error) {
    throw toApiRequestError(error)
  }
}
