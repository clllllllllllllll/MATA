export interface ParsedDataListResponse<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ParsedResidentRow {
  id: string
  employee_code: string | null
  name: string
  mcr: string
  programme_code: string | null
  r_year: string | null
  classification: string | null
  reg_type: string | null
  base_institution: string | null
  employer_tag: string | null
  status: string | null
}

export interface ParsedResidentPostingRow {
  id: string
  resident_id: string
  resident_name: string | null
  mcr: string | null
  programme_code: string | null
  posting_code: string | null
  reporting_period_id: string
  reporting_period_label: string | null
  start_date: string
  end_date: string
  month_label: string | null
  r_year: string
  status: string
  loa_type: string | null
  loa_start_date: string | null
  loa_end_date: string | null
  refresher_training_type: string | null
  active_months_weight: number | null
  working_days_in_month: number | null
}

export interface ParsedTeachingTargetRow {
  id: string
  reporting_period_id: string
  reporting_period_label: string | null
  programme_code: string
  r_year: string
  posting_code: string
  session_type_id: string
  session_type_name: string | null
  duration_hours: number | null
  monthly_target: number
  is_tracked: boolean
  is_reallocatable: boolean
  tag: string | null
  details_of_training: string | null
}

export interface ParsedTeachingNameCatalogueRow {
  id: string
  keyword: string
  programme_code: string
  posting_code: string
  r_year: string
  reporting_period_id: string
  reporting_period_label: string | null
  session_type_id: string
  session_type_name: string | null
  duration_hours: number
  is_tracked: boolean
}

export interface ParsedFormF1RecordRow {
  id: string
  reporting_period_id: string
  reporting_period_label: string | null
  mcr: string
  resident_name: string | null
  programme_code: string | null
  month_label: string
  status_raw: string
  is_active: boolean
  promotion_date: string | null
  upload_id: string | null
}

export interface ParsedPublicHolidayRow {
  id: string
  holiday_date: string
  name: string | null
  day_of_week: string | null
  year: number | null
}

export type AyDateCategory = 'im_subspec' | 'non_im_subspec'

export interface ParsedAcademicMonthBoundaryRow {
  id: string
  academic_year_label: string
  ay_date_category: AyDateCategory
  month_label: string
  start_date: string
  end_date: string
  upload_id: string | null
}

export type ParsedDataRow =
  | ParsedResidentRow
  | ParsedResidentPostingRow
  | ParsedTeachingTargetRow
  | ParsedTeachingNameCatalogueRow
  | ParsedFormF1RecordRow
  | ParsedPublicHolidayRow
  | ParsedAcademicMonthBoundaryRow
