import type { AppRole } from './types/app'

type GuardRole = AppRole | null

interface BaseGuardInput {
  isLoading: boolean
  hasExplicitSession: boolean
  role: GuardRole
}

export type RouteAccessKind = 'root' | 'public_auth' | 'protected'
type RouteAccessRuleKind = 'public_auth' | 'protected' | 'redirect'

interface RouteAccessRule {
  path: string
  kind: RouteAccessRuleKind
  allowedRoles?: readonly AppRole[]
  matches?: (pathname: string) => boolean
}

export type RouteAccessDecision =
  | { kind: 'allow' }
  | { kind: 'wait_for_auth_hydration' }
  | { kind: 'redirect_to_login'; to: '/login' }
  | { kind: 'redirect_to_role_default'; to: string }

export type RouteGuardDecision =
  | { kind: 'allow' }
  | { kind: 'loading' }
  | { kind: 'redirect'; to: string }

const defaultPathByRole: Record<AppRole, string> = {
  master_admin: '/admin',
  programme_pc: '/pc/teaching-events',
  secretary: '/secretary/events',
  resident: '/resident/submissions',
  external_resident: '/external/submissions',
}

export const defaultPathForGuardRole = (role: AppRole): string => defaultPathByRole[role]

const uuidPathSegmentPattern =
  '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
const pcResidentAttendanceDetailPattern = new RegExp(
  `^/pc/residents/${uuidPathSegmentPattern}/attendance$`,
)

export const isPcResidentAttendanceDetailPath = (pathname: string): boolean => {
  const pathOnly = pathname.split(/[?#]/)[0] || '/'
  const normalisedPathname = pathOnly === '/' ? '/' : pathOnly.replace(/\/+$/, '')
  return pcResidentAttendanceDetailPattern.test(normalisedPathname)
}

const protectedNamespaces = [
  { prefix: '/admin', role: 'master_admin' },
  { prefix: '/pc', role: 'programme_pc' },
  { prefix: '/secretary', role: 'secretary' },
  { prefix: '/resident', role: 'resident' },
  { prefix: '/external', role: 'external_resident' },
] as const satisfies readonly { prefix: string; role: AppRole }[]

export const routeAccessRules = [
  { path: '/', kind: 'redirect' },
  { path: '/login', kind: 'public_auth' },
  { path: '/register/non-nhg', kind: 'public_auth' },
  { path: '/non-nhg/register', kind: 'public_auth' },
  { path: '/admin', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/upload', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/upload/warnings', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/config', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/config/multi', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/logs', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/upload-logs', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/parsed-data', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/secretary-events', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/staff-accounts', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/submissions', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/admin/external-attendance', kind: 'protected', allowedRoles: ['master_admin'] },
  { path: '/pc', kind: 'protected', allowedRoles: ['programme_pc'] },
  { path: '/pc/teaching-events', kind: 'protected', allowedRoles: ['programme_pc'] },
  { path: '/pc/upload-ttf', kind: 'protected', allowedRoles: ['programme_pc'] },
  { path: '/pc/warnings', kind: 'protected', allowedRoles: ['programme_pc'] },
  { path: '/pc/config', kind: 'protected', allowedRoles: ['programme_pc'] },
  { path: '/pc/resident-attendance', kind: 'protected', allowedRoles: ['programme_pc'] },
  {
    path: '/pc/residents/:resident_id/attendance',
    kind: 'protected',
    allowedRoles: ['programme_pc'],
    matches: isPcResidentAttendanceDetailPath,
  },
  { path: '/pc/external-attendance', kind: 'protected', allowedRoles: ['programme_pc'] },
  { path: '/secretary', kind: 'protected', allowedRoles: ['secretary'] },
  { path: '/secretary/events', kind: 'protected', allowedRoles: ['secretary'] },
  { path: '/resident', kind: 'protected', allowedRoles: ['resident'] },
  { path: '/resident/submissions', kind: 'protected', allowedRoles: ['resident'] },
  { path: '/resident/attendance', kind: 'protected', allowedRoles: ['resident'] },
  { path: '/external', kind: 'protected', allowedRoles: ['external_resident'] },
  { path: '/external/submissions', kind: 'protected', allowedRoles: ['external_resident'] },
  { path: '/external/attendance', kind: 'protected', allowedRoles: ['external_resident'] },
] as const satisfies readonly RouteAccessRule[]

const normalisePathname = (pathname: string): string => {
  const pathOnly = pathname.split(/[?#]/)[0] || '/'
  return pathOnly === '/' ? '/' : pathOnly.replace(/\/+$/, '')
}

const findRouteAccessRule = (pathname: string): RouteAccessRule | undefined => {
  const normalisedPathname = normalisePathname(pathname)
  return routeAccessRules.find((rule) =>
    rule.path === normalisedPathname
    || ('matches' in rule && rule.matches(normalisedPathname)))
}

const findProtectedNamespace = (pathname: string): { prefix: string; role: AppRole } | undefined => {
  const normalisedPathname = normalisePathname(pathname)
  return protectedNamespaces.find((namespace) =>
    normalisedPathname === namespace.prefix || normalisedPathname.startsWith(`${namespace.prefix}/`))
}

export const isRoutePathAllowedForRole = (pathname: string, role: AppRole): boolean => {
  const rule = findRouteAccessRule(pathname)
  return rule?.kind === 'protected' && Boolean(rule.allowedRoles?.includes(role))
}

export const roleForRoutePath = (pathname: string): AppRole | null => {
  const rule = findRouteAccessRule(pathname)
  return rule?.kind === 'protected' && rule.allowedRoles?.length === 1
    ? rule.allowedRoles[0]
    : null
}

export const getRouteAccessDecision = ({
  pathname,
  routeKind,
  isLoading,
  hasExplicitSession,
  role,
}: BaseGuardInput & { pathname: string; routeKind?: RouteAccessKind }): RouteAccessDecision => {
  if (isLoading) {
    return { kind: 'wait_for_auth_hydration' }
  }

  const routeRule = findRouteAccessRule(pathname)
  const protectedNamespace = findProtectedNamespace(pathname)
  const isFallbackRedirect = routeKind === 'root' || routeRule?.kind === 'redirect'

  if (routeRule?.kind === 'public_auth') {
    if (hasExplicitSession && role) {
      return { kind: 'redirect_to_role_default', to: defaultPathForGuardRole(role) }
    }
    return { kind: 'allow' }
  }

  if (protectedNamespace) {
    if (!hasExplicitSession || !role) {
      return { kind: 'redirect_to_login', to: '/login' }
    }
    if (protectedNamespace.role !== role) {
      return { kind: 'redirect_to_role_default', to: defaultPathForGuardRole(role) }
    }
    if (routeRule?.kind === 'protected' && routeRule.allowedRoles?.includes(role)) {
      return { kind: 'allow' }
    }
    return { kind: 'redirect_to_role_default', to: defaultPathForGuardRole(role) }
  }

  if (isFallbackRedirect) {
    if (hasExplicitSession && role) {
      return { kind: 'redirect_to_role_default', to: defaultPathForGuardRole(role) }
    }
    return { kind: 'redirect_to_login', to: '/login' }
  }

  if (routeKind === 'public_auth') {
    if (hasExplicitSession && role) {
      return { kind: 'redirect_to_role_default', to: defaultPathForGuardRole(role) }
    }
    return { kind: 'allow' }
  }

  if (!hasExplicitSession || !role) {
    return { kind: 'redirect_to_login', to: '/login' }
  }

  if (routeRule?.kind !== 'protected' || !routeRule.allowedRoles?.includes(role)) {
    return { kind: 'redirect_to_role_default', to: defaultPathForGuardRole(role) }
  }

  return { kind: 'allow' }
}

export const shouldRenderRoutes = (decision: RouteAccessDecision): boolean => decision.kind === 'allow'

const toLegacyDecision = (decision: RouteAccessDecision): RouteGuardDecision => {
  if (decision.kind === 'wait_for_auth_hydration') {
    return { kind: 'loading' }
  }
  if (decision.kind === 'redirect_to_login' || decision.kind === 'redirect_to_role_default') {
    return { kind: 'redirect', to: decision.to }
  }
  return decision
}

export const resolveRootRoute = ({
  isLoading,
  hasExplicitSession,
  role,
}: BaseGuardInput): RouteGuardDecision => {
  return toLegacyDecision(getRouteAccessDecision({
    pathname: '/',
    routeKind: 'root',
    isLoading,
    hasExplicitSession,
    role,
  }))
}

export const resolveLoginRoute = ({
  isLoading,
  hasExplicitSession,
  role,
}: BaseGuardInput): RouteGuardDecision => {
  return toLegacyDecision(getRouteAccessDecision({
    pathname: '/login',
    routeKind: 'public_auth',
    isLoading,
    hasExplicitSession,
    role,
  }))
}

export const resolveProtectedRoute = ({
  pathname,
  isLoading,
  hasExplicitSession,
  role,
}: BaseGuardInput & { pathname: string }): RouteGuardDecision => {
  return toLegacyDecision(getRouteAccessDecision({
    pathname,
    routeKind: 'protected',
    isLoading,
    hasExplicitSession,
    role,
  }))
}
