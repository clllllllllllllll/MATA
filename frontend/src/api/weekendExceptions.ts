import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { toConfigDeleteResult, toDataRevalidationImpact, type ConfigDeleteResult } from './dataRevalidation'
import { httpClient, toApiRequestError } from './http'
import type { DataRevalidationImpact } from '../types/dataRevalidation'

export interface WeekendException {
  id: string
  programmeCode?: string
  postingCode?: string
  dayType: 'sat' | 'sun' | 'both'
  startTimeMin?: string
  endTimeMax?: string
  sessionTypeId?: string
  sessionTypeName?: string
  sessionNamePattern?: string
  mutatesToSessionTypeId?: string
  mutatesToSessionTypeName?: string
  adjustedDurationHours?: string
  createdAt?: string
  updatedAt?: string
  dataRevalidation?: DataRevalidationImpact | null
}

interface WeekendExceptionRequestContext {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  actorName?: string
}

export interface WeekendExceptionMutationPayload {
  programmeCode?: string | null
  postingCode?: string | null
  dayType: 'sat' | 'sun' | 'both'
  startTimeMin?: string | null
  endTimeMax?: string | null
  sessionTypeId?: string | null
  sessionNamePattern?: string | null
  mutatesToSessionTypeId?: string | null
  adjustedDurationHours?: string | null
}

const toOptionalString = (value: unknown): string | undefined =>
  value === null || value === undefined || value === '' ? undefined : String(value)

const toWeekendException = (value: Record<string, unknown>): WeekendException => ({
  id: String(value.id ?? ''),
  programmeCode: toOptionalString(value.programme_code),
  postingCode: toOptionalString(value.posting_code),
  dayType: value.day_type === 'sun' || value.day_type === 'both' ? value.day_type : 'sat',
  startTimeMin: toOptionalString(value.start_time_min),
  endTimeMax: toOptionalString(value.end_time_max),
  sessionTypeId: toOptionalString(value.session_type_id),
  sessionTypeName: toOptionalString(value.session_type_name),
  sessionNamePattern: toOptionalString(value.session_name_pattern),
  mutatesToSessionTypeId: toOptionalString(value.mutates_to_session_type_id),
  mutatesToSessionTypeName: toOptionalString(value.mutates_to_session_type_name),
  adjustedDurationHours: toOptionalString(value.adjusted_duration_hours),
  createdAt: toOptionalString(value.created_at),
  updatedAt: toOptionalString(value.updated_at),
  dataRevalidation: toDataRevalidationImpact(value.data_revalidation),
})

const toApiPayload = (payload: WeekendExceptionMutationPayload): Record<string, unknown> => ({
  programme_code: payload.programmeCode ?? null,
  posting_code: payload.postingCode ?? null,
  day_type: payload.dayType,
  start_time_min: payload.startTimeMin ?? null,
  end_time_max: payload.endTimeMax ?? null,
  session_type_id: payload.sessionTypeId ?? null,
  session_name_pattern: payload.sessionNamePattern ?? null,
  mutates_to_session_type_id: payload.mutatesToSessionTypeId ?? null,
  adjusted_duration_hours: payload.adjustedDurationHours ?? null,
})

export const listWeekendExceptions = async (
  params: WeekendExceptionRequestContext,
): Promise<WeekendException[]> => {
  try {
    const response = await httpClient.get('/admin/weekend-exceptions', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toWeekendException)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createWeekendException = async (
  params: WeekendExceptionRequestContext & { payload: WeekendExceptionMutationPayload },
): Promise<WeekendException> => {
  try {
    const response = await httpClient.post(
      '/admin/weekend-exceptions',
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
      },
    )
    return toWeekendException(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateWeekendException = async (
  params: WeekendExceptionRequestContext & {
    id: string
    payload: WeekendExceptionMutationPayload
  },
): Promise<WeekendException> => {
  try {
    const response = await httpClient.put(
      `/admin/weekend-exceptions/${params.id}`,
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
      },
    )
    return toWeekendException(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deleteWeekendException = async (
  params: WeekendExceptionRequestContext & { id: string },
): Promise<ConfigDeleteResult> => {
  try {
    const response = await httpClient.delete(`/admin/weekend-exceptions/${params.id}`, {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
    })
    return toConfigDeleteResult(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
