import { createContext } from 'react'
import type { LogoutRetryReason } from '../api/logoutReliability'
import type { AuthIdentity, AuthSessionState, StoredAuthSession } from '../types/auth'

export type LogoutStatus = 'none' | 'pending' | 'confirmed'

export interface AuthContextValue {
  authState: AuthSessionState
  identity: AuthIdentity | null
  session: StoredAuthSession | null
  hasExplicitSession: boolean
  isLoading: boolean
  logoutStatus: LogoutStatus
  isLogoutRetrying: boolean
  canRetryLogout: boolean
  logoutRetryCount: number
  logoutRetryReason: LogoutRetryReason | null
  staffActorNameRequired: boolean
  hydrateSession: () => Promise<void>
  beginLoginAttempt: () => number
  isAuthRequestCurrent: (generation: number) => boolean
  clearCurrentAuthRequest: (generation: number) => Promise<boolean>
  loginWithSession: (session: StoredAuthSession, generation: number) => boolean
  updateStaffActorName: (fullName: string) => Promise<AuthIdentity>
  logout: () => Promise<void>
  retryLogout: () => boolean
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
