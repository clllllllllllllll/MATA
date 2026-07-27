import { frontendConfig } from '../config/frontendConfig'
import type { AppRole } from '../types/app'
import type { AuthIdentity, StoredAuthSession } from '../types/auth'
import { httpClient, toApiRequestError } from './http'
import type { ResidentLoginPayload } from './loginPayloads'
import {
  parseNonNhgRegistrationOptions,
  type NonNhgRegistrationOptions,
} from './nonNhgRegistrationOptions'
import { parseAuthSessionResponse, toAuthIdentity } from './authSessionResponse'
import {
  announceAuthSessionEstablished,
  authSessionChangedEvent,
  authSessionRevalidationEvent,
  captureAuthSessionFence,
  clearAuthSession,
  isAuthSessionFenceCurrent,
  readAuthSessionEpoch,
  readAuthSessionRevision,
  readStoredAuthSession,
  saveAuthSession,
  saveHydratedAuthSession,
  type AuthSessionFence,
} from './authSessionStore'

type BackendLoginRole = 'staff' | 'admin' | 'secretary' | 'resident' | 'external_resident'

type LoginPayload =
  | {
      role: 'staff' | 'admin' | 'secretary'
      email: string
      password: string
    }
  | ResidentLoginPayload

export interface NonNhgRegistrationPayload {
  name: string
  mcr: string
  homeCluster: 'NUH' | 'SingHealth'
  postingSchedule: Array<{
    startDate: string
    endDate: string
    programmeCode: string
    institution: string
  }>
}

export interface NonNhgRegistrationResult {
  resident: {
    id: string
    name: string
    mcr: string
    homeCluster: 'NUH' | 'SingHealth'
    currentNhgPostingCode: string
    status?: string
  }
  postingSchedule: Array<Record<string, unknown>>
}

const optionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined

const requiredString = (value: unknown): string => optionalString(value) ?? ''

export {
  announceAuthSessionEstablished,
  authSessionChangedEvent,
  authSessionRevalidationEvent,
  captureAuthSessionFence,
  clearAuthSession,
  isAuthSessionFenceCurrent,
  readAuthSessionEpoch,
  readAuthSessionRevision,
  readStoredAuthSession,
  saveAuthSession,
  saveHydratedAuthSession,
}
export type { AuthSessionFence }
export { parseNonNhgRegistrationOptions }
export type {
  NonNhgMappingStatus,
  NonNhgRegistrationAvailability,
  NonNhgRegistrationInstitution,
  NonNhgRegistrationOptions,
  NonNhgRegistrationProgramme,
} from './nonNhgRegistrationOptions'

export const roleToBackendRole = (role: AppRole): BackendLoginRole => {
  if (role === 'master_admin' || role === 'programme_pc') {
    return 'admin'
  }
  return role
}

export const toStubIdentityHeaders = (identity: AuthIdentity | null): Record<string, string> => {
  if (!identity || frontendConfig.authMode === 'supabase') {
    return {}
  }
  const headers: Record<string, string> = {
    'X-User-Role': roleToBackendRole(identity.role),
    'X-User-Id': identity.subjectId,
  }
  if (identity.role === 'master_admin' || identity.role === 'programme_pc') {
    headers['X-User-Programme'] = identity.programmeScope.join(',')
    if (identity.role === 'master_admin') {
      headers['X-Admin-Level'] = 'master'
    }
  }
  if (identity.role === 'secretary') {
    headers['X-User-Site'] = identity.postingCode
  }
  if (identity.role === 'resident') {
    headers['X-User-Programme'] = identity.programmeCode
    headers['X-User-MCR'] = identity.mcr
  }
  if (identity.role === 'external_resident') {
    headers['X-User-MCR'] = identity.mcr
  }
  return headers
}

export const toSessionRequestHeaders = (session: StoredAuthSession | null): Record<string, string> =>
  frontendConfig.authMode === 'supabase'
    ? {}
    : toStubIdentityHeaders(session?.identity ?? null)

const localIdentityConfig = () => {
  const headers = toSessionRequestHeaders(readStoredAuthSession())
  return Object.keys(headers).length > 0 ? { headers } : undefined
}

const parseLoginOrHydrationResponse = (value: unknown): StoredAuthSession => {
  try {
    return parseAuthSessionResponse(value)
  } catch (error) {
    if (frontendConfig.authMode === 'supabase' || !value || typeof value !== 'object') {
      throw error
    }
    const response = value as Record<string, unknown>
    const rawIdentity = response.user && typeof response.user === 'object'
      ? response.user as Record<string, unknown>
      : response
    return { identity: toAuthIdentity(rawIdentity), csrfToken: '' }
  }
}

export const login = async (payload: LoginPayload): Promise<StoredAuthSession> => {
  try {
    const response = await httpClient.post<unknown>('/auth/login', payload)
    return parseLoginOrHydrationResponse(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const loginResident = (payload: ResidentLoginPayload) => login(payload)

export const loginStaff = (email: string, password: string): Promise<StoredAuthSession> =>
  login({ role: 'staff', email, password })

export const refreshAuthSession = async (): Promise<StoredAuthSession> => {
  try {
    const response = await httpClient.post<unknown>('/auth/session/refresh')
    return parseAuthSessionResponse(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const hydrateAuthSession = async (): Promise<StoredAuthSession> => {
  try {
    const response = await httpClient.get<unknown>('/auth/me', localIdentityConfig())
    return parseLoginOrHydrationResponse(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const logoutAuthSession = async (
  session: StoredAuthSession,
  fence: AuthSessionFence,
): Promise<void> => {
  try {
    await httpClient.post('/auth/logout', undefined, {
      authSessionCsrfToken: session.csrfToken,
      authSessionEpoch: fence.sessionEpoch,
      authSessionRevision: fence.revision,
    })
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateStaffActorName = async (fullName: string): Promise<AuthIdentity> => {
  try {
    const response = await httpClient.post<Record<string, unknown>>(
      '/auth/staff-actor-name',
      { full_name: fullName },
      localIdentityConfig(),
    )
    return toAuthIdentity(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const registerNonNhgResident = async (
  payload: NonNhgRegistrationPayload,
): Promise<NonNhgRegistrationResult> => {
  try {
    const response = await httpClient.post<Record<string, unknown>>('/external-residents/register', {
      name: payload.name,
      mcr: payload.mcr,
      home_cluster: payload.homeCluster,
      posting_schedule: payload.postingSchedule.map((row) => ({
        start_date: row.startDate,
        end_date: row.endDate,
        programme_code: row.programmeCode,
        institution: row.institution,
      })),
    })
    const resident = (response.data.resident ?? {}) as Record<string, unknown>
    const homeCluster = resident.home_cluster
    if (homeCluster !== 'NUH' && homeCluster !== 'SingHealth') {
      throw new Error('Malformed registration response.')
    }
    const postingSchedule = Array.isArray(response.data.posting_schedule)
      ? response.data.posting_schedule.filter(
          (row): row is Record<string, unknown> => Boolean(row && typeof row === 'object'),
        )
      : payload.postingSchedule.map((row) => ({
          start_date: row.startDate,
          end_date: row.endDate,
          programme_code: row.programmeCode,
          institution: row.institution,
        }))
    return {
      resident: {
        id: requiredString(resident.id),
        name: requiredString(resident.name),
        mcr: requiredString(resident.mcr),
        homeCluster,
        currentNhgPostingCode: requiredString(resident.current_nhg_posting_code),
        status: optionalString(resident.status),
      },
      postingSchedule,
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const listNonNhgRegistrationOptions = async (): Promise<NonNhgRegistrationOptions> => {
  try {
    const response = await httpClient.get<unknown>('/external-residents/registration-options')
    return parseNonNhgRegistrationOptions(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
