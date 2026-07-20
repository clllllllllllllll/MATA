/// <reference types="node" />

import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import type { ResidentLoginPayload } from './api/loginPayloads.ts'
import type { StoredAuthSession } from './types/auth.ts'

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const redirectTarget = (decision: { kind: string; to?: string }) =>
  'to' in decision ? decision.to : undefined

const appSource = read('./App.tsx')
const mainSource = read('./main.tsx')
const authApiSource = read('./api/auth.ts')
const loginErrorMessagesSource = read('./api/loginErrorMessages.ts')
const loginPayloadsSource = read('./api/loginPayloads.ts')
const httpSource = read('./api/http.ts')
const authContextSource = read('./context/AuthContext.tsx')
const authContextTypeSource = read('./context/authContext.ts')
const loginPageSource = read('./pages/auth/LoginPage.tsx')
const residentLoginFlowSource = read('./pages/auth/residentLoginFlow.ts')
const registrationPageSource = read('./pages/auth/NonNhgRegistrationPage.tsx')
const shellSource = read('./components/AppShell.tsx')
const navigationSource = read('./config/navigation.ts')
const frontendConfigSource = read('./config/frontendConfig.ts')
const authHeadersSource = read('./api/authHeaders.ts')
const packageSource = read('../package.json')
const envExampleSource = read('../.env.example')
const appStateSource = read('./context/AppContext.tsx')
const pcTeachingEventsSource = read('./pages/pc/PcTeachingEventsPage.tsx')
const pcUploadTtfSource = read('./pages/pc/PcUploadTtfPage.tsx')
const adminUploadPageSource = read('./pages/admin/AdminUploadPage.tsx')
const adminConfigPageSource = read('./pages/admin/AdminConfigPage.tsx')
const adminLogsPageSource = read('./pages/admin/AdminLogsPage.tsx')
const staffAccountsApiPath = fileURLToPath(new URL('./api/staffAccounts.ts', import.meta.url))
const staffAccountsPagePath = fileURLToPath(new URL('./pages/admin/AdminStaffAccountsPage.tsx', import.meta.url))
const staffAccountsPageSource = read('./pages/admin/AdminStaffAccountsPage.tsx')
const adminExternalAttendancePageSource = read('./pages/admin/AdminExternalAttendancePage.tsx')
const secretarySchedulePageSource = read('./pages/secretary/SecretaryTeachingSchedulePage.tsx')
const residentSubmissionPageSource = read('./pages/resident/ResidentSubmissionPage.tsx')
const adminResidentSubmissionsPageSource = read('./pages/admin/AdminResidentSubmissionsPage.tsx')
const stylesSource = read('./index.css')
const stubPageSource = read('./pages/StubPage.tsx')
const routeGuardsSource = read('./routeGuards.ts')
const routeTracePath = fileURLToPath(new URL('./utils/routeTrace.ts', import.meta.url))
const supabaseClientPath = fileURLToPath(new URL('./api/supabaseClient.ts', import.meta.url))
assert(existsSync(supabaseClientPath), 'Supabase browser client module exists')
const supabaseClientSource = read('./api/supabaseClient.ts')
const appSourceLf = appSource.replace(/\r\n/g, '\n')
const stylesSourceLf = stylesSource.replace(/\r\n/g, '\n')
const obsoleteRolePopoverClass = ['role', 'switcher', 'popover'].join('-')
const obsoleteSwitchCopy = ['SWITCH', 'ROLE'].join(' ')
const obsoleteRoleMutation = ['setRole', '(option.id)'].join('')
const obsoleteRoleSwitcherEnv = ['VITE', 'ENABLE', 'ROLE', 'SWITCHER'].join('_')
const obsoleteRoleSwitcherConfig = ['enable', 'Role', 'Switcher'].join('')
const obsoleteIdentityHeaderFallback = ['dev', 'Identity', 'Headers', 'Enabled'].join('')
const obsoleteProgrammePcLabel = ['Programme', 'PC'].join(' ')

const {
  getRouteAccessDecision,
  routeAccessRules,
  shouldRenderRoutes,
  resolveLoginRoute,
  resolveProtectedRoute,
  resolveRootRoute,
} = await import('./routeGuards.ts')

interface RawLoginResponse {
  access_token: string
  token_type: string
  user: Record<string, unknown>
}

type CreateStoredSession = (response: RawLoginResponse) => StoredAuthSession
type SubmitSharedResidentLogin = (options: {
  rawMcr: string
  authenticate: (payload: ResidentLoginPayload) => Promise<StoredAuthSession>
}) => Promise<{ session: StoredAuthSession; redirectPath: string }>
type ParseNonNhgRegistrationOptions = (value: unknown) => {
  institutions: Array<{ code: string; name: string }>
  programmes: Array<{
    programmeCode: string
    programmeName: string
    institutions: Array<{
      institutionCode: string
      available: boolean
      status: 'pending' | 'active'
    }>
  }>
}

const productionAuthModules = await (async () => {
  const moduleServer = await createServer({
    root: fileURLToPath(new URL('../', import.meta.url)),
    configFile: false,
    envFile: false,
    logLevel: 'silent',
    appType: 'custom',
    server: { middlewareMode: true },
  })
  try {
    const [authModule, residentLoginFlowModule] = await Promise.all([
      moduleServer.ssrLoadModule('/src/api/auth.ts'),
      moduleServer.ssrLoadModule('/src/pages/auth/residentLoginFlow.ts'),
    ])
    return {
      createStoredSession: authModule.createStoredSession as CreateStoredSession,
      parseNonNhgRegistrationOptions:
        authModule.parseNonNhgRegistrationOptions as ParseNonNhgRegistrationOptions,
      submitSharedResidentLogin:
        residentLoginFlowModule.submitSharedResidentLogin as SubmitSharedResidentLogin,
    }
  } finally {
    await moduleServer.close()
  }
})()

const rawLoginResponse = (user: Record<string, unknown>): RawLoginResponse => ({
  access_token: 'synthetic-access-token',
  token_type: 'bearer',
  user,
})

const parsedRegistrationOptions = productionAuthModules.parseNonNhgRegistrationOptions({
  institutions: [
    { code: 'TTSH', name: 'TTSH' },
    { code: 'KTPH', name: 'KTPH' },
  ],
  programmes: [
    {
      programme_code: 'GERI',
      programme_name: 'Geriatric Medicine',
      institutions: [
        { institution_code: 'TTSH', available: false, status: 'pending' },
        { institution_code: 'KTPH', available: true, status: 'active' },
      ],
    },
  ],
})
assert(
  JSON.stringify(parsedRegistrationOptions) ===
    JSON.stringify({
      institutions: [
        { code: 'TTSH', name: 'TTSH' },
        { code: 'KTPH', name: 'KTPH' },
      ],
      programmes: [
        {
          programmeCode: 'GERI',
          programmeName: 'Geriatric Medicine',
          institutions: [
            { institutionCode: 'TTSH', available: false, status: 'pending' },
            { institutionCode: 'KTPH', available: true, status: 'active' },
          ],
        },
      ],
    }),
  'Non-NHG registration parses backend mapping availability states',
)
let malformedRegistrationOptionsRejected = false
try {
  productionAuthModules.parseNonNhgRegistrationOptions({
    institutions: [{ code: 'TTSH', name: 'TTSH' }],
    programmes: [
      {
        programme_code: 'GERI',
        programme_name: 'Geriatric Medicine',
        institutions: [
          { institution_code: 'TTSH', available: true, status: 'pending' },
        ],
      },
    ],
  })
} catch (error) {
  malformedRegistrationOptionsRejected =
    error instanceof Error && error.message === 'Malformed registration options response.'
}
assert(
  malformedRegistrationOptionsRejected,
  'Non-NHG registration fails closed on inconsistent backend mapping states',
)
const twentyEightPendingProgrammes = Array.from({ length: 28 }, (_value, index) => ({
  programme_code: `P${String(index + 1).padStart(2, '0')}`,
  programme_name: `Programme ${index + 1}`,
  institutions: [
    { institution_code: 'TTSH', available: false, status: 'pending' },
  ],
}))
const parsedPendingOptions = productionAuthModules.parseNonNhgRegistrationOptions({
  institutions: [{ code: 'TTSH', name: 'TTSH' }],
  programmes: twentyEightPendingProgrammes,
})
assert(
  parsedPendingOptions.programmes.length === 28 &&
    parsedPendingOptions.programmes.every((programme) =>
      programme.institutions.every(
        (mapping) => !mapping.available && mapping.status === 'pending',
      ),
  ),
  'Non-NHG registration parser preserves all 28 pending programmes',
)
const parsedFutureInstitution = productionAuthModules.parseNonNhgRegistrationOptions({
  institutions: [{ code: 'WH', name: 'Woodlands Health' }],
  programmes: [
    {
      programme_code: 'DR',
      programme_name: 'Diagnostic Radiology',
      institutions: [
        { institution_code: 'WH', available: true, status: 'active' },
      ],
    },
  ],
})
assert(
  parsedFutureInstitution.institutions[0]?.code === 'WH' &&
    parsedFutureInstitution.programmes[0]?.institutions[0]?.available === true,
  'Non-NHG registration parser accepts future backend-configured institutions without source changes',
)

const assertInvalidRawLoginResponse = async (
  label: string,
  response: RawLoginResponse,
) => {
  let parsedSession: StoredAuthSession | undefined
  let parserError: unknown
  try {
    parsedSession = productionAuthModules.createStoredSession(response)
  } catch (error) {
    parserError = error
  }

  assert(parsedSession === undefined, `${label} returns no stored session`)
  assert(
    parserError instanceof Error && parserError.message === 'Invalid authentication response.',
    `${label} fails with a generic parser error`,
  )

  let loginResult: { session: StoredAuthSession; redirectPath: string } | undefined
  let loginRejected = false
  try {
    loginResult = await productionAuthModules.submitSharedResidentLogin({
      rawMcr: 'M90001Z',
      authenticate: async () => productionAuthModules.createStoredSession(response),
    })
  } catch {
    loginRejected = true
  }

  assert(loginRejected, `${label} rejects before loginWithSession`)
  assert(loginResult === undefined, `${label} produces no session or resident redirect`)
}

await assertInvalidRawLoginResponse(
  'missing backend role',
  rawLoginResponse({
    id: 'synthetic-missing-role-id',
    mcr: 'M90001Z',
    programme_code: 'GRM',
  }),
)
await assertInvalidRawLoginResponse(
  'unsupported backend role',
  rawLoginResponse({
    id: 'synthetic-unsupported-role-id',
    role: 'unexpected_role',
  }),
)
await assertInvalidRawLoginResponse(
  'empty backend role',
  rawLoginResponse({
    id: 'synthetic-empty-role-id',
    role: '',
  }),
)

const nativeResidentSession = productionAuthModules.createStoredSession(
  rawLoginResponse({
    id: 'synthetic-native-resident-id',
    role: 'resident',
    mcr: 'M90001Z',
    programme_code: 'GRM',
  }),
)
const externalResidentSession = productionAuthModules.createStoredSession(
  rawLoginResponse({
    id: 'synthetic-external-resident-id',
    role: 'external_resident',
    mcr: 'E90002A',
    home_cluster: 'NUH',
  }),
)
const adminSession = productionAuthModules.createStoredSession(
  rawLoginResponse({
    id: 'synthetic-admin-id',
    role: 'admin',
    admin_level: 'programme',
    programme_scope: ['GRM'],
  }),
)
const secretarySession = productionAuthModules.createStoredSession(
  rawLoginResponse({
    id: 'synthetic-secretary-id',
    role: 'secretary',
    posting_code: 'TTSHGerMed',
  }),
)

assert(nativeResidentSession.identity.role === 'resident', 'raw native Resident response parses')
assert(
  externalResidentSession.identity.role === 'external_resident',
  'raw Non-NHG Resident response parses',
)
assert(adminSession.identity.role === 'programme_pc', 'raw admin response parsing is unchanged')
assert(secretarySession.identity.role === 'secretary', 'raw secretary response parsing is unchanged')

assert(appSource.includes('path="/login"'), 'universal /login route is registered outside AppShell')
assert(!appSource.includes('RedirectIfAuthenticated'), '/login redirects authenticated users through the top-level access boundary')
assert(appSource.includes('getRouteAccessDecision'), 'App route gates use the single synchronous route decision function')
assert(Array.isArray(routeAccessRules), 'route guards expose a single route access source of truth')
assert(
  appSourceLf.includes('const AccessControlledRoutes = () =>') &&
    appSourceLf.indexOf('const decision = getRouteAccessDecision') < appSourceLf.indexOf('return (\n    <Routes>') &&
    appSource.includes('return <AppRoutes />'),
  'top-level route access boundary decides before the Routes tree can render',
)
assert(
  !appSource.includes('const protectedElement =') &&
    !appSource.includes('RouteAccessGate') &&
    !appSource.includes('<Route element={<RequireAuth />}>'),
  'protected routes do not rely on lower-tree route element guards as the primary defense',
)
assert(appSource.includes('auth-hydration-screen'), 'auth hydration transition uses a neutral visual surface')
assert(!appSource.includes('auth-card auth-card-compact'), 'auth hydration transition does not reuse login card styling')
assert(!existsSync(routeTracePath), 'temporary route trace utility is removed after diagnostics')
const diagnosticSources = [
  appSource,
  shellSource,
  routeGuardsSource,
  pcUploadTtfSource,
  adminUploadPageSource,
  adminConfigPageSource,
  adminLogsPageSource,
  secretarySchedulePageSource,
  residentSubmissionPageSource,
  stubPageSource,
]
for (const source of diagnosticSources) {
  assert(!source.includes('traceRoute'), 'temporary route trace calls are removed')
  assert(!source.includes('[ROUTE_DECISION]'), 'temporary route decision diagnostics are removed')
  assert(!source.includes('[MOUNT]'), 'temporary route mount diagnostics are removed')
  assert(!source.includes('__MATA_ROUTE_TRACE'), 'temporary global route trace array is removed')
  assert(!source.includes('performance.mark'), 'temporary route performance marks are removed')
}
assert(mainSource.includes('<AuthProvider>'), 'AuthProvider wraps the app')
assert(authContextSource.includes('hydrateSession'), 'auth context hydrates or validates the stored session')
assert(authContextSource.includes('logout'), 'auth context exposes logout')
assert(authContextTypeSource.includes('updateStaffActorName'), 'auth context exposes saved staff actor name updates')
assert(authApiSource.includes("'/auth/login'"), 'auth API posts to /auth/login')
assert(authApiSource.includes("'/auth/me'"), 'auth API can hydrate from /auth/me')
assert(authApiSource.includes("'/auth/staff-actor-name'"), 'auth API can save the current staff actor name')
assert(authApiSource.includes("'/external-residents/register'"), 'auth API registers Non-NHG residents')
assert(packageSource.includes('"@supabase/supabase-js": "2.110.0"'), 'Supabase JS dependency is pinned exactly')
assert(
  supabaseClientSource.includes("from '@supabase/supabase-js'") &&
    supabaseClientSource.includes('createClient('),
  'Supabase client module creates the browser client through @supabase/supabase-js',
)
assert(
  supabaseClientSource.includes('VITE_AUTH_MODE=supabase') &&
    supabaseClientSource.includes('VITE_SUPABASE_URL') &&
    supabaseClientSource.includes('VITE_SUPABASE_ANON_KEY'),
  'Supabase client fails clearly when required public frontend env vars are missing',
)
assert(
  frontendConfigSource.includes('VITE_SUPABASE_PUBLISHABLE_KEY') &&
    envExampleSource.includes('VITE_SUPABASE_PUBLISHABLE_KEY'),
  'frontend Supabase config supports publishable key naming without private backend credential exposure',
)
assert(
  authApiSource.includes('loginStaffWithSupabase') &&
    authApiSource.includes('signInWithSupabasePassword') &&
    authApiSource.includes('meFromBearerToken'),
  'supabase staff login signs in with Supabase then resolves MATA identity through backend /auth/me',
)
const rawAuthMeCallMatches = [
  ...authApiSource.matchAll(/httpClient\.get<Record<string, unknown>>\(AUTH_ME_PATH/g),
]
assert(
  authApiSource.includes("const AUTH_ME_PATH = '/auth/me'") &&
    authApiSource.includes('const requestAuthMe = async') &&
    rawAuthMeCallMatches.length === 1,
  'all frontend /auth/me calls go through the single auth-owned request helper',
)
assert(
  authApiSource.includes('const hasAuthMeCredentials =') &&
    /if \(!hasAuthMeCredentials\(headers\)\) \{[\s\S]*throw new ApiRequestError\('Missing authentication token\.'\)[\s\S]*\}/.test(authApiSource),
  'auth-owned /auth/me helper refuses to call the backend when no token or stub identity headers exist',
)
assert(
  /const supabaseSession = await signInWithSupabasePassword\(email, password\)[\s\S]*await meFromBearerToken\(supabaseSession\.accessToken\)/.test(authApiSource),
  'supabase staff login uses the returned Supabase access_token for the immediate backend /auth/me call',
)
assert(
  /if \(frontendConfig\.authMode === 'supabase'\) \{\s*return loginStaffWithSupabase\(email, password\)\s*\}\s*return login\(\{ role: 'staff', email, password \}\)/.test(authApiSource),
  'supabase staff login bypasses backend /auth/login while stub staff login still uses the neutral backend discriminator',
)
assert(
  authApiSource.includes('STAFF_SUPABASE_BACKEND_AUTH_ERROR') &&
    loginPageSource.includes('STAFF_SUPABASE_BACKEND_AUTH_ERROR'),
  'backend /auth/me failure after successful Supabase sign-in is shown separately from invalid-password failure copy',
)
assert(
  authApiSource.includes('SupabaseConfigurationError') &&
    loginPageSource.includes('VITE_AUTH_MODE=supabase requires'),
  'missing Supabase public env config surfaces a clear frontend login error',
)
assert(
  authApiSource.includes('hydrateSupabaseSession') &&
    authContextSource.includes('hydrateSupabaseSession'),
  'supabase session hydration calls backend /auth/me from the current Supabase browser session',
)
const hydrateSupabaseSessionSource = authApiSource.slice(
  authApiSource.indexOf('export const hydrateSupabaseSession'),
  authApiSource.indexOf('export const hydrateMataResidentSession'),
)
assert(
  hydrateSupabaseSessionSource.includes('if (!supabaseSession)') &&
    hydrateSupabaseSessionSource.indexOf('return null') <
      hydrateSupabaseSessionSource.indexOf('meFromBearerToken'),
  'hydration with no Supabase token returns locally instead of calling /auth/me',
)
assert(
  authApiSource.includes('hydrateMataResidentSession') &&
    authContextSource.includes('hydrateMataResidentSession'),
  'supabase-mode hydration falls back to a stored MATA resident token when no staff Supabase session exists',
)
const hydrateMataResidentSessionSource = authApiSource.slice(
  authApiSource.indexOf('export const hydrateMataResidentSession'),
  authApiSource.indexOf('export const me = async'),
)
assert(
  hydrateMataResidentSessionSource.includes('!storedSession.accessToken') &&
    hydrateMataResidentSessionSource.indexOf('return null') <
      hydrateMataResidentSessionSource.indexOf('meFromBearerToken'),
  'hydration with no stored MATA resident token returns locally instead of calling /auth/me',
)
assert(
  !routeGuardsSource.includes('/auth/me') &&
    !/\bme\s*\(/.test(routeGuardsSource) &&
    !routeGuardsSource.includes('meFromBearerToken') &&
    !routeGuardsSource.includes('hydrateSession'),
  'route guards redirect from local auth state and never call /auth/me without a token',
)
assert(
  !httpSource.includes('X-MATA-Auth-' + 'Debug') &&
    !httpSource.includes(['auth', 'Debug'].join('')) &&
    !httpSource.includes('MATA_AUTH_' + 'DEBUG'),
  'temporary auth debug headers and logs are not part of normal HTTP transport',
)
assert(
  secretarySchedulePageSource.includes('formulaUnsafeCsvPrefix') &&
    secretarySchedulePageSource.includes('value.trimStart()') &&
    secretarySchedulePageSource.includes("`'${value}`") &&
    secretarySchedulePageSource.includes('row.map(quoteCsvCell)'),
  'secretary schedule CSV export neutralizes spreadsheet formula-leading cells before download',
)
assert(
  authApiSource.includes('current_staff_actor_name') &&
    authApiSource.includes('staff_actor_name_required') &&
    authContextSource.includes('staffActorNameRequired'),
  'frontend auth identity carries saved staff actor-name fields from backend /auth/me',
)
assert(
  appSource.includes('StaffActorNameGate') &&
    appSource.includes('Set staff name') &&
    appSource.includes('Save and continue') &&
    appSource.includes('This name will be recorded on actions performed using this shared staff account.'),
  'staff users missing a saved actor name are blocked by the set-staff-name flow',
)
assert(
  shellSource.includes('Staff account settings') &&
    shellSource.includes('Current staff name') &&
    shellSource.includes('updateStaffActorName'),
  'AppShell provides saved staff actor-name settings for staff identities',
)
assert(
  !authApiSource.includes('Non-NHG Resident MCR-only sign-in is not available in Supabase mode yet.') &&
    !authApiSource.includes("if (frontendConfig.authMode === 'supabase' && role === 'external_resident')") &&
    !authApiSource.includes("new ApiRequestError('Resident MCR-only sign-in is not available in Supabase mode yet.')"),
  'supabase mode enables NHG and registered Non-NHG Resident MCR login through the backend',
)
assert(
    httpSource.includes('readStoredAuthSession') &&
    httpSource.includes('isMataResidentSessionRole') &&
    httpSource.includes("role === 'resident' || role === 'external_resident'") &&
    httpSource.includes("setHeaderValue(request.headers, 'Authorization', `Bearer ${storedSession.accessToken}`)"),
  'shared HTTP client attaches stored MATA bearer before protected NHG and Non-NHG resident API calls',
)
assert(
  httpSource.includes('getCurrentSupabaseAccessToken') &&
    httpSource.includes('const accessToken = await getCurrentSupabaseAccessToken()') &&
    httpSource.includes("setHeaderValue(request.headers, 'Authorization', `Bearer ${accessToken}`)"),
  'shared HTTP client attaches the latest Supabase bearer for staff API calls',
)
assert(
  authApiSource.includes('updateStaffActorName') &&
    !/updateStaffActorName[\s\S]*headers:\s*toSessionRequestHeaders\(session\)/.test(authApiSource),
  'staff actor-name update relies on the shared HTTP interceptor instead of a stored session Authorization header',
)
assert(
  httpSource.includes("delete request.headers['X-User-Role']") &&
    httpSource.includes("delete request.headers['X-Admin-Level']"),
  'supabase HTTP transport strips local/demo identity headers before requests leave the frontend',
)
assert(
  authContextSource.includes('signOutFromSupabase') &&
    shellSource.includes('await logout()'),
  'supabase logout signs out of Supabase and clears local app identity before redirect',
)
assert(
  authContextSource.includes('authRequestGenerationRef') &&
    authContextSource.includes('nextAuthRequestGeneration') &&
    authContextSource.includes('isCurrentAuthRequest') &&
    authContextSource.includes('!isCurrentAuthRequest(generation)'),
  'auth context guards hydration state writes so stale /auth/me failures cannot overwrite newer login success',
)
const hydrateSessionSource = authContextSource.slice(
  authContextSource.indexOf('const hydrateSession = useCallback'),
  authContextSource.indexOf('useEffect(() => {'),
)
const initialHydrationEffectSource = authContextSource.slice(
  authContextSource.indexOf('useEffect(() => {'),
  authContextSource.indexOf('useEffect(() => {\n    const onSessionChanged'),
)
assert(
  authContextSource.includes('clearCurrentAuthRequest') &&
    !hydrateSessionSource.includes('signOutFromSupabase') &&
    !initialHydrationEffectSource.includes('signOutFromSupabase'),
  'hydration /auth/me failures clear only local MATA state and cannot fire a stale Supabase logout during a newer login',
)
assert(
  /const logout = useCallback\(async \(\) => \{[\s\S]*nextAuthRequestGeneration\(\)[\s\S]*await signOutFromSupabase\(\)[\s\S]*clearAuthSession\(\)[\s\S]*setSession\(null\)/.test(authContextSource),
  'logout still invalidates in-flight auth requests, clears Supabase, and clears local app session',
)
assert(
  !authApiSource.includes('user_metadata') &&
    !authContextSource.includes('user_metadata') &&
    !supabaseClientSource.includes('user_metadata'),
  'frontend never derives MATA authorization from Supabase user_metadata',
)
assert(loginPageSource.includes('NHG Resident'), 'login page uses NHG Resident terminology')
assert(loginPageSource.includes('Non-NHG Resident'), 'login page uses Non-NHG Resident terminology')
assert(
  loginErrorMessagesSource.includes('Unable to sign in. Check your details and try again.') &&
    loginPageSource.includes('resolveResidentLoginError(loginError)'),
  'mounted resident login maps ordinary failures to generic copy',
)
assert(
  loginErrorMessagesSource.includes('Too many sign-in attempts. Please try again in 1 minute.') &&
    loginPageSource.includes('getRateLimitLoginErrorMessage') &&
    /const getStaffLoginErrorMessage = \(loginError: unknown\) => \{\s*const rateLimitMessage = getRateLimitLoginErrorMessage\(loginError\)[\s\S]*?if \(rateLimitMessage\) \{[\s\S]*?return rateLimitMessage[\s\S]*?STAFF_SUPABASE_BACKEND_AUTH_ERROR/.test(loginPageSource),
  'login page shows a specific too-many-requests message before staff errors fall back to generic or backend-auth copy',
)
assert(
  httpSource.includes('retryAfterSeconds') &&
    httpSource.includes("'retry-after'") &&
    httpSource.includes('parseRetryAfterSeconds'),
  'HTTP error conversion preserves Retry-After seconds for backend login rate-limit feedback',
)
assert(
  loginErrorMessagesSource.includes('isRateLimitError') &&
    loginErrorMessagesSource.includes('getRateLimitLoginErrorMessage') &&
    loginErrorMessagesSource.includes('.status === 429'),
  'login error mapping preserves rate-limit detection and one-minute fallback messaging',
)
assert(
  !loginPageSource.includes('loginOrder') &&
    !loginPageSource.includes('isRateLimitError') &&
    !loginPageSource.includes("startsWith('E')") &&
    !loginPageSource.includes('external_resident') &&
    !residentLoginFlowSource.includes('loginOrder') &&
    !residentLoginFlowSource.includes('catch') &&
    residentLoginFlowSource.includes('const session = await authenticate(payload)') &&
    loginPayloadsSource.includes("role: 'resident'") &&
    !loginPayloadsSource.includes("role: 'external_resident'"),
  'shared resident login sends one neutral request without prefix inference or frontend table probing',
)
assert(loginPageSource.includes('loginStaff'), 'staff login is separate from MCR resident login')
assert(
  !loginPageSource.includes('residentSupabaseUnsupported') &&
    !loginPageSource.includes('MCR-only resident sign-in is available in local/demo mode. Supabase staff sessions are enabled here.') &&
    !loginPageSource.includes('Non-NHG Resident sign-in remains deferred') &&
    loginPageSource.includes('NHG and registered Non-NHG residents use this shared MCR login.'),
  'login page explains the shared NHG and registered Non-NHG Resident MCR login',
)
assert(!loginPageSource.includes('auth-login-grid'), 'login page does not use the three-equal-card layout')
assert(!loginPageSource.includes('auth-login-panel'), 'login page does not render Staff/NHG/Non-NHG as equal cards')
assert(!loginPageSource.includes('auth-draft'), 'login page does not show a DRAFT stamp')
assert(!loginPageSource.includes('auth-footnote'), 'login page does not show environment/demo footer copy')
assert(!loginPageSource.includes('Local/demo build'), 'login page omits local/demo environment copy')
assert(!loginPageSource.includes('Production authentication'), 'login page omits replacement production auth footer copy')
assert(!loginPageSource.includes('auth-tab-list'), 'login page does not show a Resident/Staff segmented toggle')
assert(!loginPageSource.includes('staffLoginRole'), 'login page does not let users choose a staff implementation role')
assert(
  !loginPageSource.includes(`Master Admin / ${obsoleteProgrammePcLabel}`),
  'login page does not expose staff implementation role chooser copy',
)
assert(
  !loginPageSource.includes('auth-resident-role-selector') &&
    !loginPageSource.includes('chooseResidentLoginRole') &&
    !loginPageSource.includes('residentLoginState') &&
    loginPageSource.includes('submitSharedResidentLogin') &&
    registrationPageSource.includes('to="/login"'),
  'registration returns to the same shared Resident MCR form without subtype state or controls',
)
const residentFormStart = loginPageSource.indexOf(
  '<form className="auth-form auth-form-block" onSubmit={submitResidentLogin}>',
)
const residentFormEnd = loginPageSource.indexOf('</form>', residentFormStart)
const residentFormSource = loginPageSource.slice(residentFormStart, residentFormEnd)
assert(
  residentFormStart >= 0 &&
    residentFormEnd > residentFormStart &&
    (residentFormSource.match(/<input/g) ?? []).length === 1 &&
    (residentFormSource.match(/<button/g) ?? []).length === 1 &&
    (residentFormSource.match(/'Continue'/g) ?? []).length === 1 &&
    residentFormSource.includes('MCR number'),
  'shared Resident MCR form renders one MCR input and one Continue button',
)
assert(
  authApiSource.includes("return login({ role: 'staff', email, password })"),
  'staff login uses the unchanged neutral backend staff login discriminator',
)
assert(registrationPageSource.includes('registration-confirmation'), 'registration page implements screenshot-only confirmation state')
assert(registrationPageSource.includes('registerNonNhgResident'), 'registration page submits through auth API helper')
assert(registrationPageSource.includes('Continue to login'), 'confirmation continues to login when no session is returned')
assert(!registrationPageSource.includes('auth-draft'), 'Non-NHG registration and confirmation pages do not show DRAFT stamps')
assert(
  registrationPageSource.includes('Upcoming NHG Postings') &&
    registrationPageSource.includes('postingSchedule') &&
    registrationPageSource.includes('addScheduleRow') &&
    !registrationPageSource.includes('Current NHG posting'),
  'Non-NHG registration uses repeatable upcoming posting schedule rows instead of a single current posting field',
)
assert(
  authApiSource.includes('posting_schedule: payload.postingSchedule.map') &&
    !authApiSource.includes('posting_code: row.postingCode') &&
    !authApiSource.includes('current_nhg_posting_code: payload.currentNhgPostingCode'),
  'Non-NHG registration API sends programme/institution schedule rows without trusting client-entered posting_code',
)
assert(
  !registrationPageSource.includes('postingCode: string') &&
    !registrationPageSource.includes("'postingCode'") &&
    !registrationPageSource.includes('Posting code') &&
    !registrationPageSource.includes('placeholder="e.g. TTSHGerMed"') &&
    !registrationPageSource.includes('Resolved by MATA after submission') &&
    !registrationPageSource.includes('auth-schedule-resolved'),
  'Non-NHG registration form ends schedule rows after programme and institution without editable or placeholder posting UI',
)
assert(
  registrationPageSource.includes('postingResolutionError') &&
    registrationPageSource.includes('Posting configuration') &&
    registrationPageSource.includes('auth-schedule-row-error'),
  'Non-NHG registration shows configuration validation near schedule rows',
)
assert(
  registrationPageSource.includes("error.status === 429") &&
    registrationPageSource.includes('Too many registration attempts. Please try again later.'),
  'Non-NHG registration keeps rate-limit feedback distinct from generic validation errors',
)
assert(
  registrationPageSource.includes('formatSchedulePosting') &&
    registrationPageSource.includes('auth-confirmation-schedule'),
  'Non-NHG registration success recap displays programme/institution schedule details',
)
assert(
  !loginPageSource.includes('auth-register-cta is-disabled') &&
    !loginPageSource.includes('Registration and MCR-only Supabase sessions remain deferred.'),
  'Non-NHG registration CTA remains available in supabase mode',
)
assert(
  !registrationPageSource.includes('listPostingCodes') &&
    registrationPageSource.includes('listNonNhgRegistrationOptions') &&
    !registrationPageSource.includes('const PROGRAMME_OPTIONS') &&
    !registrationPageSource.includes('const INSTITUTION_OPTIONS'),
  'public Non-NHG registration uses backend-supported pairs without admin APIs or a duplicate static matrix',
)
assert(
  registrationPageSource.includes('registrationOptionsLoading') &&
    registrationPageSource.includes('Loading posting options...') &&
    registrationPageSource.includes('REGISTRATION_OPTIONS_ERROR') &&
    registrationPageSource.includes('NO_CONFIGURED_INSTITUTIONS'),
  'Non-NHG registration keeps loading, request-error, and empty-configuration states distinct',
)
assert(
  registrationPageSource.includes('PENDING_MAPPING_MESSAGE') &&
    registrationPageSource.includes('Posting configuration for this programme is pending.') &&
    registrationPageSource.includes('disabled={!mapping.available}') &&
    registrationPageSource.includes('isAvailableScheduleRow'),
  'pending mappings remain visible, unavailable, and unable to satisfy submission validation',
)
assert(
  !registrationPageSource.includes('posting_code') &&
    !registrationPageSource.includes('TTSHGerMed') &&
    !authApiSource.includes("value === 'TTSH'") &&
    !authApiSource.includes("value === 'KTPH'") &&
    !authApiSource.includes("value === 'WH'"),
  'Non-NHG registration UI exposes no posting code and has no institution-specific parser branches',
)
assert(
  navigationSource.includes("id: 'master_admin'") &&
    navigationSource.includes("defaultPath: '/admin'") &&
    loginPageSource.includes('navigate(getRedirectPath(session.identity.role, fromPath), { replace: true })'),
  'successful staff /auth/me response redirects master admins to /admin through the role default path',
)
assert(
  appSource.includes('const AccessControlledRoutes = () =>') &&
    appSource.includes('return <AppRoutes />') &&
    appSource.includes('<NonNhgRegistrationPage />'),
  'authenticated users visiting /register/non-nhg are redirected before the registration page renders',
)
assert(shellSource.includes('logout()'), 'AppShell logout clears auth session')
assert(
  !shellSource.includes('forcedRole') &&
    !shellSource.includes('roleFromPathname(location.pathname)') &&
    !shellSource.includes('setRole(forcedRole)'),
  'AppShell does not derive its displayed role from an unauthorized URL before route guards redirect',
)
assert(!shellSource.includes(obsoleteRolePopoverClass), 'AppShell does not render the obsolete role chooser popover')
assert(!shellSource.includes(obsoleteSwitchCopy), 'AppShell does not render demo role chooser copy')
assert(!shellSource.includes(obsoleteRoleMutation), 'AppShell role display cannot mutate the app role')
assert(!frontendConfigSource.includes(obsoleteRoleSwitcherEnv), 'obsolete role chooser Vite config is removed')
assert(!frontendConfigSource.includes(obsoleteRoleSwitcherConfig), 'obsolete role chooser config flag is removed')
assert(navigationSource.includes("defaultPath: '/pc/teaching-events'"), 'PC default route is teaching events')
assert(
  existsSync(staffAccountsApiPath) &&
    existsSync(staffAccountsPagePath) &&
    appSource.includes('AdminStaffAccountsPage') &&
    routeGuardsSource.includes("'/admin/staff-accounts'") &&
    navigationSource.includes("path: '/admin/staff-accounts'") &&
    navigationSource.includes("label: 'Staff Accounts'"),
  'Master Admin Staff Accounts route, navigation, page, and API client are present',
)
assert(
  navigationSource.indexOf("label: 'Staff Accounts'") <
    navigationSource.indexOf("label: 'Secretary Events'"),
  'Master Admin nav shows Staff Accounts above Secretary Events',
)
assert(
  staffAccountsPageSource.includes("programme_pc: 'PC'") &&
    staffAccountsPageSource.includes('<option value="programme_pc">PC</option>') &&
    staffAccountsPageSource.includes("'PC requires at least one programme.'"),
  'Staff Accounts page displays Programme Coordinator accounts as PC',
)
assert(
  staffAccountsPageSource.includes('staff-account-action-button') &&
    staffAccountsPageSource.includes('className="admin-staff-accounts-table"') &&
    staffAccountsPageSource.includes('className="staff-account-actions"') &&
    staffAccountsPageSource.includes('className="staff-account-actions-primary"') &&
    staffAccountsPageSource.includes('staff-account-reset-button') &&
    staffAccountsPageSource.includes('button button-ghost danger staff-account-action-button') &&
    !staffAccountsPageSource.includes('className="button button-secondary" onClick={() => {'),
  'Staff Accounts row actions use aligned admin row button styles',
)
assert(
  /\.admin-staff-accounts-table \{\n\s+width: 100%;[\s\S]*min-width: 1180px;[\s\S]*table-layout: auto;/.test(stylesSourceLf) &&
    /\.admin-staff-accounts-table th,\n\.admin-staff-accounts-table td \{\n\s+white-space: nowrap;/.test(stylesSourceLf),
  'Staff Accounts desktop table uses page-scoped single-line column layout',
)
assert(
  /\.staff-account-actions \{\n\s+display: inline-grid;[\s\S]*grid-template-columns: minmax\(max-content, 1fr\);/.test(stylesSourceLf) &&
    /\.staff-account-actions-primary \{\n\s+display: grid;[\s\S]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/.test(stylesSourceLf) &&
    /\.staff-account-reset-button \{\n\s+width: 100%;/.test(stylesSourceLf),
  'Staff Accounts reset password action matches the combined top action row width',
)
assert(
  !staffAccountsPageSource.includes('selectedOptions') &&
    !staffAccountsPageSource.includes('multiple') &&
    staffAccountsPageSource.includes("value={formState.programmeScope[0] ?? ''}") &&
    staffAccountsPageSource.includes('event.target.value ? [event.target.value] : []'),
  'Staff Accounts PC programme scope uses one clean dropdown while preserving programme_scope as an array',
)
assert(
  !staffAccountsPageSource.includes('checkbox-row') &&
    staffAccountsPageSource.includes('secretary-toggle-block staff-account-toggle-block') &&
    staffAccountsPageSource.includes('secretary-yes-no') &&
    staffAccountsPageSource.includes("className={formState.isActive ? 'is-active' : ''}") &&
    staffAccountsPageSource.includes("className={!formState.isActive ? 'is-active' : ''}"),
  'Staff Accounts active state uses the Add Teaching yes/no segmented selector',
)
assert(
  /\.admin-staff-accounts-page table tbody td \{\n\s+vertical-align: middle;/.test(stylesSourceLf),
  'Staff Accounts table body cells are vertically centered',
)
for (const source of [
  navigationSource,
  staffAccountsPageSource,
  pcUploadTtfSource,
  pcTeachingEventsSource,
  adminLogsPageSource,
  adminConfigPageSource,
  adminResidentSubmissionsPageSource,
]) {
  assert(!source.includes(obsoleteProgrammePcLabel), 'frontend user-facing copy uses PC terminology')
}
assert(
  adminLogsPageSource.indexOf('title="Admin Logs"') <
    adminLogsPageSource.indexOf('actions={') &&
    adminLogsPageSource.indexOf('actions={') <
      adminLogsPageSource.indexOf('className="card filter-bar warning-filter-card admin-logs-filter-card"') &&
    adminLogsPageSource.indexOf('<IconRefresh size={14} />') <
      adminLogsPageSource.indexOf('className="card filter-bar warning-filter-card admin-logs-filter-card"') &&
    !adminLogsPageSource.includes('className="admin-logs-filter-actions"') &&
    adminLogsPageSource.indexOf('Date to') < adminLogsPageSource.indexOf('className="admin-logs-clear-filter"') &&
    adminLogsPageSource.indexOf('className="admin-logs-clear-filter"') <
      adminLogsPageSource.indexOf('className="admin-logs-advanced-filters"') &&
    /\.admin-logs-filter-main \{\n\s+display: grid;\n\s+grid-template-columns: minmax\(220px, 1\.15fr\) repeat\(5, minmax\(128px, 1fr\)\);[\s\S]*align-items: end;/.test(stylesSourceLf) &&
    /\.admin-logs-clear-filter \{\n\s+display: flex;[\s\S]*align-items: center;[\s\S]*justify-content: flex-start;/.test(stylesSourceLf),
  'Admin Logs refresh is a header action and Clear filters sits inline after Date to in the filter card',
)
assert(
  !adminLogsPageSource.includes('Technical details') &&
    !adminLogsPageSource.includes('technicalDetailFields') &&
    !adminLogsPageSource.includes('admin-log-support-details'),
  'Admin Logs detail omits technical support details from the normal UI',
)
assert(
  !adminLogsPageSource.includes('Immutable evidence') &&
    !adminLogsPageSource.includes('Bounded evidence preview') &&
    !adminLogsPageSource.includes('JsonPreview') &&
    !adminLogsPageSource.includes('immutable_evidence'),
  'Admin Logs detail omits raw immutable evidence and JSON previews from the normal UI',
)
assert(
  !adminLogsPageSource.includes('selectedDetail.related_entities.map') &&
    !adminLogsPageSource.includes('entity.entity_id ?'),
  'Admin Logs detail does not render related entity IDs in the normal UI',
)
assert(
  !adminLogsPageSource.includes('value={activeDetail.reporting_period_id}') &&
    adminLogsPageSource.includes('reportingPeriodLabelForLog'),
  'Admin Logs detail maps reporting_period_id to a readable reporting period label',
)
assert(authHeadersSource.includes('getSessionAuthHeaders'), 'demo/header builder can use active session identity')
assert(authHeadersSource.includes("authMode === 'supabase'"), 'auth headers suppress stub/demo identity in supabase mode')
assert(!authHeadersSource.includes(obsoleteIdentityHeaderFallback), 'auth headers do not emit pre-login demo identity headers')
assert(!authHeadersSource.includes("'X-User-Role':"), 'authHeaders does not synthesize raw frontend role headers')
assert(!authContextSource.includes('demoIdentityForRole'), 'local app role does not create implicit authenticated identity')
const staffLoginSource = loginPageSource.slice(
  loginPageSource.indexOf('const submitStaffLogin'),
  loginPageSource.indexOf('const submitResidentLogin'),
)
const staffLoginPreTrySource = staffLoginSource.slice(0, staffLoginSource.indexOf('try {'))
assert(
  authContextSource.includes('beginLoginAttempt') &&
    staffLoginPreTrySource.includes('beginLoginAttempt()') &&
    !staffLoginPreTrySource.includes('await logout()'),
  'staff login invalidates stale hydration and clears local app state before a new attempt without Supabase logout',
)
assert(
  /if \(submittingForm === 'staff'\) \{\s*return\s*\}/.test(staffLoginSource) &&
    staffLoginSource.includes('isAuthRequestCurrent(loginGeneration)') &&
    staffLoginSource.includes('clearCurrentAuthRequest(loginGeneration, { signOutSupabase: true })') &&
    !staffLoginSource.includes('await logout()') &&
    /catch \(loginError\) \{[\s\S]*if \(!isAuthRequestCurrent\(loginGeneration\)\) \{[\s\S]*return[\s\S]*\}[\s\S]*const clearedCurrentRequest = await clearCurrentAuthRequest\(loginGeneration, \{ signOutSupabase: true \}\)[\s\S]*if \(!clearedCurrentRequest\) \{[\s\S]*return[\s\S]*\}[\s\S]*setError/.test(staffLoginSource),
  'staff login blocks duplicate submissions and uses generation-scoped failure cleanup before error state changes',
)
assert(
  authApiSource.includes('current_posting_code') &&
    authApiSource.includes('current_posting_label') &&
    authApiSource.includes('currentPostingCode') &&
    authApiSource.includes('currentPostingLabel') &&
    shellSource.includes('identity.currentPostingLabel ?? identity.currentPostingCode ??') &&
    shellSource.includes('No current posting'),
  'resident shell scope uses backend-derived current posting display labels before posting-code fallback',
)
assert(
  shellSource.includes("identity?.role === 'resident' || identity?.role === 'external_resident'") &&
    shellSource.includes('identity.mcr') &&
    !shellSource.includes('`${identity.programmeCode} - MCR ${identity.mcr}`') &&
    !shellSource.includes('`${postingScope} - MCR ${identity.mcr}`'),
  'NHG and Non-NHG resident sidebar subtext shows only the raw MCR number and scope omits MCR',
)
assert(
  residentSubmissionPageSource.includes("Submissions are recorded for home-cluster's records only") &&
    !residentSubmissionPageSource.includes('Non-NHG Resident - submissions are stored for home-cluster forwarding only'),
  'Non-NHG submission portal uses the updated forwarding-only copy',
)
assert(
  adminExternalAttendancePageSource.includes('secretary-event-metrics admin-resident-submissions-metrics external-attendance-metrics') &&
    adminExternalAttendancePageSource.includes('resident-submissions-mobile-summary-card') &&
    adminExternalAttendancePageSource.includes('resident-submissions-desktop-metric') &&
    adminExternalAttendancePageSource.indexOf('label="Submitted"') < adminExternalAttendancePageSource.indexOf('label="Flagged"') &&
    adminExternalAttendancePageSource.indexOf('label="Flagged"') < adminExternalAttendancePageSource.indexOf('label="Ad-hoc"') &&
    !adminExternalAttendancePageSource.includes('label="Total"') &&
    !adminExternalAttendancePageSource.includes('grid metrics-grid resident-submissions-metrics') &&
    adminExternalAttendancePageSource.indexOf('external-attendance-filters') < adminExternalAttendancePageSource.indexOf('external-attendance-metrics'),
  'Non-NHG Attendance metrics show Submitted / Flagged / Ad-hoc below filters without a Total card',
)
assert(
  adminExternalAttendancePageSource.includes('card filter-bar admin-resident-submissions-filters external-attendance-filters') &&
    adminExternalAttendancePageSource.includes('admin-secretary-events-filter-actions external-attendance-filter-actions') &&
    adminExternalAttendancePageSource.indexOf('Status') < adminExternalAttendancePageSource.indexOf('Clear filters'),
  'Non-NHG Attendance filters reuse admin filter styling with Clear filters aligned by Status',
)
assert(
  adminExternalAttendancePageSource.includes('<StatusBadge tone="neutral" label={row.homeCluster} />') &&
    !adminExternalAttendancePageSource.includes('<th>Status</th>') &&
    !adminExternalAttendancePageSource.includes('StatusBadge tone={statusTone(row.status)}') &&
    adminExternalAttendancePageSource.includes('admin-resident-submissions-table-card') &&
    adminExternalAttendancePageSource.includes('admin-resident-submissions-table external-attendance-table') &&
    adminExternalAttendancePageSource.includes('secretary-event-title-cell') &&
    adminExternalAttendancePageSource.includes('secretary-event-stack') &&
    adminExternalAttendancePageSource.includes('secretary-event-source-cell'),
  'Non-NHG Attendance table reuses resident submission styling and omits visible Status column/values',
)
assert(
  !adminResidentSubmissionsPageSource.includes('label="Submissions"') &&
    !adminResidentSubmissionsPageSource.includes('<th>Status</th>') &&
    !adminResidentSubmissionsPageSource.includes('<td>\n                      <StatusBadge label={submission.status}') &&
    adminResidentSubmissionsPageSource.indexOf('<th>Teaching</th>') < adminResidentSubmissionsPageSource.indexOf('<th>Session Type</th>') &&
    adminResidentSubmissionsPageSource.indexOf('<th>Session Type</th>') < adminResidentSubmissionsPageSource.indexOf('<th>Posting</th>') &&
    !adminResidentSubmissionsPageSource.includes("{submission.mcr} / {submission.programmeCode ?? '-'}"),
  'NHG Resident Submissions removes Submissions metric/status column, puts Session Type before Posting, and shows resident MCR without programme suffix',
)
assert(
  !pcTeachingEventsSource.includes('listProgrammes'),
  'PC teaching-events page does not call master-admin programme list',
)
assert(
  !pcUploadTtfSource.includes('listProgrammes'),
  'PC upload TTF page does not call master-admin programme list',
)
assert(
  pcUploadTtfSource.includes('useAuth') &&
    pcUploadTtfSource.includes("identity?.role === 'programme_pc'") &&
    pcUploadTtfSource.includes('identity.programmeScope'),
  'PC upload TTF page derives programme options from the authenticated PC session scope',
)
assert(
  !pcUploadTtfSource.includes('resolvePcProgrammeScope(demoAdminProgrammes'),
  'PC upload TTF page does not derive programme scope from local demo fallback state',
)
assert(
  appStateSource.includes("identity.role === 'master_admin'") &&
    appStateSource.includes("identity.role === 'programme_pc'") &&
    appStateSource.includes('identity.programmeScope.length > 0') &&
    appStateSource.includes("identity.role === 'secretary'") &&
    appStateSource.includes('listSecretaryReportingPeriods()'),
  'reporting periods auto-load from role-scoped endpoints for Master Admin, scoped PC, and Secretary sessions',
)
assert(
  pcUploadTtfSource.includes('reportingPeriods') && pcUploadTtfSource.includes('reportingPeriodId'),
  'PC upload TTF uses the shared PC-safe reporting-period source',
)
assert(
  adminConfigPageSource.includes("setFeedback(mutationFeedback('Reporting period updated.'))") &&
    !adminConfigPageSource.includes("setFeedback(mutationFeedback('Reporting period updated.', result))"),
  'Reporting Period update success message stays simple and omits data revalidation details',
)
assert(
  adminUploadPageSource.includes('listProgrammes'),
  'Master Admin upload page still loads the programme catalogue for admin uploads',
)

assert(
  redirectTarget(resolveRootRoute({ isLoading: false, hasExplicitSession: false, role: 'master_admin' })) === '/login',
  'unauthenticated root redirects to login even when a local role exists',
)
assert(
  redirectTarget(resolveProtectedRoute({
    pathname: '/admin',
    isLoading: false,
    hasExplicitSession: false,
    role: 'master_admin',
  })) === '/login',
  'unauthenticated /admin redirects to login before AppShell renders',
)
assert(
  redirectTarget(resolveProtectedRoute({
    pathname: '/pc/teaching-events',
    isLoading: false,
    hasExplicitSession: false,
    role: 'programme_pc',
  })) === '/login',
  'unauthenticated PC route redirects to login before AppShell renders',
)
assert(
  redirectTarget(resolveProtectedRoute({
    pathname: '/admin',
    isLoading: false,
    hasExplicitSession: true,
    role: 'resident',
  })) === '/resident/submissions',
  'resident /admin navigation redirects before admin content renders',
)
assert(
  redirectTarget(resolveProtectedRoute({
    pathname: '/admin',
    isLoading: false,
    hasExplicitSession: true,
    role: 'external_resident',
  })) === '/external/submissions',
  'Non-NHG resident /admin navigation redirects before admin content renders',
)
assert(
  redirectTarget(resolveProtectedRoute({
    pathname: '/admin',
    isLoading: false,
    hasExplicitSession: true,
    role: 'secretary',
  })) === '/secretary/events',
  'secretary /admin navigation redirects before admin content renders',
)
assert(
  redirectTarget(resolveProtectedRoute({
    pathname: '/admin',
    isLoading: false,
    hasExplicitSession: true,
    role: 'programme_pc',
  })) === '/pc/teaching-events',
  'PC /admin navigation redirects before Master Admin content renders',
)
assert(
  resolveProtectedRoute({
    pathname: '/admin',
    isLoading: false,
    hasExplicitSession: true,
    role: 'master_admin',
  }).kind === 'allow',
  'Master Admin session may render /admin',
)
assert(
  resolveLoginRoute({ isLoading: false, hasExplicitSession: false, role: 'master_admin' }).kind === 'allow',
  'local app role alone does not redirect away from /login',
)
assert(
  redirectTarget(resolveLoginRoute({ isLoading: false, hasExplicitSession: true, role: 'secretary' })) === '/secretary/events',
  'authenticated users are redirected away from public auth routes',
)
assert(
  getRouteAccessDecision({
    pathname: '/admin',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: false,
    role: null,
  }).kind === 'redirect_to_login',
  'single route decision redirects logged-out /admin to login',
)
assert(
  getRouteAccessDecision({
    pathname: '/pc/upload-ttf',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: false,
    role: null,
  }).kind === 'redirect_to_login',
  'single route decision redirects logged-out PC upload to login',
)
assert(
  redirectTarget(getRouteAccessDecision({
    pathname: '/admin',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'programme_pc',
  })) === '/pc/teaching-events',
  'single route decision redirects PC /admin to PC default',
)
assert(
  redirectTarget(getRouteAccessDecision({
    pathname: '/secretary/events',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'programme_pc',
  })) === '/pc/teaching-events',
  'single route decision redirects PC /secretary/events to PC default',
)
assert(
  redirectTarget(getRouteAccessDecision({
    pathname: '/pc/upload-ttf',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'secretary',
  })) === '/secretary/events',
  'single route decision redirects Secretary /pc/upload-ttf to Secretary default',
)
assert(
  redirectTarget(getRouteAccessDecision({
    pathname: '/admin',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'resident',
  })) === '/resident/submissions',
  'single route decision redirects NHG Resident /admin to resident default',
)
assert(
  redirectTarget(getRouteAccessDecision({
    pathname: '/resident/submissions',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'external_resident',
  })) === '/external/submissions',
  'single route decision redirects Non-NHG Resident /resident/submissions to Non-NHG default',
)
assert(
  redirectTarget(getRouteAccessDecision({
    pathname: '/login',
    routeKind: 'public_auth',
    isLoading: false,
    hasExplicitSession: true,
    role: 'master_admin',
  })) === '/admin',
  'single route decision redirects authenticated Master Admin away from /login',
)
assert(
  redirectTarget(getRouteAccessDecision({
    pathname: '/register/non-nhg',
    routeKind: 'public_auth',
    isLoading: false,
    hasExplicitSession: true,
    role: 'programme_pc',
  })) === '/pc/teaching-events',
  'single route decision redirects authenticated PC away from registration',
)
assert(
  getRouteAccessDecision({
    pathname: '/admin',
    routeKind: 'protected',
    isLoading: true,
    hasExplicitSession: true,
    role: 'programme_pc',
  }).kind === 'wait_for_auth_hydration',
  'route gate waits during auth hydration instead of rendering protected pages',
)
assert(
  loginPageSource.includes('isPathAllowedForRole(from, role)') &&
    loginPageSource.includes('return defaultPathForRole(role)'),
  'saved login redirect targets are ignored when they are not allowed for the authenticated role',
)

const implementedProtectedRoutesByRole = {
  master_admin: [
    '/admin',
    '/admin/upload',
    '/admin/upload/warnings',
    '/admin/config',
    '/admin/config/multi',
    '/admin/logs',
    '/admin/upload-logs',
    '/admin/parsed-data',
    '/admin/secretary-events',
    '/admin/staff-accounts',
    '/admin/submissions',
    '/admin/external-attendance',
  ],
  programme_pc: [
    '/pc',
    '/pc/teaching-events',
    '/pc/upload-ttf',
    '/pc/warnings',
    '/pc/config',
    '/pc/external-attendance',
  ],
  secretary: [
    '/secretary',
    '/secretary/events',
  ],
  resident: [
    '/resident',
    '/resident/submissions',
    '/resident/attendance',
  ],
  external_resident: [
    '/external',
    '/external/submissions',
    '/external/attendance',
  ],
} as const

const expectedDefaultPathByRole = {
  master_admin: '/admin',
  programme_pc: '/pc/teaching-events',
  secretary: '/secretary/events',
  resident: '/resident/submissions',
  external_resident: '/external/submissions',
} as const

const matrixRoles = Object.keys(implementedProtectedRoutesByRole) as Array<keyof typeof implementedProtectedRoutesByRole>
const allImplementedProtectedPaths = Object.values(implementedProtectedRoutesByRole).flat()
const routeRulePaths = routeAccessRules.map((rule: { path: string }) => rule.path)
const protectedNamespaceSamples = [
  '/admin',
  '/admin/upload',
  '/admin/config',
  '/admin/logs',
  '/admin/anything',
  '/pc',
  '/pc/upload-ttf',
  '/pc/anything',
  '/secretary',
  '/secretary/events',
  '/secretary/anything',
  '/resident',
  '/resident/submissions',
  '/resident/anything',
  '/external',
  '/external/submissions',
  '/external/attendance',
  '/external/anything',
] as const

for (const path of allImplementedProtectedPaths) {
  assert(routeRulePaths.includes(path), `route access matrix covers implemented protected route ${path}`)
  assert(
    getRouteAccessDecision({
      pathname: path,
      routeKind: 'protected',
      isLoading: false,
      hasExplicitSession: false,
      role: null,
    }).kind === 'redirect_to_login',
    `logged-out ${path} redirects to login before any protected route render`,
  )

  for (const role of matrixRoles) {
    const decision = getRouteAccessDecision({
      pathname: path,
      routeKind: 'protected',
      isLoading: false,
      hasExplicitSession: true,
      role,
    })
    if (implementedProtectedRoutesByRole[role].includes(path as never)) {
      assert(decision.kind === 'allow', `${role} may render implemented route ${path}`)
    } else {
      assert(
        decision.kind === 'redirect_to_role_default' &&
          decision.to === expectedDefaultPathByRole[role],
        `${role} is redirected to its own default before ${path} can render`,
      )
    }
  }
}

for (const path of protectedNamespaceSamples) {
  assert(
    getRouteAccessDecision({
      pathname: path,
      routeKind: 'protected',
      isLoading: false,
      hasExplicitSession: false,
      role: null,
    }).kind === 'redirect_to_login',
    `logged-out protected namespace ${path} redirects to login before Routes render`,
  )
}

const namespaceExpectations = [
  {
    role: 'master_admin',
    allowed: ['/admin', '/admin/upload'],
    denied: ['/pc', '/pc/upload-ttf', '/secretary/events', '/resident/submissions', '/external'],
  },
  {
    role: 'programme_pc',
    allowed: ['/pc', '/pc/upload-ttf'],
    denied: ['/admin', '/admin/upload', '/admin/config', '/admin/logs', '/secretary/events', '/resident/submissions', '/external'],
  },
  {
    role: 'secretary',
    allowed: ['/secretary', '/secretary/events'],
    denied: ['/admin', '/admin/upload', '/admin/config', '/pc', '/pc/upload-ttf', '/resident/submissions', '/external'],
  },
  {
    role: 'resident',
    allowed: ['/resident', '/resident/submissions'],
    denied: ['/admin', '/admin/upload', '/admin/anything', '/pc/upload-ttf', '/secretary/events', '/external'],
  },
  {
    role: 'external_resident',
    allowed: ['/external', '/external/submissions', '/external/attendance'],
    denied: ['/admin', '/admin/upload', '/pc/upload-ttf', '/secretary/events', '/resident', '/resident/submissions'],
  },
] as const

for (const expectation of namespaceExpectations) {
  for (const path of expectation.allowed) {
    assert(
      getRouteAccessDecision({
        pathname: path,
        routeKind: 'protected',
        isLoading: false,
        hasExplicitSession: true,
        role: expectation.role,
      }).kind === 'allow',
      `${expectation.role} may render allowed namespace route ${path}`,
    )
  }
  for (const path of expectation.denied) {
    assert(
      redirectTarget(getRouteAccessDecision({
        pathname: path,
        routeKind: 'protected',
        isLoading: false,
        hasExplicitSession: true,
        role: expectation.role,
      })) === expectedDefaultPathByRole[expectation.role],
      `${expectation.role} is redirected away from disallowed namespace route ${path} before Routes render`,
    )
  }
}

for (const publicAuthPath of ['/login', '/register/non-nhg', '/non-nhg/register']) {
  assert(routeRulePaths.includes(publicAuthPath), `route access matrix covers public auth route ${publicAuthPath}`)
  assert(
    getRouteAccessDecision({
      pathname: publicAuthPath,
      routeKind: 'public_auth',
      isLoading: false,
      hasExplicitSession: false,
      role: null,
    }).kind === 'allow',
    `logged-out ${publicAuthPath} may render public auth content or alias redirect`,
  )
  for (const role of matrixRoles) {
    assert(
      redirectTarget(getRouteAccessDecision({
        pathname: publicAuthPath,
        routeKind: 'public_auth',
        isLoading: false,
        hasExplicitSession: true,
        role,
      })) === expectedDefaultPathByRole[role],
      `${role} is redirected away from public auth route ${publicAuthPath} before page render`,
    )
  }
}

for (const role of matrixRoles) {
  assert(
    redirectTarget(getRouteAccessDecision({
      pathname: '/not-implemented',
      routeKind: 'root',
      isLoading: false,
      hasExplicitSession: true,
      role,
    })) === expectedDefaultPathByRole[role],
    `${role} wildcard route redirects to authenticated role default`,
  )
}

assert(
  getRouteAccessDecision({
    pathname: '/not-implemented',
    routeKind: 'root',
    isLoading: false,
    hasExplicitSession: false,
    role: null,
  }).kind === 'redirect_to_login',
  'logged-out wildcard route redirects to login without rendering a protected default page',
)

for (const decision of [
  getRouteAccessDecision({
    pathname: '/admin/upload',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'programme_pc',
  }),
  getRouteAccessDecision({
    pathname: '/pc/upload-ttf',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'master_admin',
  }),
  getRouteAccessDecision({
    pathname: '/admin',
    routeKind: 'protected',
    isLoading: true,
    hasExplicitSession: true,
    role: 'master_admin',
  }),
]) {
  assert(!shouldRenderRoutes(decision), `${decision.kind} decision must not render Routes, AppShell, or page components`)
}

assert(
  shouldRenderRoutes(getRouteAccessDecision({
    pathname: '/admin',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'master_admin',
  })),
  'allowed route decision may render the Routes tree',
)

const roleForPath = (pathname: string): string | null => {
  if (pathname.startsWith('/secretary')) return 'secretary'
  if (pathname.startsWith('/resident')) return 'resident'
  if (pathname.startsWith('/external')) return 'external_resident'
  if (pathname.startsWith('/pc')) return 'programme_pc'
  if (pathname.startsWith('/admin')) return 'master_admin'
  return null
}

const navItemPattern = /path: '([^']+)'[\s\S]*?roles: \[([^\]]+)\]/g
const navItemMatches = [...navigationSource.matchAll(navItemPattern)]
assert(navItemMatches.length > 0, 'navigation items are discoverable for role-route contract checks')
for (const match of navItemMatches) {
  const path = match[1]
  const roles = [...match[2].matchAll(/'([^']+)'/g)].map((roleMatch) => roleMatch[1])
  for (const role of roles) {
    assert(roleForPath(path) === null || roleForPath(path) === role, `navigation item ${path} must be allowed for role ${role}`)
  }
}
