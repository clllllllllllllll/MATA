import {
  captureAuthSessionFence,
  isAuthSessionFenceCurrent,
  type AuthSessionFence,
} from '../api/authSessionStore'

export type ProtectedAsyncRequestFence = {
  authSessionFence: AuthSessionFence
  requestId: number
  scopeKey: string
}

export const captureProtectedAsyncRequestFence = (
  scopeKey: string,
  requestId: number,
): ProtectedAsyncRequestFence | null => {
  const authSessionFence = captureAuthSessionFence()
  return authSessionFence
    ? { authSessionFence, requestId, scopeKey }
    : null
}

export const isProtectedAsyncRequestFenceCurrent = (
  fence: ProtectedAsyncRequestFence | null,
  currentScopeKey: string,
  currentRequestId: number,
): boolean => {
  if (!fence) {
    return false
  }
  return fence.scopeKey === currentScopeKey
    && fence.requestId === currentRequestId
    && isAuthSessionFenceCurrent(fence.authSessionFence)
}
