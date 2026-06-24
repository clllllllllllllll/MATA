import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { toDataRevalidationImpact } from './dataRevalidation'
import { httpClient, toApiRequestError } from './http'
import type { DataRevalidationImpact } from '../types/dataRevalidation'

export interface Programme {
  id: string
  code: string
  name: string
  classification?: string
  ayDateCategory: string
  rYearRequired: boolean
  isSubspecialty: boolean
  rdbAlias?: string
  createdAt?: string
  updatedAt?: string
  dataRevalidation?: DataRevalidationImpact | null
}

interface ProgrammeRequestContext {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  actorName?: string
}

export interface ProgrammeMutationPayload {
  rYearRequired: boolean
  isSubspecialty: boolean
  rdbAlias?: string | null
}

const toProgramme = (value: Record<string, unknown>): Programme => ({
  id: String(value.id ?? ''),
  code: String(value.code ?? ''),
  name: String(value.name ?? ''),
  classification: value.classification ? String(value.classification) : undefined,
  ayDateCategory: String(value.ay_date_category ?? ''),
  rYearRequired: Boolean(value.r_year_required),
  isSubspecialty: Boolean(value.is_subspecialty),
  rdbAlias: value.rdb_alias ? String(value.rdb_alias) : undefined,
  createdAt: value.created_at ? String(value.created_at) : undefined,
  updatedAt: value.updated_at ? String(value.updated_at) : undefined,
  dataRevalidation: toDataRevalidationImpact(value.data_revalidation),
})

const toApiPayload = (payload: ProgrammeMutationPayload): Record<string, unknown> => ({
  r_year_required: payload.rYearRequired,
  is_subspecialty: payload.isSubspecialty,
  rdb_alias: payload.rdbAlias ?? null,
})

export const listProgrammes = async (params: ProgrammeRequestContext): Promise<Programme[]> => {
  try {
    const response = await httpClient.get('/admin/programmes', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toProgramme)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateProgramme = async (
  params: ProgrammeRequestContext & {
    code: string
    payload: ProgrammeMutationPayload
  },
): Promise<Programme> => {
  try {
    const response = await httpClient.put(
      `/admin/programmes/${params.code}`,
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(
          params.adminId,
          params.adminProgrammes,
          params.adminLevel,
          params.actorName,
        ),
      },
    )
    return toProgramme(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
