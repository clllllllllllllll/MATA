import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface LoaType {
  id: string
  code: string
  description?: string
  createdAt?: string
  updatedAt?: string
}

interface LoaTypeRequestContext {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  actorName?: string
}

export interface LoaTypeMutationPayload {
  code: string
  description?: string | null
}

const toLoaType = (value: Record<string, unknown>): LoaType => ({
  id: String(value.id ?? ''),
  code: String(value.code ?? ''),
  description: value.description ? String(value.description) : undefined,
  createdAt: value.created_at ? String(value.created_at) : undefined,
  updatedAt: value.updated_at ? String(value.updated_at) : undefined,
})

const toApiPayload = (payload: LoaTypeMutationPayload): Record<string, unknown> => ({
  code: payload.code,
  description: payload.description ?? null,
})

export const listLoaTypes = async (params: LoaTypeRequestContext): Promise<LoaType[]> => {
  try {
    const response = await httpClient.get('/admin/loa-types', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toLoaType)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createLoaType = async (
  params: LoaTypeRequestContext & { payload: LoaTypeMutationPayload },
): Promise<LoaType> => {
  try {
    const response = await httpClient.post('/admin/loa-types', toApiPayload(params.payload), {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
    })
    return toLoaType(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateLoaType = async (
  params: LoaTypeRequestContext & {
    id: string
    payload: LoaTypeMutationPayload
  },
): Promise<LoaType> => {
  try {
    const response = await httpClient.put(
      `/admin/loa-types/${params.id}`,
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
      },
    )
    return toLoaType(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deleteLoaType = async (
  params: LoaTypeRequestContext & { id: string },
): Promise<void> => {
  try {
    await httpClient.delete(`/admin/loa-types/${params.id}`, {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
    })
  } catch (error) {
    throw toApiRequestError(error)
  }
}
