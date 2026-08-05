import type { DataRevalidationImpact } from './dataRevalidation'

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
  email: string | null
  phone: string | null
  employer_tag: string | null
  status: string | null
  updated_at: string | null
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
  day_part: string | null
  month_label: string | null
  r_year: string
  status: string
  loa_type: string | null
  loa_start_date: string | null
  loa_end_date: string | null
  refresher_training_type: string | null
  refresher_training_start: string | null
  refresher_training_end: string | null
  active_months_weight: number | null
  working_days_in_month: number | null
  updated_at: string | null
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
  updated_at: string | null
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
  updated_at: string | null
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
  updated_at: string | null
}

export type ParsedDataCorrectionValue = string | number | boolean | null

export interface ParsedDataCorrectionRequest {
  changes: Record<string, ParsedDataCorrectionValue>
  correction_reason: string
  last_seen_updated_at?: string | null
}

export interface ParsedDataCorrectionResponse<T extends ParsedDataRow = ParsedDataRow> {
  item: T
  audit_log_id: string
  entity_type: string
  entity_id: string | null
  updated_fields: string[]
  dataRevalidation?: DataRevalidationImpact | null
}

export interface ResidentPostingReplacementRow {
  resident_id: string
  posting_code: string | null
  reporting_period_id: string
  start_date: string
  end_date: string
  day_part: 'AM' | 'PM' | null
  month_label: string | null
  r_year: string
  status: string
  loa_type: string | null
  loa_start_date: string | null
  loa_end_date: string | null
  refresher_training_type: string | null
  refresher_training_start: string | null
  refresher_training_end: string | null
  active_months_weight: number
  working_days_in_month: number | null
}

export interface ParsedDataLastSeenRow {
  id: string
  updated_at: string
}

export interface ParsedDataSourceCellMetadata {
  upload_log_id: string | null
  sheet_name: string | null
  row_number: number | null
  cell_ref: string | null
  source_column_header: string | null
  source_cell_text: string | null
}

export interface ResidentPostingSourceCellReplaceRequest {
  affected_resident_posting_ids: string[]
  replacement_rows: ResidentPostingReplacementRow[]
  correction_reason: string
  source: ParsedDataSourceCellMetadata
  last_seen_rows: ParsedDataLastSeenRow[]
}

export interface ParsedDataSourceCellReplaceResponse {
  before_rows: ParsedResidentPostingRow[]
  after_rows: ParsedResidentPostingRow[]
  audit_log_id: string
  entity_type: string
  entity_id: string | null
  updated_fields: string[]
  dataRevalidation?: DataRevalidationImpact | null
}

export interface ParsedDataCorrectionHistoryRow {
  id: string
  created_at: string
  actor_user_id: string | null
  actor_role: string
  actor_name: string
  action: string
  entity_type: string
  entity_id: string | null
  correction_reason: string | null
  before_json: unknown
  after_json: unknown
  metadata_json: unknown
}

export type ParsedDataCorrectionHistoryListResponse =
  ParsedDataListResponse<ParsedDataCorrectionHistoryRow>

export type ParsedDataRow =
  | ParsedResidentRow
  | ParsedResidentPostingRow
  | ParsedTeachingTargetRow
  | ParsedFormF1RecordRow
  | ParsedPublicHolidayRow
  | ParsedAcademicMonthBoundaryRow
