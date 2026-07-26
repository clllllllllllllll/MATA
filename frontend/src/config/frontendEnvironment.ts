export type FrontendAppEnvironment = 'local' | 'preview' | 'production'
export type FrontendAuthenticationMode = 'stub' | 'demo' | 'supabase'

interface FrontendEnvironmentInput {
  appEnv?: string
  authMode?: string
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
} => {
  const rawAppEnv = input.appEnv?.trim()
  const rawAuthMode = input.authMode?.trim()

  if (options.requireExplicit && !rawAppEnv) {
    throw new Error('A frontend build requires VITE_APP_ENV.')
  }
  if (options.requireExplicit && !rawAuthMode) {
    throw new Error('A frontend build requires VITE_AUTH_MODE.')
  }

  const appEnv = rawAppEnv || 'local'
  const authMode = rawAuthMode || 'stub'
  if (!appEnvironments.has(appEnv as FrontendAppEnvironment)) {
    throw new Error('VITE_APP_ENV is invalid.')
  }
  if (!authenticationModes.has(authMode as FrontendAuthenticationMode)) {
    throw new Error('VITE_AUTH_MODE is invalid.')
  }
  if (!approvedEnvironmentModes.has(`${appEnv}:${authMode}`)) {
    throw new Error('VITE_APP_ENV and VITE_AUTH_MODE are not an approved combination.')
  }

  return {
    appEnv: appEnv as FrontendAppEnvironment,
    authMode: authMode as FrontendAuthenticationMode,
  }
}
