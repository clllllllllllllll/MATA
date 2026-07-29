export type FrontendAppEnvironment = 'local' | 'preview' | 'production'
export type FrontendAuthenticationMode = 'stub' | 'demo' | 'supabase'

interface FrontendEnvironmentInput {
  appEnv?: string
  authMode?: string
  apiBaseUrl?: string
}

interface FrontendEnvironmentOptions {
  requireExplicit?: boolean
}

const appEnvironments = new Set<FrontendAppEnvironment>([
  'local',
  'preview',
  'production',
])
const authenticationModes = new Set<FrontendAuthenticationMode>([
  'stub',
  'demo',
  'supabase',
])
const approvedEnvironmentModes = new Set([
  'local:stub',
  'preview:demo',
  'preview:supabase',
  'production:supabase',
])

export const validateFrontendEnvironment = (
  input: FrontendEnvironmentInput,
  options: FrontendEnvironmentOptions = {},
): {
  appEnv: FrontendAppEnvironment
  authMode: FrontendAuthenticationMode
  apiBaseUrl: string
} => {
  const rawAppEnv = input.appEnv?.trim()
  const rawAuthMode = input.authMode?.trim()
  const rawApiBaseUrl = input.apiBaseUrl?.trim()

  if (options.requireExplicit && !rawAppEnv) {
    throw new Error('A frontend build requires VITE_APP_ENV.')
  }
  if (options.requireExplicit && !rawAuthMode) {
    throw new Error('A frontend build requires VITE_AUTH_MODE.')
  }
  if (options.requireExplicit && !rawApiBaseUrl) {
    throw new Error('A frontend build requires VITE_API_BASE_URL.')
  }

  const appEnv = rawAppEnv || 'local'
  const authMode = rawAuthMode || 'stub'
  const apiBaseUrl = rawApiBaseUrl || '/api/v1'
  if (!appEnvironments.has(appEnv as FrontendAppEnvironment)) {
    throw new Error('VITE_APP_ENV is invalid.')
  }
  if (!authenticationModes.has(authMode as FrontendAuthenticationMode)) {
    throw new Error('VITE_AUTH_MODE is invalid.')
  }
  if (!approvedEnvironmentModes.has(`${appEnv}:${authMode}`)) {
    throw new Error('VITE_APP_ENV and VITE_AUTH_MODE are not an approved combination.')
  }
  if (
    (appEnv === 'production' || authMode === 'supabase') &&
    apiBaseUrl !== '/api/v1'
  ) {
    throw new Error(
      'Production and Supabase frontend builds require VITE_API_BASE_URL=/api/v1.',
    )
  }

  return {
    appEnv: appEnv as FrontendAppEnvironment,
    authMode: authMode as FrontendAuthenticationMode,
    apiBaseUrl,
  }
}
