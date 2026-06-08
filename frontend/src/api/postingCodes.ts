import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export interface PostingCodeOption {
  id: string
  code: string
  displayName?: string
  institution?: string
  department?: string
}

interface ListPostingCodesParams {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
}

const toOptionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value : undefined

const toPostingCodeOption = (value: Record<string, unknown>): PostingCodeOption => ({
  id: String(value.id ?? value.code ?? ''),
  code: String(value.code ?? ''),
  displayName: toOptionalString(value.display_name),
  institution: toOptionalString(value.institution),
  department: toOptionalString(value.department),
})

export const listPostingCodes = async ({
  adminId,
  adminProgrammes,
  adminLevel,
}: ListPostingCodesParams): Promise<PostingCodeOption[]> => {
  try {
    const response = await httpClient.get<unknown[]>('/admin/posting-codes', {
      params: { limit: 500 },
      headers: buildAdminDemoHeaders(adminId, adminProgrammes, adminLevel),
    })
    return Array.isArray(response.data)
      ? response.data.map((entry) => toPostingCodeOption(entry as Record<string, unknown>))
      : []
  } catch (error) {
    throw toApiRequestError(error)
  }
}
