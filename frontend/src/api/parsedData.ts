import type {
  AyDateCategory,
  ParsedAcademicMonthBoundaryRow,
  ParsedDataCorrectionHistoryListResponse,
  ParsedDataCorrectionHistoryRow,
  ParsedDataCorrectionRequest,
  ParsedDataCorrectionResponse,
  ParsedDataRow,
  ParsedDataListResponse,
  ParsedFormF1RecordRow,
  ParsedPublicHolidayRow,
  ParsedResidentPostingRow,
  ParsedResidentRow,
  ParsedDataSourceCellReplaceResponse,
  ParsedTeachingTargetRow,
  ResidentPostingSourceCellReplaceRequest,
} from '../types/parsedData'
import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { toDataRevalidationImpact } from './dataRevalidation'
import { httpClient, toApiRequestError } from './http'

interface AdminParsedDataParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  limit?: number
  offset?: number
}

export interface ListParsedResidentsParams extends AdminParsedDataParams {
  programmeCode?: string
  mcr?: string
  search?: string
  status?: string
}

export interface ListParsedResidentPostingsParams extends AdminParsedDataParams {
  reportingPeriodId?: string
  programmeCode?: string
  postingCode?: string
  mcr?: string
  status?: string
  monthLabel?: string
  search?: string
}

export interface ListParsedTeachingTargetsParams extends AdminParsedDataParams {
  reportingPeriodId?: string
  programmeCode?: string
  postingCode?: string
  rYear?: string
  sessionType?: string
  isTracked?: boolean | 'all'
  search?: string
}

export interface ListParsedFormF1RecordsParams extends AdminParsedDataParams {
  reportingPeriodId?: string
  programmeCode?: string
  mcr?: string
  monthLabel?: string
  isActive?: boolean | 'all'
  search?: string
}

export interface ListParsedPublicHolidaysParams extends AdminParsedDataParams {
  year?: string
  search?: string
}

export interface ListParsedAcademicMonthBoundariesParams extends AdminParsedDataParams {
  academicYearLabel?: string
  ayDateCategory?: AyDateCategory | 'all'
  monthLabel?: string
  search?: string
}

export interface ListParsedDataCorrectionsParams extends AdminParsedDataParams {
  entityType?: string
  entityId?: string
  uploadLogId?: string
  sheetName?: string
  rowNumber?: number | null
  cellRef?: string
}

type ApiRow = Record<string, unknown>

const headersFor = (
  adminId: string,
  adminProgrammes: string[],
  adminLevel: AdminDemoLevel = 'master',
) => buildAdminDemoHeaders(adminId, adminProgrammes, adminLevel)

const optionalString = (value: unknown): string | null => {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || null
}

const requiredString = (value: unknown): string => {
  return typeof value === 'string' ? value : String(value ?? '')
}

const finiteNumber = (value: unknown, fallback = 0): number => {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

const optionalNumber = (value: unknown): number | null => {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

const booleanValue = (value: unknown): boolean => {
  return value === true
}

const addTextParam = (
  params: Record<string, string | number | boolean>,
  key: string,
  value?: string,
) => {
  const trimmed = value?.trim()
  if (trimmed && trimmed !== 'all') {
    params[key] = trimmed
  }
}

const addPaginationParams = (
  queryParams: Record<string, string | number | boolean>,
  params: AdminParsedDataParams,
) => {
  if (params.limit) {
    queryParams.limit = params.limit
  }
  if (params.offset) {
    queryParams.offset = params.offset
  }
}

const listParsedData = async <T>(
  path: string,
  params: AdminParsedDataParams,
  queryParams: Record<string, string | number | boolean>,
  mapRow: (row: ApiRow) => T,
): Promise<ParsedDataListResponse<T>> => {
  addPaginationParams(queryParams, params)
  try {
    const response = await httpClient.get(path, {
      headers: headersFor(params.adminId, params.adminProgrammes, params.adminLevel),
      params: queryParams,
    })
    const payload = response.data as Record<string, unknown>
    const rows = Array.isArray(payload.items) ? payload.items : []
    return {
      items: rows
        .filter((row): row is ApiRow => typeof row === 'object' && row !== null)
        .map(mapRow),
      total: finiteNumber(payload.total),
      limit: finiteNumber(payload.limit, params.limit ?? 50),
      offset: finiteNumber(payload.offset, params.offset ?? 0),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

const correctParsedDataRow = async <T extends ParsedDataRow>(
  path: string,
  params: AdminParsedDataParams,
  request: ParsedDataCorrectionRequest,
  mapRow: (row: ApiRow) => T,
): Promise<ParsedDataCorrectionResponse<T>> => {
  try {
    const response = await httpClient.patch(path, request, {
      headers: headersFor(params.adminId, params.adminProgrammes, params.adminLevel),
    })
    const payload = response.data as Record<string, unknown>
    const item = typeof payload.item === 'object' && payload.item !== null
      ? mapRow(payload.item as ApiRow)
      : mapRow({})
    return {
      item,
      audit_log_id: requiredString(payload.audit_log_id),
      entity_type: requiredString(payload.entity_type),
      entity_id: optionalString(payload.entity_id),
      updated_fields: Array.isArray(payload.updated_fields)
        ? payload.updated_fields.map(requiredString)
        : [],
      dataRevalidation: toDataRevalidationImpact(payload.data_revalidation),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

const toSourceCellReplaceResponse = (
  payload: Record<string, unknown>,
): ParsedDataSourceCellReplaceResponse => ({
  before_rows: Array.isArray(payload.before_rows)
    ? payload.before_rows
      .filter((row): row is ApiRow => typeof row === 'object' && row !== null)
      .map(toParsedResidentPosting)
    : [],
  after_rows: Array.isArray(payload.after_rows)
    ? payload.after_rows
      .filter((row): row is ApiRow => typeof row === 'object' && row !== null)
      .map(toParsedResidentPosting)
    : [],
  audit_log_id: requiredString(payload.audit_log_id),
  entity_type: requiredString(payload.entity_type),
  entity_id: optionalString(payload.entity_id),
  updated_fields: Array.isArray(payload.updated_fields)
    ? payload.updated_fields.map(requiredString)
    : [],
  dataRevalidation: toDataRevalidationImpact(payload.data_revalidation),
})

const toParsedResident = (value: ApiRow): ParsedResidentRow => ({
  id: requiredString(value.id),
  employee_code: optionalString(value.employee_code),
  name: requiredString(value.name),
  mcr: requiredString(value.mcr),
  programme_code: optionalString(value.programme_code),
  r_year: optionalString(value.r_year),
  classification: optionalString(value.classification),
  reg_type: optionalString(value.reg_type),
  base_institution: optionalString(value.base_institution),
  email: optionalString(value.email),
  phone: optionalString(value.phone),
  employer_tag: optionalString(value.employer_tag),
  status: optionalString(value.status),
  updated_at: optionalString(value.updated_at),
})

const toParsedResidentPosting = (value: ApiRow): ParsedResidentPostingRow => ({
  id: requiredString(value.id),
  resident_id: requiredString(value.resident_id),
  resident_name: optionalString(value.resident_name),
  mcr: optionalString(value.mcr),
  programme_code: optionalString(value.programme_code),
  posting_code: optionalString(value.posting_code),
  reporting_period_id: requiredString(value.reporting_period_id),
  reporting_period_label: optionalString(value.reporting_period_label),
  start_date: requiredString(value.start_date),
  end_date: requiredString(value.end_date),
  day_part: optionalString(value.day_part),
  month_label: optionalString(value.month_label),
  r_year: requiredString(value.r_year),
  status: requiredString(value.status),
  loa_type: optionalString(value.loa_type),
  loa_start_date: optionalString(value.loa_start_date),
  loa_end_date: optionalString(value.loa_end_date),
  refresher_training_type: optionalString(value.refresher_training_type),
  refresher_training_start: optionalString(value.refresher_training_start),
  refresher_training_end: optionalString(value.refresher_training_end),
  active_months_weight: optionalNumber(value.active_months_weight),
  working_days_in_month: optionalNumber(value.working_days_in_month),
  updated_at: optionalString(value.updated_at),
})

const toParsedTeachingTarget = (value: ApiRow): ParsedTeachingTargetRow => ({
  id: requiredString(value.id),
  reporting_period_id: requiredString(value.reporting_period_id),
  reporting_period_label: optionalString(value.reporting_period_label),
  programme_code: requiredString(value.programme_code),
  r_year: requiredString(value.r_year),
  posting_code: requiredString(value.posting_code),
  session_type_id: requiredString(value.session_type_id),
  session_type_name: optionalString(value.session_type_name),
  duration_hours: optionalNumber(value.duration_hours),
  monthly_target: finiteNumber(value.monthly_target),
  is_tracked: booleanValue(value.is_tracked),
  is_reallocatable: booleanValue(value.is_reallocatable),
  tag: optionalString(value.tag),
  updated_at: optionalString(value.updated_at),
})

const toParsedFormF1Record = (value: ApiRow): ParsedFormF1RecordRow => ({
  id: requiredString(value.id),
  reporting_period_id: requiredString(value.reporting_period_id),
  reporting_period_label: optionalString(value.reporting_period_label),
  mcr: requiredString(value.mcr),
  resident_name: optionalString(value.resident_name),
  programme_code: optionalString(value.programme_code),
  month_label: requiredString(value.month_label),
  status_raw: requiredString(value.status_raw),
  is_active: booleanValue(value.is_active),
  promotion_date: optionalString(value.promotion_date),
  upload_id: optionalString(value.upload_id),
  updated_at: optionalString(value.updated_at),
})

const toParsedPublicHoliday = (value: ApiRow): ParsedPublicHolidayRow => ({
  id: requiredString(value.id),
  holiday_date: requiredString(value.holiday_date),
  name: optionalString(value.name),
  day_of_week: optionalString(value.day_of_week),
  year: optionalNumber(value.year),
})

const toAyDateCategory = (value: unknown): AyDateCategory => {
  return value === 'im_subspec' ? 'im_subspec' : 'non_im_subspec'
}

const toParsedAcademicMonthBoundary = (
  value: ApiRow,
): ParsedAcademicMonthBoundaryRow => ({
  id: requiredString(value.id),
  academic_year_label: requiredString(value.academic_year_label),
  ay_date_category: toAyDateCategory(value.ay_date_category),
  month_label: requiredString(value.month_label),
  start_date: requiredString(value.start_date),
  end_date: requiredString(value.end_date),
  upload_id: optionalString(value.upload_id),
  updated_at: optionalString(value.updated_at),
})

const toParsedCorrectionHistoryRow = (value: ApiRow): ParsedDataCorrectionHistoryRow => ({
  id: requiredString(value.id),
  created_at: requiredString(value.created_at),
  actor_user_id: optionalString(value.actor_user_id),
  actor_role: requiredString(value.actor_role),
  actor_name: requiredString(value.actor_name),
  action: requiredString(value.action),
  entity_type: requiredString(value.entity_type),
  entity_id: optionalString(value.entity_id),
  correction_reason: optionalString(value.correction_reason),
  before_json: value.before_json,
  after_json: value.after_json,
  metadata_json: value.metadata_json,
})

export const listParsedResidents = (
  params: ListParsedResidentsParams,
): Promise<ParsedDataListResponse<ParsedResidentRow>> => {
  const queryParams: Record<string, string | number | boolean> = {}
  addTextParam(queryParams, 'programme_code', params.programmeCode)
  addTextParam(queryParams, 'mcr', params.mcr)
  addTextParam(queryParams, 'search', params.search)
  addTextParam(queryParams, 'status', params.status)
  return listParsedData('/admin/parsed-data/residents', params, queryParams, toParsedResident)
}

export const listParsedResidentPostings = (
  params: ListParsedResidentPostingsParams,
): Promise<ParsedDataListResponse<ParsedResidentPostingRow>> => {
  const queryParams: Record<string, string | number | boolean> = {}
  addTextParam(queryParams, 'reporting_period_id', params.reportingPeriodId)
  addTextParam(queryParams, 'programme_code', params.programmeCode)
  addTextParam(queryParams, 'posting_code', params.postingCode)
  addTextParam(queryParams, 'mcr', params.mcr)
  addTextParam(queryParams, 'status', params.status)
  addTextParam(queryParams, 'month_label', params.monthLabel)
  addTextParam(queryParams, 'search', params.search)
  return listParsedData(
    '/admin/parsed-data/resident-postings',
    params,
    queryParams,
    toParsedResidentPosting,
  )
}

export const listParsedTeachingTargets = (
  params: ListParsedTeachingTargetsParams,
): Promise<ParsedDataListResponse<ParsedTeachingTargetRow>> => {
  const queryParams: Record<string, string | number | boolean> = {}
  addTextParam(queryParams, 'reporting_period_id', params.reportingPeriodId)
  addTextParam(queryParams, 'programme_code', params.programmeCode)
  addTextParam(queryParams, 'posting_code', params.postingCode)
  addTextParam(queryParams, 'r_year', params.rYear)
  addTextParam(queryParams, 'session_type', params.sessionType)
  addTextParam(queryParams, 'search', params.search)
  if (params.isTracked !== undefined && params.isTracked !== 'all') {
    queryParams.is_tracked = params.isTracked
  }
  return listParsedData(
    '/admin/parsed-data/teaching-targets',
    params,
    queryParams,
    toParsedTeachingTarget,
  )
}

export const listParsedFormF1Records = (
  params: ListParsedFormF1RecordsParams,
): Promise<ParsedDataListResponse<ParsedFormF1RecordRow>> => {
  const queryParams: Record<string, string | number | boolean> = {}
  addTextParam(queryParams, 'reporting_period_id', params.reportingPeriodId)
  addTextParam(queryParams, 'programme_code', params.programmeCode)
  addTextParam(queryParams, 'mcr', params.mcr)
  addTextParam(queryParams, 'month_label', params.monthLabel)
  addTextParam(queryParams, 'search', params.search)
  if (params.isActive !== undefined && params.isActive !== 'all') {
    queryParams.is_active = params.isActive
  }
  return listParsedData(
    '/admin/parsed-data/form-f1-records',
    params,
    queryParams,
    toParsedFormF1Record,
  )
}

export const listParsedPublicHolidays = (
  params: ListParsedPublicHolidaysParams,
): Promise<ParsedDataListResponse<ParsedPublicHolidayRow>> => {
  const queryParams: Record<string, string | number | boolean> = {}
  addTextParam(queryParams, 'search', params.search)
  const year = params.year?.trim()
  if (year && /^\d{4}$/.test(year)) {
    queryParams.year = year
  } else if (year && !queryParams.search) {
    queryParams.search = year
  }
  return listParsedData(
    '/admin/parsed-data/public-holidays',
    params,
    queryParams,
    toParsedPublicHoliday,
  )
}

export const listParsedAcademicMonthBoundaries = (
  params: ListParsedAcademicMonthBoundariesParams,
): Promise<ParsedDataListResponse<ParsedAcademicMonthBoundaryRow>> => {
  const queryParams: Record<string, string | number | boolean> = {}
  addTextParam(queryParams, 'academic_year_label', params.academicYearLabel)
  addTextParam(queryParams, 'month_label', params.monthLabel)
  addTextParam(queryParams, 'search', params.search)
  if (params.ayDateCategory && params.ayDateCategory !== 'all') {
    queryParams.ay_date_category = params.ayDateCategory
  }
  return listParsedData(
    '/admin/parsed-data/academic-month-boundaries',
    params,
    queryParams,
    toParsedAcademicMonthBoundary,
  )
}

export const updateParsedResident = (
  params: AdminParsedDataParams,
  residentId: string,
  request: ParsedDataCorrectionRequest,
): Promise<ParsedDataCorrectionResponse<ParsedResidentRow>> =>
  correctParsedDataRow(
    `/admin/parsed-data/residents/${encodeURIComponent(residentId)}`,
    params,
    request,
    toParsedResident,
  )

export const updateParsedResidentPosting = (
  params: AdminParsedDataParams,
  residentPostingId: string,
  request: ParsedDataCorrectionRequest,
): Promise<ParsedDataCorrectionResponse<ParsedResidentPostingRow>> =>
  correctParsedDataRow(
    `/admin/parsed-data/resident-postings/${encodeURIComponent(residentPostingId)}`,
    params,
    request,
    toParsedResidentPosting,
  )

export const updateParsedTeachingTarget = (
  params: AdminParsedDataParams,
  teachingTargetId: string,
  request: ParsedDataCorrectionRequest,
): Promise<ParsedDataCorrectionResponse<ParsedTeachingTargetRow>> =>
  correctParsedDataRow(
    `/admin/parsed-data/teaching-targets/${encodeURIComponent(teachingTargetId)}`,
    params,
    request,
    toParsedTeachingTarget,
  )

export const updateParsedFormF1Record = (
  params: AdminParsedDataParams,
  formF1RecordId: string,
  request: ParsedDataCorrectionRequest,
): Promise<ParsedDataCorrectionResponse<ParsedFormF1RecordRow>> =>
  correctParsedDataRow(
    `/admin/parsed-data/form-f1-records/${encodeURIComponent(formF1RecordId)}`,
    params,
    request,
    toParsedFormF1Record,
  )

export const updateParsedAcademicMonthBoundary = (
  params: AdminParsedDataParams,
  academicMonthBoundaryId: string,
  request: ParsedDataCorrectionRequest,
): Promise<ParsedDataCorrectionResponse<ParsedAcademicMonthBoundaryRow>> =>
  correctParsedDataRow(
    `/admin/parsed-data/academic-month-boundaries/${encodeURIComponent(academicMonthBoundaryId)}`,
    params,
    request,
    toParsedAcademicMonthBoundary,
  )

export const replaceParsedResidentPostingSourceCell = async (
  params: AdminParsedDataParams,
  request: ResidentPostingSourceCellReplaceRequest,
): Promise<ParsedDataSourceCellReplaceResponse> => {
  try {
    const response = await httpClient.post(
      '/admin/parsed-data/resident-postings/source-cell-replace',
      request,
      { headers: headersFor(params.adminId, params.adminProgrammes, params.adminLevel) },
    )
    return toSourceCellReplaceResponse(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const listParsedDataCorrections = (
  params: ListParsedDataCorrectionsParams,
): Promise<ParsedDataCorrectionHistoryListResponse> => {
  const queryParams: Record<string, string | number | boolean> = {}
  addTextParam(queryParams, 'entity_type', params.entityType)
  addTextParam(queryParams, 'entity_id', params.entityId)
  addTextParam(queryParams, 'upload_log_id', params.uploadLogId)
  addTextParam(queryParams, 'sheet_name', params.sheetName)
  addTextParam(queryParams, 'cell_ref', params.cellRef)
  if (params.rowNumber) {
    queryParams.row_number = params.rowNumber
  }
  return listParsedData(
    '/admin/parsed-data/corrections',
    params,
    queryParams,
    toParsedCorrectionHistoryRow,
  )
}
