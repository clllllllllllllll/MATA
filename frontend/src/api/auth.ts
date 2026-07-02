import { frontendConfig } from '../config/frontendConfig'
import type { AppRole } from '../types/app'
import type { AuthIdentity, StoredAuthSession } from '../types/auth'
import { ApiRequestError, httpClient, toApiRequestError } from './http'
import {
  getCurrentSupabaseSessionToken,
  signInWithSupabasePassword,
  SupabaseConfigurationError,
} from './supabaseClient'

const AUTH_SESSION_KEY = 'mata.auth.session.v1'
const AUTH_SESSION_CHANGED_EVENT = 'mata-auth-session-change'

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
  currentNhgPostingCode: string
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
  postingHistory?: Record<string, unknown>
  session?: StoredAuthSession
}

const isBrowser = () => typeof window !== 'undefined'

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
      }
    }
    return {
      role: 'programme_pc',
      subjectId,
      name,
      email,
      adminLevel,
      programmeScope: toStringArray(rawUser.programme_scope),
    }
  }

  if (backendRole === 'secretary') {
    return {
      role: 'secretary',
      subjectId,
      name,
      email,
      postingCode: requiredString(rawUser.posting_code),
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

const notifySessionChanged = () => {
  if (isBrowser()) {
    window.dispatchEvent(new Event(AUTH_SESSION_CHANGED_EVENT))
  }
}

export const authSessionChangedEvent = AUTH_SESSION_CHANGED_EVENT

export const readStoredAuthSession = (): StoredAuthSession | null => {
  if (!isBrowser()) {
    return null
  }
  const rawValue = window.sessionStorage.getItem(AUTH_SESSION_KEY)
  if (!rawValue) {
    return null
  }
  try {
    const parsed = JSON.parse(rawValue) as StoredAuthSession
    if (!parsed?.identity?.role || !parsed.accessToken) {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export const saveAuthSession = (session: StoredAuthSession) => {
  if (isBrowser()) {
    window.sessionStorage.setItem(AUTH_SESSION_KEY, JSON.stringify(session))
  }
  notifySessionChanged()
}

export const clearAuthSession = () => {
  if (isBrowser()) {
    window.sessionStorage.removeItem(AUTH_SESSION_KEY)
  }
  notifySessionChanged()
}

export const roleToBackendRole = (role: AppRole): BackendLoginRole => {
  if (role === 'master_admin' || role === 'programme_pc') {
    return 'admin'
  }
  if (role === 'external_resident') {
    return 'external_resident'
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
  if (frontendConfig.authMode === 'supabase') {
    throw new ApiRequestError('Resident MCR-only sign-in is not available in Supabase mode yet.')
  }
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

export const me = async (session: StoredAuthSession): Promise<AuthIdentity> => {
  try {
    if (frontendConfig.authMode === 'supabase') {
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

export const registerNonNhgResident = async (
  payload: NonNhgRegistrationPayload,
): Promise<NonNhgRegistrationResult> => {
  try {
    const response = await httpClient.post<Record<string, unknown>>('/external-residents/register', {
      name: payload.name,
      mcr: payload.mcr,
      home_cluster: payload.homeCluster,
      current_nhg_posting_code: payload.currentNhgPostingCode,
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
      postingHistory: response.data.posting_history as Record<string, unknown> | undefined,
      session: loginLikeResponse,
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}
