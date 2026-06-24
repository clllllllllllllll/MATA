import type { UploadType } from './app'

export type AdminLogType =
  | 'upload'
  | 'warning'
  | 'warning_action'
  | 'source_cell_correction'
  | 'parsed_data_correction'
  | 'config_mutation'
  | 'data_revalidation'

export type AdminLogActorRole =
  | 'master_admin'
  | 'programme_pc'
  | 'admin'
  | 'secretary'
  | 'resident'
  | 'external_resident'
  | string

export type AdminLogRelationship =
  | 'primary'
  | 'source'
  | 'occurrence'
  | 'workflow_issue'
  | 'audit_log'
  | 'upload_log'
  | 'resident'
  | 'config_entity'
  | 'related'
  | string

export type AdminLogActionName =
  | 'view_upload_evidence'
  | 'view_raw_summary'
  | 'view_warning'
  | 'view_warning_occurrence'
  | 'view_parsed_data'
  | 'view_config'
  | 'view_data_revalidation'
  | 'download_raw_audit'
  | string

export interface AdminLogSourceRef {
  sheet_name?: string | null
  row_number?: number | null
  cell_ref?: string | null
}

export interface AdminLogDeepLink {
  route: string
  params?: Record<string, unknown>
  query?: Record<string, unknown>
  drawer?: string | null
  entity_id?: string | null
}

export interface AdminLogListItem {
  id: string
  log_type: AdminLogType
  occurred_at: string
  actor_user_id?: string | null
  actor_name?: string | null
  actor_role?: AdminLogActorRole | null
  stored_actor_role?: string | null
  actor_admin_level?: string | null
  programme_code?: string | null
  reporting_period_id?: string | null
  entity_type?: string | null
  entity_id?: string | null
  upload_log_id?: string | null
  warning_issue_id?: string | null
  upload_warning_id?: string | null
  upload_type?: UploadType | null
  warning_type?: string | null
  status?: string | null
  outcome?: string | null
  title: string
  summary: string
  source_ref?: AdminLogSourceRef | null
  deep_link?: AdminLogDeepLink | null
}

export interface AdminLogListResponse {
  items: AdminLogListItem[]
  total: number
  limit: number
  offset: number
}

export interface AdminLogRelatedEntity {
  entity_type: string
  entity_id?: string | null
  label: string
  relationship: AdminLogRelationship
  deep_link?: AdminLogDeepLink | null
}

export interface AdminLogAction {
  action: AdminLogActionName
  label: string
  method?: string | null
  endpoint?: string | null
  deep_link?: AdminLogDeepLink | null
}

export interface AdminLogDetailResponse {
  id: string
  log_type: AdminLogType
  list_item: AdminLogListItem
  immutable_evidence: Record<string, unknown>
  workflow_status?: Record<string, unknown> | null
  related_entities: AdminLogRelatedEntity[]
  available_actions: AdminLogAction[]
}
