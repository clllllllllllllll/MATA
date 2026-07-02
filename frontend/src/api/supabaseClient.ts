import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js'
import { frontendConfig } from '../config/frontendConfig'

export interface SupabaseSessionToken {
  accessToken: string
  tokenType: 'Bearer'
}

export class SupabaseConfigurationError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'SupabaseConfigurationError'
  }
}

let supabaseClient: SupabaseClient | null = null

const publicSupabaseKey = () => frontendConfig.supabasePublishableKey || frontendConfig.supabaseAnonKey

const assertSupabaseFrontendConfig = () => {
  if (frontendConfig.authMode !== 'supabase') {
    return
  }

  if (!frontendConfig.supabaseUrl || !publicSupabaseKey()) {
    throw new SupabaseConfigurationError(
      'VITE_AUTH_MODE=supabase requires VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY or VITE_SUPABASE_PUBLISHABLE_KEY.',
    )
  }
}

export const getSupabaseClient = (): SupabaseClient => {
  assertSupabaseFrontendConfig()
  if (supabaseClient === null) {
    supabaseClient = createClient(frontendConfig.supabaseUrl, publicSupabaseKey())
  }
  return supabaseClient
}

const toSessionToken = (session: Session | null): SupabaseSessionToken | null => {
  if (!session?.access_token) {
    return null
  }
  return {
    accessToken: session.access_token,
    tokenType: 'Bearer',
  }
}

export const signInWithSupabasePassword = async (
  email: string,
  password: string,
): Promise<SupabaseSessionToken> => {
  const client = getSupabaseClient()
  const { data, error } = await client.auth.signInWithPassword({ email, password })
  if (error) {
    throw error
  }

  const sessionToken = toSessionToken(data.session)
  if (sessionToken) {
    return sessionToken
  }

  const currentSession = await getCurrentSupabaseSessionToken()
  if (!currentSession) {
    throw new Error('Supabase sign-in completed without an access token.')
  }
  return currentSession
}

export const getCurrentSupabaseSessionToken = async (): Promise<SupabaseSessionToken | null> => {
  if (frontendConfig.authMode !== 'supabase') {
    return null
  }

  const { data, error } = await getSupabaseClient().auth.getSession()
  if (error) {
    throw error
  }
  return toSessionToken(data.session)
}

export const getCurrentSupabaseAccessToken = async (): Promise<string | null> => {
  const session = await getCurrentSupabaseSessionToken()
  return session?.accessToken ?? null
}

export const signOutFromSupabase = async () => {
  if (frontendConfig.authMode !== 'supabase') {
    return
  }

  const { error } = await getSupabaseClient().auth.signOut({ scope: 'local' })
  if (error) {
    throw error
  }
}
