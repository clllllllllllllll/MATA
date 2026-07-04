import { frontendConfig } from '../config/frontendConfig'
import type { AppRole } from '../types/app'
import type { AuthIdentity, StoredAuthSession } from '../types/auth'
import { ApiRequestError, httpClient, toApiRequestError } from './http'
import {
  authSessionChangedEvent,
  clearAuthSession,
  readStoredAuthSession,
  saveAuthSession,
} from './authSessionStore'
import {
  getCurrentSupabaseSessionToken,
  signInWithSupabasePassword,
  SupabaseConfigurationError,
} from './supabaseClient'

type BackendLoginRole = 'staff' | 'admin' | 'secretary' | 'resident' | 'external_resident'

type LoginPayload =
  | {
      role: 'staff' | 'admin' | 'secretary'
      email: string
      password: string
    }
  | {
      role: 'resident' | 'external_resident'
      mcr: string
    }

interface BackendLoginResponse {
  access_token: string
  token_type: string
  user: Record<string, unknown>
}

export interface NonNhgRegistrationPayload {
  name: string
  mcr: string
  homeCluster: 'NUH' | 'SingHealth'
  postingSchedule: Array<{
    startDate: string
    endDate: string
    programmeCode: string
    institution: 'TTSH' | 'WH' | 'KTPH'
    postingCode: string
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
  postingSchedule?: Array<Record<string, unknown>>
  session?: StoredAuthSession
}

const optionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value : undefined

const requiredString = (value: unknown): string => optionalString(value) ?? ''

const toStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value
      .map((item) => (typeof item === 'string' ? item.trim() : ''))
      .filter((item) => item.length > 0)
  }
  if (typeof value === 'string') {
    return value
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0)
  }
  return []
}

const toHomeCluster = (value: unknown): 'NUH' | 'SingHealth' =>
  String(value).toLowerCase() === 'singhealth' ? 'SingHealth' : 'NUH'

const toStaffActorFields = (rawUser: Record<string, unknown>) => ({
  currentStaffActorName: optionalString(rawUser.current_staff_actor_name),
  staffActorNameRequired: rawUser.staff_actor_name_required === true,
  staffActorNameUpdatedAt: optionalString(rawUser.staff_actor_name_updated_at),
  staffActorNameUpdatedByUserId: optionalString(rawUser.staff_actor_name_updated_by_user_id),
})

const toAuthIdentity = (rawUser: Record<string, unknown>): AuthIdentity => {
  const backendRole = String(rawUser.role ?? '')
  const subjectId = requiredString(rawUser.id)
  const name = optionalString(rawUser.name)
  const email = optionalString(rawUser.email)

  if (backendRole === 'admin') {
    const adminLevel = rawUser.admin_level === 'master' ? 'master' : 'programme'
    if (adminLevel === 'master') {
      return {
        role: 'master_admin',
        subjectId,
        name,
        email,
        adminLevel,
        programmeScope: toStringArray(rawUser.programme_scope),
        ...toStaffActorFields(rawUser),
      }
    }
    return {
      role: 'programme_pc',
      subjectId,
      name,
      email,
      adminLevel,
      programmeScope: toStringArray(rawUser.programme_scope),
      ...toStaffActorFields(rawUser),
    }
  }

  if (backendRole === 'secretary') {
    return {
      role: 'secretary',
      subjectId,
      name,
      email,
      postingCode: requiredString(rawUser.posting_code),
      ...toStaffActorFields(rawUser),
    }
  }

  if (backendRole === 'external_resident') {
    return {
      role: 'external_resident',
      subjectId,
      name,
      mcr: requiredString(rawUser.mcr),
      homeCluster: toHomeCluster(rawUser.home_cluster),
    }
  }

  return {
    role: 'resident',
    subjectId,
    name,
    mcr: requiredString(rawUser.mcr),
    programmeCode: requiredString(rawUser.programme_code),
  }
}

export const createStoredSession = (response: BackendLoginResponse): StoredAuthSession => ({
  mode: frontendConfig.authMode,
  accessToken: response.access_token,
  tokenType: response.token_type || 'bearer',
  identity: toAuthIdentity(response.user),
  createdAt: new Date().toISOString(),
})

const createSupabaseStoredSession = (
  accessToken: string,
  identity: AuthIdentity,
): StoredAuthSession => ({
  mode: 'supabase',
  accessToken,
  tokenType: 'Bearer',
  identity,
  createdAt: new Date().toISOString(),
})

export { authSessionChangedEvent, clearAuthSession, readStoredAuthSession, saveAuthSession }

export const roleToBackendRole = (role: AppRole): BackendLoginRole => {
  if (role === 'master_admin' || role === 'programme_pc') {
    return 'admin'
  }
  if (role === 'external_resident') {
    return 'external_resident'
  }
  return role
}

const isMataResidentSessionRole = (role: AppRole): role is 'resident' | 'external_resident' =>
  role === 'resident' || role === 'external_resident'

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

export const toSessionRequestHeaders = (session: StoredAuthSession | null): Record<string, string> => {
  if (!session) {
    return {}
  }
  if (frontendConfig.authMode === 'supabase') {
    return session.accessToken
      ? { Authorization: `${session.tokenType || 'bearer'} ${session.accessToken}` }
      : {}
  }
  return toStubIdentityHeaders(session.identity)
}

export const login = async (payload: LoginPayload): Promise<StoredAuthSession> => {
  try {
    const response = await httpClient.post<BackendLoginResponse>('/auth/login', payload)
    return createStoredSession(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const loginResident = (mcr: string, role: 'resident' | 'external_resident' = 'resident') => {
  return login({ role, mcr })
}

export const loginStaffWithSupabase = async (email: string, password: string): Promise<StoredAuthSession> => {
  try {
    const supabaseSession = await signInWithSupabasePassword(email, password)
    const identity = await meFromBearerToken(supabaseSession.accessToken)
    return createSupabaseStoredSession(supabaseSession.accessToken, identity)
  } catch (error) {
    if (error instanceof SupabaseConfigurationError) {
      throw new ApiRequestError(error.message)
    }
    throw toApiRequestError(error)
  }
}

export const loginStaff = (email: string, password: string): Promise<StoredAuthSession> => {
  if (frontendConfig.authMode === 'supabase') {
    return loginStaffWithSupabase(email, password)
  }
  return login({ role: 'staff', email, password })
}

export const meFromBearerToken = async (accessToken: string): Promise<AuthIdentity> => {
  try {
    const response = await httpClient.get<Record<string, unknown>>('/auth/me', {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
    return toAuthIdentity(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const hydrateSupabaseSession = async (): Promise<StoredAuthSession | null> => {
  const supabaseSession = await getCurrentSupabaseSessionToken()
  if (!supabaseSession) {
    return null
  }

  const identity = await meFromBearerToken(supabaseSession.accessToken)
  return createSupabaseStoredSession(supabaseSession.accessToken, identity)
}

export const hydrateMataResidentSession = async (): Promise<StoredAuthSession | null> => {
  if (frontendConfig.authMode !== 'supabase') {
    return null
  }

  const storedSession = readStoredAuthSession()
  if (
    !storedSession ||
    storedSession.mode !== 'supabase' ||
    !isMataResidentSessionRole(storedSession.identity.role) ||
    !storedSession.accessToken
  ) {
    return null
  }

  const identity = await meFromBearerToken(storedSession.accessToken)
  if (!isMataResidentSessionRole(identity.role)) {
    throw new ApiRequestError('Stored MATA resident session resolved to a non-resident identity.')
  }
  return {
    ...storedSession,
    tokenType: 'Bearer',
    identity,
  }
}

export const me = async (session: StoredAuthSession): Promise<AuthIdentity> => {
  try {
    if (frontendConfig.authMode === 'supabase') {
      if (isMataResidentSessionRole(session.identity.role)) {
        return await meFromBearerToken(session.accessToken)
      }

      const supabaseSession = await getCurrentSupabaseSessionToken()
      const accessToken = supabaseSession?.accessToken ?? session.accessToken
      if (!accessToken) {
        throw new ApiRequestError('Missing Supabase access token.')
      }
      return await meFromBearerToken(accessToken)
    }

    const response = await httpClient.get<Record<string, unknown>>('/auth/me', {
      headers: toSessionRequestHeaders(session),
    })
    return toAuthIdentity(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

const toStaffActorNameRequestConfig = (session: StoredAuthSession) => {
  if (frontendConfig.authMode === 'supabase') {
    return undefined
  }
  return { headers: toSessionRequestHeaders(session) }
}

export const updateStaffActorName = async (
  session: StoredAuthSession,
  fullName: string,
): Promise<AuthIdentity> => {
  try {
    const response = await httpClient.post<Record<string, unknown>>(
      '/auth/staff-actor-name',
      { full_name: fullName },
      toStaffActorNameRequestConfig(session),
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
        posting_code: row.postingCode,
      })),
    })
    const resident = (response.data.resident ?? {}) as Record<string, unknown>
    const loginLikeResponse = response.data.access_token && response.data.user
      ? createStoredSession(response.data as unknown as BackendLoginResponse)
      : undefined
    return {
      resident: {
        id: requiredString(resident.id),
        name: requiredString(resident.name),
        mcr: requiredString(resident.mcr),
        homeCluster: toHomeCluster(resident.home_cluster),
        currentNhgPostingCode: requiredString(resident.current_nhg_posting_code),
        status: optionalString(resident.status),
      },
      postingSchedule: response.data.posting_schedule as Array<Record<string, unknown>> | undefined,
      session: loginLikeResponse,
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}
