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
const authContextSource = read('./context/AuthContext.tsx')
const loginPageSource = read('./pages/auth/LoginPage.tsx')
const registrationPageSource = read('./pages/auth/NonNhgRegistrationPage.tsx')
const shellSource = read('./components/AppShell.tsx')
const navigationSource = read('./config/navigation.ts')
const frontendConfigSource = read('./config/frontendConfig.ts')
const authHeadersSource = read('./api/authHeaders.ts')
const appStateSource = read('./context/AppContext.tsx')
const pcTeachingEventsSource = read('./pages/pc/PcTeachingEventsPage.tsx')
const pcUploadTtfSource = read('./pages/pc/PcUploadTtfPage.tsx')
const adminUploadPageSource = read('./pages/admin/AdminUploadPage.tsx')
const adminConfigPageSource = read('./pages/admin/AdminConfigPage.tsx')
const adminLogsPageSource = read('./pages/admin/AdminLogsPage.tsx')
const secretarySchedulePageSource = read('./pages/secretary/SecretaryTeachingSchedulePage.tsx')
const residentSubmissionPageSource = read('./pages/resident/ResidentSubmissionPage.tsx')
const stubPageSource = read('./pages/StubPage.tsx')
const routeGuardsSource = read('./routeGuards.ts')
const routeTracePath = fileURLToPath(new URL('./utils/routeTrace.ts', import.meta.url))
const appSourceLf = appSource.replace(/\r\n/g, '\n')
const obsoleteRolePopoverClass = ['role', 'switcher', 'popover'].join('-')
const obsoleteSwitchCopy = ['SWITCH', 'ROLE'].join(' ')
const obsoleteRoleMutation = ['setRole', '(option.id)'].join('')
const obsoleteRoleSwitcherEnv = ['VITE', 'ENABLE', 'ROLE', 'SWITCHER'].join('_')
const obsoleteRoleSwitcherConfig = ['enable', 'Role', 'Switcher'].join('')
const obsoleteIdentityHeaderFallback = ['dev', 'Identity', 'Headers', 'Enabled'].join('')

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
assert(authApiSource.includes("'/auth/login'"), 'auth API posts to /auth/login')
assert(authApiSource.includes("'/auth/me'"), 'auth API can hydrate from /auth/me')
assert(authApiSource.includes("'/external-residents/register'"), 'auth API registers Non-NHG residents')
assert(loginPageSource.includes('NHG Resident'), 'login page uses NHG Resident terminology')
assert(loginPageSource.includes('Non-NHG Resident'), 'login page uses Non-NHG Resident terminology')
assert(loginPageSource.includes('Unable to sign in. Check your details and try again.'), 'login page uses generic failure copy')
assert(loginPageSource.includes('loginStaff'), 'staff login is separate from MCR resident login')
assert(!loginPageSource.includes('auth-login-grid'), 'login page does not use the three-equal-card layout')
assert(!loginPageSource.includes('auth-login-panel'), 'login page does not render Staff/NHG/Non-NHG as equal cards')
assert(!loginPageSource.includes('auth-draft'), 'login page does not show a DRAFT stamp')
assert(!loginPageSource.includes('auth-footnote'), 'login page does not show environment/demo footer copy')
assert(!loginPageSource.includes('Local/demo build'), 'login page omits local/demo environment copy')
assert(!loginPageSource.includes('Production authentication'), 'login page omits replacement production auth footer copy')
assert(!loginPageSource.includes('auth-tab-list'), 'login page does not show a Resident/Staff segmented toggle')
assert(!loginPageSource.includes('staffLoginRole'), 'login page does not let users choose a staff implementation role')
assert(
  !loginPageSource.includes('Master Admin / Programme PC'),
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
assert(navigationSource.includes("defaultPath: '/pc/teaching-events'"), 'Programme PC default route is teaching events')
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
  'PC upload TTF page derives programme options from the authenticated Programme PC session scope',
)
assert(
  !pcUploadTtfSource.includes('resolvePcProgrammeScope(demoAdminProgrammes'),
  'PC upload TTF page does not derive programme scope from local demo fallback state',
)
assert(
  appStateSource.includes("identity.role === 'master_admin'") &&
    appStateSource.includes("identity.role === 'programme_pc'") &&
    appStateSource.includes('identity.programmeScope.length > 0'),
  'reporting periods auto-load only for Master Admin or scoped Programme PC sessions',
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
  'Programme PC /admin navigation redirects before Master Admin content renders',
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
  'single route decision redirects Programme PC /admin to PC default',
)
assert(
  redirectTarget(getRouteAccessDecision({
    pathname: '/secretary/events',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'programme_pc',
  })) === '/pc/teaching-events',
  'single route decision redirects Programme PC /secretary/events to PC default',
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
  'single route decision redirects authenticated Programme PC away from registration',
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
