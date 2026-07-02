import type { AppRole } from './app'

export type FrontendAppEnv = 'local' | 'preview' | 'production'
export type AuthMode = 'stub' | 'demo' | 'supabase'

export type AuthIdentity =
  | {
      role: 'master_admin'
      subjectId: string
      name?: string
      email?: string
      adminLevel: 'master'
      programmeScope: string[]
    }
  | {
      role: 'programme_pc'
      subjectId: string
      name?: string
      email?: string
      adminLevel: 'programme'
      programmeScope: string[]
    }
  | {
      role: 'secretary'
      subjectId: string
      name?: string
      email?: string
      postingCode: string
    }
  | {
      role: 'resident'
      subjectId: string
      name?: string
      mcr: string
      programmeCode: string
    }
  | {
      role: 'external_resident'
      subjectId: string
      name?: string
      mcr: string
      homeCluster: 'NUH' | 'SingHealth'
    }

export interface AuthSessionState {
  mode: AuthMode
  identity: AuthIdentity | null
  role: AppRole | null
  isAuthenticated: boolean
}

export interface StoredAuthSession {
  mode: AuthMode
  accessToken: string
  tokenType: string
  identity: AuthIdentity
  createdAt: string
}
