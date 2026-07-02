import { frontendConfig } from '../config/frontendConfig'
import type { AuthIdentity } from '../types/auth'
import { readStoredAuthSession, toStubIdentityHeaders } from './auth'

export type AdminDemoLevel = 'master' | 'programme'

const defaultAdminDemoLevel: AdminDemoLevel =
  frontendConfig.defaultRole === 'master_admin' ? 'master' : 'programme'

const sessionHeadersFor = (predicate: (identity: AuthIdentity) => boolean): Record<string, string> => {
  if (frontendConfig.authMode === 'supabase') {
    return {}
  }
  const identity = readStoredAuthSession()?.identity
  if (!identity || !predicate(identity)) {
    return {}
  }
  return toStubIdentityHeaders(identity)
}

export const getSessionAuthHeaders = (): Record<string, string> => {
  if (frontendConfig.authMode === 'supabase') {
    return {}
  }
  return toStubIdentityHeaders(readStoredAuthSession()?.identity ?? null)
}

export const buildAdminDemoHeaders = (
  adminId: string,
  adminProgrammes: string[],
  adminLevel: AdminDemoLevel = defaultAdminDemoLevel,
  _actorName?: string,
): Record<string, string> => {
  void adminId
  void adminProgrammes
  void adminLevel
  void _actorName
  const sessionHeaders = sessionHeadersFor((identity) =>
    identity.role === 'master_admin' || identity.role === 'programme_pc',
  )
  if (Object.keys(sessionHeaders).length > 0) {
    return sessionHeaders
  }
  return {}
}

export const buildSecretaryDemoHeaders = (overrides?: {
  secretaryId?: string
  secretarySite?: string
  actorName?: string
}): Record<string, string> => {
  void overrides
  const sessionHeaders = sessionHeadersFor((identity) => identity.role === 'secretary')
  if (Object.keys(sessionHeaders).length > 0) {
    return sessionHeaders
  }
  return {}
}

export const buildResidentDemoHeaders = (overrides?: {
  residentId?: string
  residentProgramme?: string
  residentMcr?: string
}): Record<string, string> => {
  void overrides
  const sessionHeaders = sessionHeadersFor((identity) =>
    identity.role === 'resident' || identity.role === 'external_resident',
  )
  if (Object.keys(sessionHeaders).length > 0) {
    return sessionHeaders
  }
  return {}
}

export const buildExternalResidentDemoHeaders = (overrides?: {
  externalResidentId?: string
  residentMcr?: string
}): Record<string, string> => {
  void overrides
  const sessionHeaders = sessionHeadersFor((identity) => identity.role === 'external_resident')
  if (Object.keys(sessionHeaders).length > 0) {
    return sessionHeaders
  }
  return {}
}
