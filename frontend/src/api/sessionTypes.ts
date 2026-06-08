import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface SessionTypeOption {
  id: string
  name: string
  durationHours: string
}

interface SessionTypeRequestContext {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  limit?: number
}

const toSessionTypeOption = (value: Record<string, unknown>): SessionTypeOption => ({
  id: String(value.id ?? ''),
  name: String(value.name ?? ''),
  durationHours: String(value.duration_hours ?? ''),
})

export const listSessionTypes = async (
  params: SessionTypeRequestContext,
): Promise<SessionTypeOption[]> => {
  try {
    const response = await httpClient.get('/admin/session-types', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
      params: { limit: params.limit ?? 500 },
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toSessionTypeOption)
      .filter((row) => row.id && row.name)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
