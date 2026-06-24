import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { toConfigDeleteResult, toDataRevalidationImpact, type ConfigDeleteResult } from './dataRevalidation'
import { httpClient, toApiRequestError } from './http'
import type { DataRevalidationImpact } from '../types/dataRevalidation'

export interface GlobalSessionType {
  id: string
  name: string
  durationHours: string
  isActive: boolean
  createdAt?: string
  updatedAt?: string
  dataRevalidation?: DataRevalidationImpact | null
}

interface GlobalSessionTypeRequestContext {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  actorName?: string
}

export interface GlobalSessionTypeMutationPayload {
  name?: string
  durationHours?: string
  isActive?: boolean
}

const toOptionalString = (value: unknown): string | undefined =>
  value === null || value === undefined || value === '' ? undefined : String(value)

const toGlobalSessionType = (value: Record<string, unknown>): GlobalSessionType => ({
  id: String(value.id ?? ''),
  name: String(value.name ?? ''),
  durationHours: String(value.duration_hours ?? ''),
  isActive: Boolean(value.is_active),
  createdAt: toOptionalString(value.created_at),
  updatedAt: toOptionalString(value.updated_at),
  dataRevalidation: toDataRevalidationImpact(value.data_revalidation),
})

const toApiPayload = (payload: GlobalSessionTypeMutationPayload): Record<string, unknown> => ({
  name: payload.name,
  duration_hours: payload.durationHours,
  is_active: payload.isActive,
})

export const listGlobalSessionTypes = async (
  params: GlobalSessionTypeRequestContext,
): Promise<GlobalSessionType[]> => {
  try {
    const response = await httpClient.get('/admin/global-session-types', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toGlobalSessionType)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createGlobalSessionType = async (
  params: GlobalSessionTypeRequestContext & { payload: GlobalSessionTypeMutationPayload },
): Promise<GlobalSessionType> => {
  try {
    const response = await httpClient.post(
      '/admin/global-session-types',
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
      },
    )
    return toGlobalSessionType(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateGlobalSessionType = async (
  params: GlobalSessionTypeRequestContext & {
    id: string
    payload: GlobalSessionTypeMutationPayload
  },
): Promise<GlobalSessionType> => {
  try {
    const response = await httpClient.put(
      `/admin/global-session-types/${params.id}`,
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
      },
    )
    return toGlobalSessionType(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deleteGlobalSessionType = async (
  params: GlobalSessionTypeRequestContext & { id: string },
): Promise<ConfigDeleteResult> => {
  try {
    const response = await httpClient.delete(`/admin/global-session-types/${params.id}`, {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
    })
    return toConfigDeleteResult(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
