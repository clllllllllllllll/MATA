import type { AppRole } from './app'

export type FrontendAppEnv = 'local' | 'preview' | 'production'
export type AuthMode = 'stub' | 'demo' | 'supabase'

interface StaffActorIdentityFields {
  currentStaffActorName?: string
  staffActorNameRequired: boolean
  staffActorNameUpdatedAt?: string
  staffActorNameUpdatedByUserId?: string
}

export type AuthIdentity =
  | {
      role: 'master_admin'
      subjectId: string
      name?: string
      email?: string
      adminLevel: 'master'
      programmeScope: string[]
    } & StaffActorIdentityFields
  | {
      role: 'programme_pc'
      subjectId: string
      name?: string
      email?: string
      adminLevel: 'programme'
      programmeScope: string[]
    } & StaffActorIdentityFields
  | {
      role: 'secretary'
      subjectId: string
      name?: string
      email?: string
      postingCode: string
    } & StaffActorIdentityFields
  | {
      role: 'resident'
      subjectId: string
      name?: string
      mcr: string
      programmeCode: string
      currentPostingCode?: string
      currentPostingLabel?: string
    }
  | {
      role: 'external_resident'
      subjectId: string
      name?: string
      mcr: string
      homeCluster: 'NUH' | 'SingHealth'
      currentPostingCode?: string
      currentPostingLabel?: string
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
