/// <reference types="node" />

import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import {
  parseAuthSessionResponse,
  type BackendAuthSessionResponse,
} from './api/authSessionResponse.ts'
import {
  clearAuthSession,
  readAuthSessionRevision,
  readStoredAuthSession,
  saveAuthSession,
} from './api/authSessionStore.ts'
import {
  CSRF_HEADER_NAME,
  csrfHeadersForRequest,
  isUnsafeRequestMethod,
} from './api/httpTransport.ts'
import {
  defaultPathForGuardRole,
  getRouteAccessDecision,
  routeAccessRules,
} from './routeGuards.ts'
import type { AppRole } from './types/app.ts'
import type { StoredAuthSession } from './types/auth.ts'

const frontendRoot = fileURLToPath(new URL('../', import.meta.url))
const srcRoot = fileURLToPath(new URL('./', import.meta.url))
const read = (relativePath: string) => readFileSync(join(frontendRoot, relativePath), 'utf8')

const productionSourceFiles = (directory: string): string[] =>
  readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) {
      return productionSourceFiles(path)
    }
    if (!entry.isFile() || entry.name.endsWith('.contract.test.ts')) {
      return []
    }
    return /\.(?:ts|tsx|css)$/.test(entry.name) ? [path] : []
  })

const productionSources = productionSourceFiles(srcRoot).map((path) => ({
  path,
  source: readFileSync(path, 'utf8'),
}))

const sessionResponse = (
  user: BackendAuthSessionResponse['user'],
  csrfToken = 'synthetic-csrf-token',
  sessionRefreshRequired = false,
): BackendAuthSessionResponse => ({
  user,
  csrf_token: csrfToken,
  session_refresh_required: sessionRefreshRequired,
})

const roleUsers: Record<AppRole, BackendAuthSessionResponse['user']> = {
  master_admin: {
    id: 'master-id',
    role: 'admin',
    admin_level: 'master',
    programme_scope: [],
    current_staff_actor_name: 'Master Actor',
    staff_actor_name_required: false,
  },
  programme_pc: {
    id: 'pc-id',
    role: 'admin',
    admin_level: 'programme',
    programme_scope: ['GRM'],
    staff_actor_name_required: true,
  },
  secretary: {
    id: 'secretary-id',
    role: 'secretary',
    posting_code: 'TTSHGerMed',
    staff_actor_name_required: false,
  },
  resident: {
    id: 'resident-id',
    role: 'resident',
    mcr: 'M90001Z',
    programme_code: 'GRM',
    current_posting_code: 'TTSHGerMed',
  },
  external_resident: {
    id: 'external-id',
    role: 'external_resident',
    mcr: 'E90001Z',
    home_cluster: 'NUH',
    current_posting_code: 'TTSHGerMed',
  },
}

test('the shared backend session response hydrates all five identities and CSRF state', () => {
  for (const role of Object.keys(roleUsers) as AppRole[]) {
    const parsed = parseAuthSessionResponse(
      sessionResponse(roleUsers[role], `csrf-for-${role}`, role === 'secretary'),
    )
    assert.equal(parsed.identity.role, role)
    assert.equal(parsed.csrfToken, `csrf-for-${role}`)
    assert.equal(parsed.sessionRefreshRequired, role === 'secretary')
  }
})

test('session response parsing fails closed without a user, CSRF token, or valid identity shape', () => {
  assert.throws(() => parseAuthSessionResponse({ user: roleUsers.resident }))
  assert.throws(() => parseAuthSessionResponse({ csrf_token: 'csrf-only' }))
  assert.throws(() =>
    parseAuthSessionResponse(sessionResponse({
      id: 'bad-pc',
      role: 'admin',
      admin_level: 'unexpected',
      programme_scope: ['GRM'],
    })),
  )
  assert.throws(() =>
    parseAuthSessionResponse(sessionResponse({
      id: 'bad-external',
      role: 'external_resident',
      mcr: 'E90001Z',
      home_cluster: 'Unknown',
    })),
  )
})

test('auth session state is module memory only and clears identity with CSRF state together', () => {
  const startingRevision = readAuthSessionRevision()
  clearAuthSession()
  assert.equal(readStoredAuthSession(), null)
  assert.equal(readAuthSessionRevision(), startingRevision + 1)

  const session = parseAuthSessionResponse(sessionResponse(roleUsers.resident))
  saveAuthSession(session)
  assert.deepEqual(readStoredAuthSession(), session)
  assert.equal(readAuthSessionRevision(), startingRevision + 2)

  clearAuthSession()
  assert.equal(readStoredAuthSession(), null)
  assert.equal(readAuthSessionRevision(), startingRevision + 3)
})

test('the synchronizer header is emitted for exactly the four unsafe methods', () => {
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    assert.equal(isUnsafeRequestMethod(method), true)
    assert.deepEqual(csrfHeadersForRequest(method, 'csrf-value'), {
      [CSRF_HEADER_NAME]: 'csrf-value',
    })
  }

  for (const method of ['GET', 'HEAD', 'OPTIONS', 'TRACE', undefined]) {
    assert.equal(isUnsafeRequestMethod(method), false)
    assert.deepEqual(csrfHeadersForRequest(method, 'csrf-value'), {})
  }
  assert.deepEqual(csrfHeadersForRequest('POST', undefined), {})
  assert.deepEqual(csrfHeadersForRequest('POST', '  '), {})
})

test('production frontend source has no browser credential persistence or bearer auth path', () => {
  const browserSessionStore = ['session', 'Storage'].join('')
  const browserLocalStore = ['local', 'Storage'].join('')
  const bearerHeader = new RegExp(
    ['Author', 'ization', '.{0,80}', 'Bear', 'er'].join(''),
    'is',
  )
  const browserAuthSessionRead = new RegExp(['get', 'Session', '\\s*\\('].join(''))
  const credentialStorage = new RegExp(
    `(?:access|refresh|auth|session).{0,100}(?:${browserSessionStore}|${browserLocalStore})|(?:${browserSessionStore}|${browserLocalStore}).{0,100}(?:access|refresh|auth|session)`,
    'is',
  )

  for (const { path, source } of productionSources) {
    assert.equal(credentialStorage.test(source), false, `credential storage found in ${path}`)
    assert.equal(bearerHeader.test(source), false, `bearer injection found in ${path}`)
    assert.equal(browserAuthSessionRead.test(source), false, `browser auth session lookup found in ${path}`)
  }

  assert.equal(
    existsSync(join(srcRoot, 'api', ['supabase', 'Client.ts'].join(''))),
    false,
  )
  assert.equal(read('package.json').includes(['@supabase', 'supabase-js'].join('/')), false)
})

test('frontend source has no direct Supabase data calls or backend-only Vite secrets', () => {
  const dataApiPatterns = [
    /supabase\s*\.\s*from\s*\(/,
    /supabase\s*\.\s*rpc\s*\(/,
    /\/rest\/v1\//,
    /\/graphql\/v1/,
  ]
  const forbiddenSegments = [
    ['SERVICE', 'ROLE'].join('_'),
    ['SESSION', 'HASH'].join('_'),
    ['RESIDENT', 'SESSION'].join('_'),
    ['DATABASE', 'URL'].join('_'),
    ['SYNC', 'DATABASE', 'URL'].join('_'),
    ['PRIVATE', 'KEY'].join('_'),
    ['DB', 'PASSWORD'].join('_'),
    ['RATE', 'LIMIT', 'HASH'].join('_'),
    ['JWT', 'SECRET'].join('_'),
    ['SECRET', 'KEY'].join('_'),
  ]
  const forbiddenViteName = new RegExp(
    `VITE_[A-Z0-9_]*(?:${forbiddenSegments.join('|')})`,
  )

  for (const { path, source } of productionSources) {
    for (const pattern of dataApiPatterns) {
      assert.equal(pattern.test(source), false, `direct data API call found in ${path}`)
    }
    assert.equal(forbiddenViteName.test(source), false, `backend-only Vite variable found in ${path}`)
  }

  const frontendConfigSource = read('src/config/frontendConfig.ts')
  const dockerfileSource = read('Dockerfile')
  const obsoleteBrowserPrefix = ['VITE', 'SUPABASE', ''].join('_')
  assert.equal(frontendConfigSource.includes(obsoleteBrowserPrefix), false)
  assert.equal(dockerfileSource.includes(obsoleteBrowserPrefix), false)
})

test('the Axios transport sends cookies, attaches CSRF centrally, and ignores stale 401 responses', () => {
  const httpSource = read('src/api/http.ts')
  assert.match(httpSource, /withCredentials:\s*true/)
  assert.match(
    httpSource,
    /applySessionRequestHeaders\(request\.headers,[\s\S]*csrfToken: storedSession\?\.csrfToken/,
  )
  assert.match(
    httpSource,
    /shouldClearSessionForUnauthorized\([\s\S]*authSessionRevision,[\s\S]*readAuthSessionRevision\(\)[\s\S]*clearAuthSession\(\)/,
  )
  assert.doesNotMatch(httpSource, /setHeaderValue\([^\n]+Bearer/)
})

test('login, hydration, rotation, logout, and staff actor updates use backend session APIs', () => {
  const authSource = read('src/api/authCookie.ts')
  const contextSource = read('src/context/AuthContext.tsx')

  assert.match(authSource, /post<unknown>\('\/auth\/login', payload\)/)
  assert.match(authSource, /get<unknown>\('\/auth\/me'/)
  assert.match(authSource, /post<unknown>\('\/auth\/session\/refresh'\)/)
  assert.match(authSource, /post\('\/auth\/logout'\)/)
  assert.match(authSource, /parseAuthSessionResponse\(response\.data\)/)
  assert.match(authSource, /parseLoginOrHydrationResponse\(response\.data\)/)
  assert.match(authSource, /'\/auth\/staff-actor-name'/)
  assert.match(
    contextSource,
    /sessionRefreshRequired[\s\S]*saveAuthSession\(hydratedSession\)[\s\S]*refreshAuthSession\(\)/,
  )
  assert.match(
    contextSource,
    /readAuthSessionRevision\(\) !== expectedSessionRevision[\s\S]*return null/,
  )
  assert.match(
    contextSource,
    /stagedSessionRevision = readAuthSessionRevision\(\)[\s\S]*readAuthSessionRevision\(\) === stagedSessionRevision/,
  )

  const logoutBody = contextSource.slice(
    contextSource.indexOf('const logout = useCallback'),
    contextSource.indexOf('const updateStaffActorName'),
  )
  assert.ok(logoutBody.indexOf('await logoutAuthSession()') < logoutBody.indexOf('clearLocalAuthState()'))
  assert.match(logoutBody, /finally\s*{[\s\S]*clearLocalAuthState\(\)/)
  assert.match(contextSource, /const hydratedSession = await hydrateAuthSession\(\)/)
  assert.match(contextSource, /identity: updatedIdentity/)
})

test('production API requests are forced through the relative same-origin proxy', () => {
  const configSource = read('src/config/frontendConfig.ts')
  const environmentSource = read('src/config/frontendEnvironment.ts')
  const viteSource = read('vite.config.ts')
  const vercel = JSON.parse(read('vercel.json')) as {
    rewrites: Array<{ source: string; destination: string }>
  }

  assert.match(
    configSource,
    /appEnv === 'production'[\s\S]*\? '\/api\/v1'/,
  )
  assert.match(environmentSource, /frontend build requires VITE_APP_ENV/)
  assert.match(environmentSource, /frontend build requires VITE_AUTH_MODE/)
  assert.match(environmentSource, /approvedEnvironmentModes/)
  assert.match(environmentSource, /'production:supabase'/)
  assert.match(viteSource, /command === 'build'[\s\S]*requireExplicit: true/)
  assert.deepEqual(vercel.rewrites[0], {
    source: '/api/v1/:path*',
    destination: 'https://mata-backend.vercel.app/api/v1/:path*',
  })
  assert.deepEqual(vercel.rewrites[1], {
    source: '/(.*)',
    destination: '/index.html',
  })
})

test('public login and registration routes stay public and contain no protected shell data', () => {
  const publicPaths = ['/login', '/register/non-nhg', '/non-nhg/register']
  const routePaths: string[] = routeAccessRules.map((rule) => rule.path)
  const appSource = read('src/App.tsx')
  const loginSource = read('src/pages/auth/LoginPage.tsx')
  const registrationSource = read('src/pages/auth/NonNhgRegistrationPage.tsx')

  for (const path of publicPaths) {
    assert.ok(routePaths.includes(path))
    assert.equal(getRouteAccessDecision({
      pathname: path,
      routeKind: 'public_auth',
      isLoading: false,
      hasExplicitSession: false,
      role: null,
    }).kind, 'allow')
  }
  assert.match(appSource, /path="\/login" element={<LoginPage \/>}/)
  assert.match(appSource, /path="\/register\/non-nhg" element={<NonNhgRegistrationPage \/>}/)
  assert.equal(loginSource.includes('AppShell'), false)
  assert.equal(registrationSource.includes('AppShell'), false)
  assert.equal(registrationSource.includes('loginWithSession'), false)
  assert.match(registrationSource, /Continue to login/)
})

test('all five authenticated roles retain their default redirects and cross-role guards', () => {
  const roles = Object.keys(roleUsers) as AppRole[]
  const protectedPathForRole: Record<AppRole, string> = {
    master_admin: '/admin',
    programme_pc: '/pc/teaching-events',
    secretary: '/secretary/events',
    resident: '/resident/submissions',
    external_resident: '/external/submissions',
  }

  for (const role of roles) {
    assert.equal(defaultPathForGuardRole(role), protectedPathForRole[role])
    assert.equal(getRouteAccessDecision({
      pathname: protectedPathForRole[role],
      routeKind: 'protected',
      isLoading: false,
      hasExplicitSession: true,
      role,
    }).kind, 'allow')
    assert.deepEqual(getRouteAccessDecision({
      pathname: '/login',
      routeKind: 'public_auth',
      isLoading: false,
      hasExplicitSession: true,
      role,
    }), {
      kind: 'redirect_to_role_default',
      to: protectedPathForRole[role],
    })

    const anotherRole = roles.find((candidate) => candidate !== role)
    assert.ok(anotherRole)
    assert.deepEqual(getRouteAccessDecision({
      pathname: protectedPathForRole[anotherRole],
      routeKind: 'protected',
      isLoading: false,
      hasExplicitSession: true,
      role,
    }), {
      kind: 'redirect_to_role_default',
      to: protectedPathForRole[role],
    })
  }

  assert.deepEqual(getRouteAccessDecision({
    pathname: '/admin',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: false,
    role: null,
  }), { kind: 'redirect_to_login', to: '/login' })
})

test('stub and demo identity headers remain local-only and Supabase mode stays cookie-only', () => {
  const authSource = read('src/api/authCookie.ts')
  const authHeadersSource = read('src/api/authHeaders.ts')
  assert.match(authSource, /frontendConfig\.authMode === 'supabase'[\s\S]*\? {}[\s\S]*toStubIdentityHeaders/)
  assert.match(authSource, /if \(!identity \|\| frontendConfig\.authMode === 'supabase'\)/)
  assert.match(
    authSource,
    /frontendConfig\.authMode === 'supabase'[\s\S]*throw error[\s\S]*csrfToken: ''/,
  )
  assert.match(authHeadersSource, /if \(frontendConfig\.authMode === 'supabase'\) \{[\s\S]*return {}/)
})

test('AppContext continues to react to memory-session identity changes safely', () => {
  const appContextSource = read('src/context/AppContext.tsx')
  assert.match(appContextSource, /authSessionChangedEvent/)
  assert.match(appContextSource, /readStoredAuthSession\(\)\?\.identity \?\? null/)
  assert.match(appContextSource, /transitionReportingPeriodAuthenticationContext/)
})

test('a session value contains only identity, CSRF, and optional refresh state', () => {
  const session: StoredAuthSession = {
    identity: parseAuthSessionResponse(sessionResponse(roleUsers.secretary)).identity,
    csrfToken: 'csrf',
    sessionRefreshRequired: false,
  }
  assert.deepEqual(Object.keys(session).sort(), [
    'csrfToken',
    'identity',
    'sessionRefreshRequired',
  ])
})
