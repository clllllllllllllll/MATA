import type { AppRole } from './app'

export type FrontendAppEnv = 'local' | 'preview' | 'production'
export type AuthMode = 'stub' | 'demo' | 'supabase'

export type AuthIdentity =
  | {
      role: 'master_admin'
      subjectId: string
      adminLevel: 'master'
      programmeScope: string[]
    }
  | {
      role: 'programme_pc'
      subjectId: string
      adminLevel: 'programme'
      programmeScope: string[]
    }
  | {
      role: 'secretary'
      subjectId: string
      postingCode: string
    }
  | {
      role: 'resident'
      subjectId: string
      mcr: string
      programmeCode: string
    }
  | {
      role: 'external_resident'
      subjectId: string
      mcr: string
      homeCluster: 'NUH' | 'SingHealth'
    }

export interface AuthSessionState {
  mode: AuthMode
  identity: AuthIdentity | null
  role: AppRole | null
  isAuthenticated: boolean
}
