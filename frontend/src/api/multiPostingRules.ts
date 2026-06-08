import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export type MultiPostingRuleType = 'main_posting' | 'combine' | 'half_month'

export interface MultiPostingRule {
  id: string
  programmeCode: string
  postingCode1: string
  postingCode2?: string
  ruleType: MultiPostingRuleType
  combinedLabel?: string
  mainPostingCode?: string
  exclusionCode?: string
  createdAt?: string
  updatedAt?: string
}

export interface MultiPostingRulePayload {
  programmeCode: string
  postingCode1: string
  postingCode2?: string | null
  ruleType: MultiPostingRuleType
  combinedLabel?: string | null
  mainPostingCode?: string | null
  exclusionCode?: string | null
}

interface MultiPostingRulesRequestContext {
  adminId: string
  adminProgrammes: string[]
  adminLevel?: AdminDemoLevel
}

const toOptionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value : undefined

const toRule = (value: Record<string, unknown>): MultiPostingRule => ({
  id: String(value.id ?? ''),
  programmeCode: String(value.programme_code ?? ''),
  postingCode1: String(value.posting_code_1 ?? ''),
  postingCode2: toOptionalString(value.posting_code_2),
  ruleType: String(value.rule_type ?? 'combine') as MultiPostingRuleType,
  combinedLabel: toOptionalString(value.combined_label),
  mainPostingCode: toOptionalString(value.main_posting_code),
  exclusionCode: toOptionalString(value.exclusion_code),
  createdAt: toOptionalString(value.created_at),
  updatedAt: toOptionalString(value.updated_at),
})

const toApiPayload = (payload: MultiPostingRulePayload): Record<string, unknown> => ({
  programme_code: payload.programmeCode,
  posting_code_1: payload.postingCode1,
  posting_code_2: payload.postingCode2 ?? null,
  rule_type: payload.ruleType,
  combined_label: payload.combinedLabel ?? null,
  main_posting_code: payload.mainPostingCode ?? null,
  exclusion_code: payload.exclusionCode ?? null,
})

export const listMultiPostingRules = async (
  params: MultiPostingRulesRequestContext & { ruleType?: MultiPostingRuleType },
): Promise<MultiPostingRule[]> => {
  try {
    const response = await httpClient.get('/admin/multi-posting-rules', {
      params: params.ruleType ? { rule_type: params.ruleType } : undefined,
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toRule)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createMultiPostingRule = async (
  params: MultiPostingRulesRequestContext & { payload: MultiPostingRulePayload },
): Promise<MultiPostingRule> => {
  try {
    const response = await httpClient.post(
      '/admin/multi-posting-rules',
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
      },
    )
    return toRule(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateMultiPostingRule = async (
  params: MultiPostingRulesRequestContext & {
    id: string
    payload: MultiPostingRulePayload
  },
): Promise<MultiPostingRule> => {
  try {
    const response = await httpClient.put(
      `/admin/multi-posting-rules/${params.id}`,
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
      },
    )
    return toRule(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deleteMultiPostingRule = async (
  params: MultiPostingRulesRequestContext & { id: string },
): Promise<void> => {
  try {
    await httpClient.delete(`/admin/multi-posting-rules/${params.id}`, {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, params.adminLevel),
    })
  } catch (error) {
    throw toApiRequestError(error)
  }
}
