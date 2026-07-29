import { frontendConfig } from '../config/frontendConfig'
import type { AppRole } from '../types/app'
import type { AuthIdentity, StoredAuthSession } from '../types/auth'
import { httpClient, toApiRequestError } from './http'
import type { ResidentLoginPayload } from './loginPayloads'
import {
  parseLogoutAuthSessionResponse,
  type LogoutAuthSessionResult,
} from './logoutResponse'
import { withAuthCookieResponseLock } from './authCookieCoordination'
import {
  parseNonNhgRegistrationOptions,
  type NonNhgRegistrationOptions,
} from './nonNhgRegistrationOptions'
import { parseAuthSessionResponse, toAuthIdentity } from './authSessionResponse'
import {
  announceAuthSessionEstablished,
  authSessionChangedEvent,
  authSessionEstablishedEvent,
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

export type LogoutAuthSessionProof = {
  csrfToken: string
  sessionEpoch: string | null
  sessionRevision: number
}

export type LogoutAuthSessionCoordination = {
  prepareDispatch: () => boolean
  confirmRevocation: () => boolean
  signal: AbortSignal
}

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

const withCookieResponseCoordination = <T>(
  operation: () => Promise<T>,
  signal?: AbortSignal,
): Promise<T> =>
  frontendConfig.authMode === 'supabase'
    ? withAuthCookieResponseLock(operation, undefined, signal)
    : operation()

export {
  announceAuthSessionEstablished,
  authSessionChangedEvent,
  authSessionEstablishedEvent,
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

export const login = async (
  payload: LoginPayload,
  commitSession?: (session: StoredAuthSession) => boolean,
): Promise<StoredAuthSession> => {
  try {
    return await withCookieResponseCoordination(async () => {
      const response = await httpClient.post<unknown>('/auth/login', payload, {
        allowDuringLogoutPending: true,
      })
      const session = parseLoginOrHydrationResponse(response.data)
      commitSession?.(session)
      return session
    })
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const loginResident = (
  payload: ResidentLoginPayload,
  commitSession?: (session: StoredAuthSession) => boolean,
) => login(payload, commitSession)

export const loginStaff = (
  email: string,
  password: string,
  commitSession?: (session: StoredAuthSession) => boolean,
): Promise<StoredAuthSession> =>
  login({ role: 'staff', email, password }, commitSession)

export const refreshAuthSession = async (): Promise<StoredAuthSession> => {
  try {
    return await withCookieResponseCoordination(async () => {
      const response = await httpClient.post<unknown>('/auth/session/refresh')
      return parseAuthSessionResponse(response.data)
    })
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
  proof: LogoutAuthSessionProof,
  coordination: LogoutAuthSessionCoordination,
): Promise<LogoutAuthSessionResult> => {
  try {
    return await withCookieResponseCoordination(async () => {
      if (coordination.signal.aborted || !coordination.prepareDispatch()) {
        return 'stale'
      }
      const response = await httpClient.post<unknown>('/auth/logout', undefined, {
        allowDuringLogoutPending: true,
        authSessionCsrfToken: proof.csrfToken,
        authSessionEpoch: proof.sessionEpoch,
        authSessionRevision: proof.sessionRevision,
        signal: coordination.signal,
      })
      const result = parseLogoutAuthSessionResponse(response.data)
      if (result !== 'confirmed') {
        return result
      }
      return coordination.confirmRevocation() ? 'confirmed' : 'stale'
    }, coordination.signal)
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
