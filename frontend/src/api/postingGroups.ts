import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { toConfigDeleteResult, toDataRevalidationImpact, type ConfigDeleteResult } from './dataRevalidation'
import { httpClient, toApiRequestError } from './http'
import type { DataRevalidationImpact } from '../types/dataRevalidation'

export interface PostingGroup {
  id: string
  groupCode: string
  postingCode: string
  programmeCode: string
  createdAt?: string
  updatedAt?: string
  dataRevalidation?: DataRevalidationImpact | null
}

interface PostingGroupRequestContext {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
  actorName?: string
}

export interface PostingGroupMutationPayload {
  groupCode: string
  postingCode: string
  programmeCode: string
}

const toOptionalString = (value: unknown): string | undefined =>
  value === null || value === undefined || value === '' ? undefined : String(value)

const toPostingGroup = (value: Record<string, unknown>): PostingGroup => ({
  id: String(value.id ?? ''),
  groupCode: String(value.group_code ?? ''),
  postingCode: String(value.posting_code ?? ''),
  programmeCode: String(value.programme_code ?? ''),
  createdAt: toOptionalString(value.created_at),
  updatedAt: toOptionalString(value.updated_at),
  dataRevalidation: toDataRevalidationImpact(value.data_revalidation),
})

const toApiPayload = (payload: PostingGroupMutationPayload): Record<string, unknown> => ({
  group_code: payload.groupCode,
  posting_code: payload.postingCode,
  programme_code: payload.programmeCode,
})

export const listPostingGroups = async (
  params: PostingGroupRequestContext,
): Promise<PostingGroup[]> => {
  try {
    const response = await httpClient.get('/admin/posting-groups', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toPostingGroup)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createPostingGroup = async (
  params: PostingGroupRequestContext & { payload: PostingGroupMutationPayload },
): Promise<PostingGroup> => {
  try {
    const response = await httpClient.post('/admin/posting-groups', toApiPayload(params.payload), {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
    })
    return toPostingGroup(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updatePostingGroup = async (
  params: PostingGroupRequestContext & {
    id: string
    payload: PostingGroupMutationPayload
  },
): Promise<PostingGroup> => {
  try {
    const response = await httpClient.put(
      `/admin/posting-groups/${params.id}`,
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
      },
    )
    return toPostingGroup(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deletePostingGroup = async (
  params: PostingGroupRequestContext & { id: string },
): Promise<ConfigDeleteResult> => {
  try {
    const response = await httpClient.delete(`/admin/posting-groups/${params.id}`, {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel, params.actorName),
    })
    return toConfigDeleteResult(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
