import { createContext } from 'react'
import type { AuthIdentity, AuthSessionState, StoredAuthSession } from '../types/auth'

export interface AuthContextValue {
  authState: AuthSessionState
  identity: AuthIdentity | null
  session: StoredAuthSession | null
  hasExplicitSession: boolean
  isLoading: boolean
  hydrateSession: () => Promise<void>
  loginWithSession: (session: StoredAuthSession) => void
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
