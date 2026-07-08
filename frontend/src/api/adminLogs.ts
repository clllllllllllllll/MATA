import type { UploadType } from '../types/app'
import type {
  AdminLogAction,
  AdminLogActorRole,
  AdminLogDeepLink,
  AdminLogDetailResponse,
  AdminLogListItem,
  AdminLogListResponse,
  AdminLogRelatedEntity,
  AdminLogSourceRef,
  AdminLogType,
} from '../types/adminLogs'
import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface ListAdminLogsParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  logType?: AdminLogType | 'all'
  actorUserId?: string
  actorRole?: AdminLogActorRole | 'all'
  uploadType?: UploadType | 'all'
  warningType?: string
  entityType?: string
  entityId?: string
  programmeCode?: string
  reportingPeriodId?: string
  status?: string
  outcome?: string
  dateFrom?: string
  dateTo?: string
  search?: string
  correctionType?: string
  configEntityType?: string
  limit?: number
  offset?: number
}

export interface GetAdminLogDetailParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  logId: string
}

const logTypes: AdminLogType[] = [
  'upload',
  'warning',
  'warning_action',
  'source_cell_correction',
  'parsed_data_correction',
  'config_mutation',
  'data_revalidation',
]

const uploadTypes: UploadType[] = ['rdb', 'ttf', 'form_f1', 'public_holidays']

const optionalString = (value: unknown): string | null => {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || null
}

const finiteNumber = (value: unknown, fallback = 0): number => {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

const toRecord = (value: unknown): Record<string, unknown> => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return {}
  }
  return value as Record<string, unknown>
}

const optionalRecord = (value: unknown): Record<string, unknown> | null => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return null
  }
  return value as Record<string, unknown>
}

const toLogType = (value: unknown): AdminLogType => {
  return logTypes.find((item) => item === value) ?? 'upload'
}

const toUploadType = (value: unknown): UploadType | null => {
  return uploadTypes.find((item) => item === value) ?? null
}

const toSourceRef = (value: unknown): AdminLogSourceRef | null => {
  const record = optionalRecord(value)
  if (!record) {
    return null
  }
  const rowNumber = finiteNumber(record.row_number, Number.NaN)
  return {
    sheet_name: optionalString(record.sheet_name),
    row_number: Number.isFinite(rowNumber) ? rowNumber : null,
    cell_ref: optionalString(record.cell_ref),
  }
}

const toDeepLink = (value: unknown): AdminLogDeepLink | null => {
  const record = optionalRecord(value)
  if (!record) {
    return null
  }
  const route = optionalString(record.route)
  if (!route) {
    return null
  }
  return {
    route,
    params: optionalRecord(record.params) ?? undefined,
    query: optionalRecord(record.query) ?? undefined,
    drawer: optionalString(record.drawer),
    entity_id: optionalString(record.entity_id),
  }
}

const toListItem = (value: Record<string, unknown>): AdminLogListItem => ({
  id: String(value.id ?? ''),
  log_type: toLogType(value.log_type),
  occurred_at: String(value.occurred_at ?? ''),
  actor_user_id: optionalString(value.actor_user_id),
  actor_name: optionalString(value.actor_name),
  actor_role: optionalString(value.actor_role),
  stored_actor_role: optionalString(value.stored_actor_role),
  actor_admin_level: optionalString(value.actor_admin_level),
  programme_code: optionalString(value.programme_code),
  reporting_period_id: optionalString(value.reporting_period_id),
  reporting_period_label: optionalString(value.reporting_period_label),
  entity_type: optionalString(value.entity_type),
  entity_id: optionalString(value.entity_id),
  upload_log_id: optionalString(value.upload_log_id),
  warning_issue_id: optionalString(value.warning_issue_id),
  upload_warning_id: optionalString(value.upload_warning_id),
  upload_type: toUploadType(value.upload_type),
  warning_type: optionalString(value.warning_type),
  status: optionalString(value.status),
  outcome: optionalString(value.outcome),
  title: optionalString(value.title) ?? 'Admin log entry',
  summary: optionalString(value.summary) ?? '',
  source_ref: toSourceRef(value.source_ref),
  deep_link: toDeepLink(value.deep_link),
})

const toRelatedEntity = (value: Record<string, unknown>): AdminLogRelatedEntity => ({
  entity_type: optionalString(value.entity_type) ?? 'related',
  entity_id: optionalString(value.entity_id),
  label: optionalString(value.label) ?? optionalString(value.entity_type) ?? 'Related entity',
  relationship: optionalString(value.relationship) ?? 'related',
  deep_link: toDeepLink(value.deep_link),
})

const toAction = (value: Record<string, unknown>): AdminLogAction => ({
  action: optionalString(value.action) ?? 'view_data_revalidation',
  label: optionalString(value.label) ?? 'Open',
  method: optionalString(value.method),
  endpoint: optionalString(value.endpoint),
  deep_link: toDeepLink(value.deep_link),
})

const toRecordArray = (value: unknown): Record<string, unknown>[] => {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item): item is Record<string, unknown> => {
    return typeof item === 'object' && item !== null && !Array.isArray(item)
  })
}

const toDetail = (value: Record<string, unknown>): AdminLogDetailResponse => {
  const listItemRecord = optionalRecord(value.list_item) ?? value
  return {
    id: String(value.id ?? listItemRecord.id ?? ''),
    log_type: toLogType(value.log_type ?? listItemRecord.log_type),
    list_item: toListItem(listItemRecord),
    immutable_evidence: toRecord(value.immutable_evidence),
    workflow_status: optionalRecord(value.workflow_status),
    related_entities: toRecordArray(value.related_entities).map(toRelatedEntity),
    available_actions: toRecordArray(value.available_actions).map(toAction),
  }
}

const headersFor = (
  adminId: string,
  adminProgrammes: string[],
  adminLevel: AdminDemoLevel = 'master',
) => buildAdminDemoHeaders(adminId, adminProgrammes, adminLevel)

const addStringParam = (
  queryParams: Record<string, string | number>,
  key: string,
  value?: string | null,
) => {
  const text = value?.trim()
  if (text && text !== 'all') {
    queryParams[key] = text
  }
}

export const listAdminLogs = async (
  params: ListAdminLogsParams,
): Promise<AdminLogListResponse> => {
  const queryParams: Record<string, string | number> = {}
  addStringParam(queryParams, 'log_type', params.logType)
  addStringParam(queryParams, 'actor_user_id', params.actorUserId)
  addStringParam(queryParams, 'actor_role', params.actorRole)
  addStringParam(queryParams, 'upload_type', params.uploadType)
  addStringParam(queryParams, 'warning_type', params.warningType)
  addStringParam(queryParams, 'entity_type', params.entityType)
  addStringParam(queryParams, 'entity_id', params.entityId)
  addStringParam(queryParams, 'programme_code', params.programmeCode)
  addStringParam(queryParams, 'reporting_period_id', params.reportingPeriodId)
  addStringParam(queryParams, 'status', params.status)
  addStringParam(queryParams, 'outcome', params.outcome)
  addStringParam(queryParams, 'date_from', params.dateFrom)
  addStringParam(queryParams, 'date_to', params.dateTo)
  addStringParam(queryParams, 'search', params.search)
  addStringParam(queryParams, 'correction_type', params.correctionType)
  addStringParam(queryParams, 'config_entity_type', params.configEntityType)

  if (params.limit) {
    queryParams.limit = params.limit
  }
  if (params.offset) {
    queryParams.offset = params.offset
  }

  try {
    const response = await httpClient.get('/admin/logs', {
      headers: headersFor(params.adminId, params.adminProgrammes, params.adminLevel),
      params: queryParams,
    })
    const payload = toRecord(response.data)
    return {
      items: toRecordArray(payload.items).map(toListItem),
      total: finiteNumber(payload.total),
      limit: finiteNumber(payload.limit, params.limit ?? 50),
      offset: finiteNumber(payload.offset, params.offset ?? 0),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const getAdminLogDetail = async ({
  adminId,
  adminProgrammes,
  adminLevel = 'master',
  logId,
}: GetAdminLogDetailParams): Promise<AdminLogDetailResponse> => {
  try {
    const response = await httpClient.get(`/admin/logs/${encodeURIComponent(logId)}`, {
      headers: headersFor(adminId, adminProgrammes, adminLevel),
    })
    return toDetail(toRecord(response.data))
  } catch (error) {
    throw toApiRequestError(error)
  }
}
