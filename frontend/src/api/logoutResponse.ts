export type LogoutAuthSessionResult = 'confirmed' | 'unconfirmed' | 'stale'

export const parseLogoutAuthSessionResponse = (
  value: unknown,
): Exclude<LogoutAuthSessionResult, 'stale'> => {
  if (
    !value
    || typeof value !== 'object'
    || (value as Record<string, unknown>).success !== true
    || typeof (value as Record<string, unknown>).server_logout_confirmed !== 'boolean'
  ) {
    throw new Error('Malformed logout response.')
  }
  return (value as Record<string, unknown>).server_logout_confirmed
    ? 'confirmed'
    : 'unconfirmed'
}
