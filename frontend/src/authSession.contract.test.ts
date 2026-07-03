/// <reference types="node" />

import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

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
const httpSource = read('./api/http.ts')
const authContextSource = read('./context/AuthContext.tsx')
const authContextTypeSource = read('./context/authContext.ts')
const loginPageSource = read('./pages/auth/LoginPage.tsx')
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
assert(
  authApiSource.includes('hydrateMataResidentSession') &&
    authContextSource.includes('hydrateMataResidentSession'),
  'supabase-mode hydration falls back to a stored MATA resident token when no staff Supabase session exists',
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
  authApiSource.includes("if (frontendConfig.authMode === 'supabase' && role === 'external_resident')") &&
    authApiSource.includes('Non-NHG Resident MCR-only sign-in is not available in Supabase mode yet.') &&
    !authApiSource.includes("new ApiRequestError('Resident MCR-only sign-in is not available in Supabase mode yet.')"),
  'supabase mode enables NHG Resident MCR login while keeping Non-NHG Resident login deferred',
)
assert(
  httpSource.includes('readStoredAuthSession') &&
    httpSource.includes("storedSession.identity.role === 'resident'") &&
    httpSource.includes('request.headers.Authorization = `Bearer ${storedSession.accessToken}`'),
  'shared HTTP client attaches stored resident MATA bearer before protected resident API calls',
)
assert(
  httpSource.includes('getCurrentSupabaseAccessToken') &&
    httpSource.includes('const accessToken = await getCurrentSupabaseAccessToken()') &&
    httpSource.includes("request.headers.Authorization = `Bearer ${accessToken}`"),
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
  !authApiSource.includes('user_metadata') &&
    !authContextSource.includes('user_metadata') &&
    !supabaseClientSource.includes('user_metadata'),
  'frontend never derives MATA authorization from Supabase user_metadata',
)
assert(loginPageSource.includes('NHG Resident'), 'login page uses NHG Resident terminology')
assert(loginPageSource.includes('Non-NHG Resident'), 'login page uses Non-NHG Resident terminology')
assert(loginPageSource.includes('Unable to sign in. Check your details and try again.'), 'login page uses generic failure copy')
assert(loginPageSource.includes('loginStaff'), 'staff login is separate from MCR resident login')
assert(
  !loginPageSource.includes('residentSupabaseUnsupported') &&
    !loginPageSource.includes('MCR-only resident sign-in is available in local/demo mode. Supabase staff sessions are enabled here.') &&
    loginPageSource.includes('NHG Resident MCR-only sign-in opens only your own resident routes.'),
  'login page enables NHG Resident MCR login in supabase mode',
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
  !loginPageSource.includes('setResidentRole'),
  'login page does not hide NHG/Non-NHG resident login behind a selected-mode toggle',
)
assert(
  loginPageSource.includes("'resident', 'external_resident'") &&
    loginPageSource.includes("'external_resident', 'resident'") &&
    loginPageSource.includes('loginResident(normalisedMcr, role)'),
  'single resident MCR form supports NHG and registered Non-NHG resident login without a visible mode toggle',
)
assert(authApiSource.includes("role: 'staff'"), 'staff login uses the neutral backend staff login discriminator')
assert(registrationPageSource.includes('registration-confirmation'), 'registration page implements screenshot-only confirmation state')
assert(registrationPageSource.includes('registerNonNhgResident'), 'registration page submits through auth API helper')
assert(registrationPageSource.includes('Continue to login'), 'confirmation continues to login when no session is returned')
assert(!registrationPageSource.includes('auth-draft'), 'Non-NHG registration and confirmation pages do not show DRAFT stamps')
assert(
  !registrationPageSource.includes('listPostingCodes'),
  'public Non-NHG registration page does not call admin posting-code APIs before login',
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
    staffAccountsPageSource.includes('button button-ghost danger staff-account-action-button') &&
    !staffAccountsPageSource.includes('className="button button-secondary" onClick={() => {'),
  'Staff Accounts row actions use aligned admin row button styles',
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
assert(authHeadersSource.includes('getSessionAuthHeaders'), 'demo/header builder can use active session identity')
assert(authHeadersSource.includes("authMode === 'supabase'"), 'auth headers suppress stub/demo identity in supabase mode')
assert(!authHeadersSource.includes(obsoleteIdentityHeaderFallback), 'auth headers do not emit pre-login demo identity headers')
assert(!authHeadersSource.includes("'X-User-Role':"), 'authHeaders does not synthesize raw frontend role headers')
assert(!authContextSource.includes('demoIdentityForRole'), 'local app role does not create implicit authenticated identity')
assert(loginPageSource.includes('logout()'), 'failed login clears stale auth session')
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
    appStateSource.includes('identity.programmeScope.length > 0'),
  'reporting periods auto-load only for Master Admin or scoped PC sessions',
)
assert(
  pcUploadTtfSource.includes('reportingPeriods') && pcUploadTtfSource.includes('reportingPeriodId'),
  'PC upload TTF uses the shared PC-safe reporting-period source',
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
  })) === '/external',
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
  })) === '/external',
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
  ],
  programme_pc: [
    '/pc',
    '/pc/teaching-events',
    '/pc/upload-ttf',
    '/pc/warnings',
    '/pc/config',
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
  ],
} as const

const expectedDefaultPathByRole = {
  master_admin: '/admin',
  programme_pc: '/pc/teaching-events',
  secretary: '/secretary/events',
  resident: '/resident/submissions',
  external_resident: '/external',
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
    allowed: ['/external'],
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
