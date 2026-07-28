import type { AuthIdentity } from '../types/auth'

const normalizedScope = (values: readonly string[]): string[] =>
  Array.from(
    new Set(
      values
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ).sort()

export const protectedRouteAuthorityKey = (identity: AuthIdentity | null): string => {
  if (!identity) {
    return 'unauthenticated'
  }

  const base = [identity.role, identity.subjectId]

  if (identity.role === 'master_admin' || identity.role === 'programme_pc') {
    return JSON.stringify([...base, ...normalizedScope(identity.programmeScope)])
  }
  if (identity.role === 'secretary') {
    return JSON.stringify([...base, identity.postingCode])
  }
  if (identity.role === 'resident') {
    return JSON.stringify([
      ...base,
      identity.programmeCode,
      identity.currentPostingCode ?? '',
    ])
  }
  return JSON.stringify([
    ...base,
    identity.homeCluster,
    identity.currentPostingCode ?? '',
  ])
}
