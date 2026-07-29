import type { AuthIdentity, StoredAuthSession } from '../types/auth'

export interface BackendAuthSessionResponse {
  user: Record<string, unknown>
  csrf_token: string
  session_refresh_required?: boolean
}

const optionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined

const requiredString = (value: unknown): string => {
  const parsed = optionalString(value)
  if (!parsed) {
    throw new Error('Invalid authentication response.')
  }
  return parsed
}

const toStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value
      .map((item) => optionalString(item))
      .filter((item): item is string => item !== undefined)
  }
  if (typeof value === 'string') {
    return value
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0)
  }
  return []
}

const toStaffActorFields = (rawUser: Record<string, unknown>) => ({
  currentStaffActorName: optionalString(rawUser.current_staff_actor_name),
  staffActorNameRequired: rawUser.staff_actor_name_required === true,
  staffActorNameUpdatedAt: optionalString(rawUser.staff_actor_name_updated_at),
  staffActorNameUpdatedByUserId: optionalString(rawUser.staff_actor_name_updated_by_user_id),
})

export const toAuthIdentity = (rawUser: Record<string, unknown>): AuthIdentity => {
  const backendRole = requiredString(rawUser.role)
  const subjectId = requiredString(rawUser.id)
  const name = optionalString(rawUser.name)
  const email = optionalString(rawUser.email)

  if (backendRole === 'admin') {
    if (rawUser.admin_level !== 'master' && rawUser.admin_level !== 'programme') {
      throw new Error('Invalid authentication response.')
    }
    const programmeScope = toStringArray(rawUser.programme_scope)
    if (rawUser.admin_level === 'master') {
      return {
        role: 'master_admin',
        subjectId,
        name,
        email,
        adminLevel: 'master',
        programmeScope,
        ...toStaffActorFields(rawUser),
      }
    }
    return {
      role: 'programme_pc',
      subjectId,
      name,
      email,
      adminLevel: 'programme',
      programmeScope,
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

  if (backendRole === 'resident') {
    return {
      role: 'resident',
      subjectId,
      name,
      mcr: requiredString(rawUser.mcr),
      programmeCode: requiredString(rawUser.programme_code),
      currentPostingCode: optionalString(rawUser.current_posting_code),
      currentPostingLabel: optionalString(rawUser.current_posting_label),
    }
  }

  if (backendRole === 'external_resident') {
    const homeCluster = rawUser.home_cluster
    if (homeCluster !== 'NUH' && homeCluster !== 'SingHealth') {
      throw new Error('Invalid authentication response.')
    }
    return {
      role: 'external_resident',
      subjectId,
      name,
      mcr: requiredString(rawUser.mcr),
      homeCluster,
      currentPostingCode: optionalString(rawUser.current_posting_code),
      currentPostingLabel: optionalString(rawUser.current_posting_label),
    }
  }

  throw new Error('Invalid authentication response.')
}

export const parseAuthSessionResponse = (value: unknown): StoredAuthSession => {
  if (!value || typeof value !== 'object') {
    throw new Error('Invalid authentication response.')
  }
  const response = value as Record<string, unknown>
  if (!response.user || typeof response.user !== 'object') {
    throw new Error('Invalid authentication response.')
  }
  if (
    response.session_refresh_required !== undefined &&
    typeof response.session_refresh_required !== 'boolean'
  ) {
    throw new Error('Invalid authentication response.')
  }

  return {
    identity: toAuthIdentity(response.user as Record<string, unknown>),
    csrfToken: requiredString(response.csrf_token),
    sessionRefreshRequired: response.session_refresh_required === true,
  }
}
