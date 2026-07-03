import { buildAdminDemoHeaders } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export type StaffAccountType = 'master_admin' | 'programme_pc' | 'secretary'

export interface StaffAccount {
  id: string
  accountDisplayName: string
  email: string
  accountType: StaffAccountType
  role: string
  adminLevel: string
  programmeScope: string[]
  postingCode?: string
  isActive: boolean
  currentStaffActorName?: string
  staffActorNameUpdatedAt?: string
}

export interface StaffAccountCreatePayload {
  accountDisplayName: string
  email: string
  accountType: StaffAccountType
  password: string
  isActive: boolean
  programmeScope?: string[]
  postingCode?: string
}

export interface StaffAccountUpdatePayload {
  accountDisplayName?: string
  accountType?: StaffAccountType
  isActive?: boolean
  programmeScope?: string[]
  postingCode?: string
}

interface StaffAccountRequestContext {
  adminId: string
  adminProgrammes: string[]
}

const optionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value : undefined

const toStringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value
        .map((item) => (typeof item === 'string' ? item.trim() : ''))
        .filter((item) => item.length > 0)
    : []

const toStaffAccountType = (value: unknown): StaffAccountType => {
  if (value === 'master_admin' || value === 'secretary') {
    return value
  }
  return 'programme_pc'
}

const toStaffAccount = (value: Record<string, unknown>): StaffAccount => ({
  id: String(value.id ?? ''),
  accountDisplayName: String(value.account_display_name ?? value.name ?? ''),
  email: String(value.email ?? ''),
  accountType: toStaffAccountType(value.account_type),
  role: String(value.role ?? ''),
  adminLevel: String(value.admin_level ?? ''),
  programmeScope: toStringArray(value.programme_scope),
  postingCode: optionalString(value.posting_code),
  isActive: Boolean(value.is_active),
  currentStaffActorName: optionalString(value.current_staff_actor_name),
  staffActorNameUpdatedAt: optionalString(value.staff_actor_name_updated_at),
})

const toCreatePayload = (payload: StaffAccountCreatePayload): Record<string, unknown> => ({
  account_display_name: payload.accountDisplayName,
  email: payload.email,
  account_type: payload.accountType,
  password: payload.password,
  is_active: payload.isActive,
  programme_scope: payload.accountType === 'programme_pc' ? payload.programmeScope ?? [] : undefined,
  posting_code: payload.accountType === 'secretary' ? payload.postingCode : undefined,
})

const toUpdatePayload = (payload: StaffAccountUpdatePayload): Record<string, unknown> => ({
  account_display_name: payload.accountDisplayName,
  account_type: payload.accountType,
  is_active: payload.isActive,
  programme_scope: payload.accountType === 'programme_pc' ? payload.programmeScope ?? [] : undefined,
  posting_code: payload.accountType === 'secretary' ? payload.postingCode : undefined,
})

export const listStaffAccounts = async (
  params: StaffAccountRequestContext,
): Promise<StaffAccount[]> => {
  try {
    const response = await httpClient.get('/admin/staff-accounts', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'master'),
    })
    const rows = (response.data as { items?: unknown })?.items
    return Array.isArray(rows)
      ? rows
          .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
          .map(toStaffAccount)
      : []
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createStaffAccount = async (
  params: StaffAccountRequestContext & { payload: StaffAccountCreatePayload },
): Promise<StaffAccount> => {
  try {
    const response = await httpClient.post(
      '/admin/staff-accounts',
      toCreatePayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'master'),
      },
    )
    return toStaffAccount(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateStaffAccount = async (
  params: StaffAccountRequestContext & {
    id: string
    payload: StaffAccountUpdatePayload
  },
): Promise<StaffAccount> => {
  try {
    const response = await httpClient.patch(
      `/admin/staff-accounts/${params.id}`,
      toUpdatePayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'master'),
      },
    )
    return toStaffAccount(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const resetStaffAccountPassword = async (
  params: StaffAccountRequestContext & { id: string; password: string },
): Promise<StaffAccount> => {
  try {
    const response = await httpClient.post(
      `/admin/staff-accounts/${params.id}/reset-password`,
      { password: params.password },
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, 'master'),
      },
    )
    return toStaffAccount(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
