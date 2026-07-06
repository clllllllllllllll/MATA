import { createContext } from 'react'
import type { AuthIdentity, AuthSessionState, StoredAuthSession } from '../types/auth'

export interface AuthContextValue {
  authState: AuthSessionState
  identity: AuthIdentity | null
  session: StoredAuthSession | null
  hasExplicitSession: boolean
  isLoading: boolean
  staffActorNameRequired: boolean
  hydrateSession: () => Promise<void>
  beginLoginAttempt: () => number
  isAuthRequestCurrent: (generation: number) => boolean
  clearCurrentAuthRequest: (generation: number, options?: { signOutSupabase?: boolean }) => Promise<boolean>
  loginWithSession: (session: StoredAuthSession) => void
  updateStaffActorName: (fullName: string) => Promise<AuthIdentity>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
