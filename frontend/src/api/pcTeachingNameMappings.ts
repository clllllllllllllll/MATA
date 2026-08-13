import { buildAdminDemoHeaders } from './authHeaders'
import { ApiRequestError, httpClient, toApiRequestError } from './http'

export interface ProgrammePcTeachingNameRequestContext {
  adminId: string
  programmeScope: string[]
}

export interface ProgrammePcTeachingName {
  id: string
  reportingPeriodId: string
  programmeCode: string
  teachingName: string
  createdByRole: string
  visibilityScope: string
  originPostingCode?: string
  admissionReason: string
  canManageName: boolean
  isActive: boolean
  revision: number
  createdAt?: string
  updatedAt?: string
  deactivatedAt?: string
}

export interface ProgrammePcTeachingNameList {
  items: ProgrammePcTeachingName[]
  total: number
  limit: number
  offset: number
}

export interface TeachingNameMappingTarget {
  id: string
  sessionTypeId: string
  sessionTypeName: string
  durationHours: number
  monthlyTarget: number
  isTracked: boolean
  isReallocatable: boolean
  tag?: string
}

export type TeachingNameMappingState = 'pending' | 'mapped'

export interface ProgrammePcTeachingNameMapping {
  id: string
  teachingNameId: string
  teachingName: string
  teachingNameIsActive: boolean
  teachingNameRevision: number
  teachingNameOwnerProgrammeCode: string
  teachingNameCreatedByRole: string
  teachingNameVisibilityScope: string
  teachingNameOriginPostingCode?: string
  teachingNameAdmissionReason: string
  reportingPeriodId: string
  programmeCode: string
  postingCode: string
  rYear: string
  teachingTargetId: string | null
  state: TeachingNameMappingState
  revision: number
  target?: TeachingNameMappingTarget
  availableTargetOptions: TeachingNameMappingTarget[]
}

export interface ProgrammePcTeachingNameMappingList {
  items: ProgrammePcTeachingNameMapping[]
  total: number
  limit: number
  offset: number
}

export interface TeachingNameMappingImpact {
  affectedEventCount: number
  affectedAttendanceCount: number
}

export interface TeachingNameMappingBulkResult {
  requestedCount: number
  updatedCount: number
  mappedCount: number
  pendingCount: number
  affectedEventCount: number
  affectedAttendanceCount: number
}

export interface TeachingNameMappingMutationResult extends ProgrammePcTeachingNameMapping {
  impact: TeachingNameMappingImpact
}

const toRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}

const optionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined

const toNumber = (value: unknown, fallback = 0): number => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) {
      return parsed
    }
  }
  return fallback
}

const toTeachingName = (value: Record<string, unknown>): ProgrammePcTeachingName => ({
  id: String(value.id ?? ''),
  reportingPeriodId: String(value.reporting_period_id ?? ''),
  programmeCode: String(value.programme_code ?? ''),
  teachingName: String(value.teaching_name ?? ''),
  createdByRole: String(value.created_by_role ?? ''),
  visibilityScope: String(value.visibility_scope ?? ''),
  originPostingCode: optionalString(value.origin_posting_code),
  admissionReason: String(value.admission_reason ?? ''),
  canManageName: Boolean(value.can_manage_name),
  isActive: Boolean(value.is_active),
  revision: toNumber(value.revision, 1),
  createdAt: optionalString(value.created_at),
  updatedAt: optionalString(value.updated_at),
  deactivatedAt: optionalString(value.deactivated_at),
})

const toTarget = (value: Record<string, unknown>): TeachingNameMappingTarget => ({
  id: String(value.id ?? ''),
  sessionTypeId: String(value.session_type_id ?? ''),
  sessionTypeName: String(value.session_type_name ?? ''),
  durationHours: toNumber(value.duration_hours),
  monthlyTarget: toNumber(value.monthly_target),
  isTracked: Boolean(value.is_tracked),
  isReallocatable: Boolean(value.is_reallocatable),
  tag: optionalString(value.tag),
})

const toImpact = (value: unknown): TeachingNameMappingImpact => {
  const record = toRecord(value)
  return {
    affectedEventCount: toNumber(record.affected_event_count),
    affectedAttendanceCount: toNumber(record.affected_attendance_count),
  }
}

const toMapping = (value: Record<string, unknown>): ProgrammePcTeachingNameMapping => {
  const targetRecord = toRecord(value.target)
  const optionRows = Array.isArray(value.available_target_options) ? value.available_target_options : []
  return {
    id: String(value.id ?? ''),
    teachingNameId: String(value.teaching_name_id ?? ''),
    teachingName: String(value.teaching_name ?? ''),
    teachingNameIsActive: Boolean(value.teaching_name_is_active),
    teachingNameRevision: toNumber(value.teaching_name_revision, 1),
    teachingNameOwnerProgrammeCode: String(value.teaching_name_owner_programme_code ?? ''),
    teachingNameCreatedByRole: String(value.teaching_name_created_by_role ?? ''),
    teachingNameVisibilityScope: String(value.teaching_name_visibility_scope ?? ''),
    teachingNameOriginPostingCode: optionalString(value.teaching_name_origin_posting_code),
    teachingNameAdmissionReason: String(value.teaching_name_admission_reason ?? ''),
    reportingPeriodId: String(value.reporting_period_id ?? ''),
    programmeCode: String(value.programme_code ?? ''),
    postingCode: String(value.posting_code ?? ''),
    rYear: String(value.r_year ?? ''),
    teachingTargetId: optionalString(value.teaching_target_id) ?? null,
    state: value.state === 'mapped' ? 'mapped' : 'pending',
    revision: toNumber(value.revision, 1),
    target: targetRecord.id ? toTarget(targetRecord) : undefined,
    availableTargetOptions: optionRows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toTarget)
      .filter((target) => target.id.length > 0),
  }
}

const adminHeaders = (context: ProgrammePcTeachingNameRequestContext) =>
  buildAdminDemoHeaders(context.adminId, context.programmeScope, 'programme')

export const listProgrammePcTeachingNames = async (
  params: ProgrammePcTeachingNameRequestContext & {
    reportingPeriodId: string
    programmeCode: string
    isActive?: boolean
    search?: string
    limit?: number
    offset?: number
  },
): Promise<ProgrammePcTeachingNameList> => {
  try {
    const response = await httpClient.get('/admin/teaching-names', {
      params: {
        reporting_period_id: params.reportingPeriodId,
        programme_code: params.programmeCode,
        is_active: params.isActive,
        search: params.search?.trim() || undefined,
        limit: params.limit ?? 100,
        offset: params.offset ?? 0,
      },
      headers: adminHeaders(params),
    })
    const payload = toRecord(response.data)
    const rows = Array.isArray(payload.items) ? payload.items : []
    return {
      items: rows
        .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
        .map(toTeachingName),
      total: toNumber(payload.total),
      limit: toNumber(payload.limit, params.limit ?? 100),
      offset: toNumber(payload.offset, params.offset ?? 0),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createProgrammePcTeachingName = async (
  params: ProgrammePcTeachingNameRequestContext & {
    reportingPeriodId: string
    programmeCode: string
    teachingName: string
  },
): Promise<ProgrammePcTeachingName> => {
  try {
    const response = await httpClient.post('/admin/teaching-names', {
      reporting_period_id: params.reportingPeriodId,
      programme_code: params.programmeCode,
      teaching_name: params.teachingName,
    }, { headers: adminHeaders(params) })
    return toTeachingName(toRecord(response.data))
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const renameProgrammePcTeachingName = async (
  params: ProgrammePcTeachingNameRequestContext & {
    teachingNameId: string
    teachingName: string
    expectedRevision: number
  },
): Promise<ProgrammePcTeachingName> => {
  try {
    const response = await httpClient.patch(`/admin/teaching-names/${params.teachingNameId}`, {
      teaching_name: params.teachingName,
      expected_revision: params.expectedRevision,
    }, { headers: adminHeaders(params) })
    return toTeachingName(toRecord(response.data))
  } catch (error) {
    throw toApiRequestError(error)
  }
}

const updateProgrammePcTeachingNameStatus = async (
  params: ProgrammePcTeachingNameRequestContext & {
    teachingNameId: string
    expectedRevision: number
    action: 'deactivate' | 'reactivate'
  },
): Promise<ProgrammePcTeachingName> => {
  try {
    const response = await httpClient.post(
      `/admin/teaching-names/${params.teachingNameId}/${params.action}`,
      { expected_revision: params.expectedRevision },
      { headers: adminHeaders(params) },
    )
    return toTeachingName(toRecord(response.data))
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deactivateProgrammePcTeachingName = (
  params: ProgrammePcTeachingNameRequestContext & { teachingNameId: string; expectedRevision: number },
) => updateProgrammePcTeachingNameStatus({ ...params, action: 'deactivate' })

export const reactivateProgrammePcTeachingName = (
  params: ProgrammePcTeachingNameRequestContext & { teachingNameId: string; expectedRevision: number },
) => updateProgrammePcTeachingNameStatus({ ...params, action: 'reactivate' })

export const deleteProgrammePcTeachingName = async (
  params: ProgrammePcTeachingNameRequestContext & { teachingNameId: string; expectedRevision: number },
): Promise<void> => {
  try {
    await httpClient.delete(`/admin/teaching-names/${params.teachingNameId}`, {
      data: { expected_revision: params.expectedRevision },
      headers: adminHeaders(params),
    })
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const listProgrammePcTeachingNameMappings = async (
  params: ProgrammePcTeachingNameRequestContext & {
    reportingPeriodId: string
    programmeCode: string
    postingCode?: string
    rYear?: string
    state?: TeachingNameMappingState
    search?: string
    limit?: number
    offset?: number
  },
): Promise<ProgrammePcTeachingNameMappingList> => {
  try {
    const response = await httpClient.get('/admin/teaching-name-mappings', {
      params: {
        reporting_period_id: params.reportingPeriodId,
        programme_code: params.programmeCode,
        posting_code: params.postingCode?.trim() || undefined,
        r_year: params.rYear?.trim() || undefined,
        state: params.state,
        search: params.search?.trim() || undefined,
        limit: params.limit ?? 100,
        offset: params.offset ?? 0,
      },
      headers: adminHeaders(params),
    })
    const payload = toRecord(response.data)
    const rows = Array.isArray(payload.items) ? payload.items : []
    return {
      items: rows
        .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
        .map(toMapping),
      total: toNumber(payload.total),
      limit: toNumber(payload.limit, params.limit ?? 100),
      offset: toNumber(payload.offset, params.offset ?? 0),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const getProgrammePcTeachingNameMappingImpact = async (
  params: ProgrammePcTeachingNameRequestContext & {
    mappingId: string
    expectedRevision: number
    teachingTargetId: string | null
  },
): Promise<TeachingNameMappingImpact> => {
  try {
    const response = await httpClient.get(`/admin/teaching-name-mappings/${params.mappingId}/impact`, {
      params: {
        expected_revision: params.expectedRevision,
        teaching_target_id: params.teachingTargetId ?? undefined,
      },
      headers: adminHeaders(params),
    })
    return toImpact(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const applyProgrammePcTeachingNameMapping = async (
  params: ProgrammePcTeachingNameRequestContext & {
    mappingId: string
    expectedRevision: number
    teachingTargetId: string | null
    confirmImpact: boolean
  },
): Promise<TeachingNameMappingMutationResult> => {
  try {
    const response = await httpClient.patch(`/admin/teaching-name-mappings/${params.mappingId}`, {
      teaching_target_id: params.teachingTargetId,
      expected_revision: params.expectedRevision,
      confirm_impact: params.confirmImpact,
    }, { headers: adminHeaders(params) })
    const payload = toRecord(response.data)
    return {
      ...toMapping(payload),
      impact: toImpact(payload.impact),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const applyProgrammePcTeachingNameMappingBulk = async (
  params: ProgrammePcTeachingNameRequestContext & {
    items: Array<{
      mappingId: string
      expectedRevision: number
      teachingTargetId: string | null
      confirmImpact: boolean
    }>
  },
): Promise<TeachingNameMappingBulkResult> => {
  try {
    const response = await httpClient.post('/admin/teaching-name-mappings/bulk', {
      items: params.items.map((item) => ({
        mapping_id: item.mappingId,
        expected_revision: item.expectedRevision,
        teaching_target_id: item.teachingTargetId,
        confirm_impact: item.confirmImpact,
      })),
    }, { headers: adminHeaders(params) })
    const payload = toRecord(response.data)
    return {
      requestedCount: toNumber(payload.requested_count),
      updatedCount: toNumber(payload.updated_count),
      mappedCount: toNumber(payload.mapped_count),
      pendingCount: toNumber(payload.pending_count),
      affectedEventCount: toNumber(payload.affected_event_count),
      affectedAttendanceCount: toNumber(payload.affected_attendance_count),
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const mappingImpactFromConflict = (error: unknown): TeachingNameMappingImpact | null => {
  if (!(error instanceof ApiRequestError) || error.status !== 409) {
    return null
  }
  const details = toRecord(error.details)
  const metadata = toRecord(details.metadata)
  const impact = toRecord(metadata.impact)
  if (!Object.prototype.hasOwnProperty.call(impact, 'affected_event_count')
    && !Object.prototype.hasOwnProperty.call(impact, 'affected_attendance_count')) {
    return null
  }
  return toImpact(impact)
}

export const isTeachingNameMappingRevisionConflict = (error: unknown): boolean =>
  error instanceof ApiRequestError
  && error.status === 409
  && /changed; refresh and retry/i.test(error.message)
