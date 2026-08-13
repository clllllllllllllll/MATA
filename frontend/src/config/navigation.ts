import type { NavItem, RoleOption } from '../types/app'
import { frontendConfig } from './frontendConfig'
import type { AppRole } from '../types/app'
import { defaultPathForGuardRole, isRoutePathAllowedForRole, roleForRoutePath } from '../routeGuards'

export const roleOptions: RoleOption[] = [
  {
    id: 'master_admin',
    label: 'Master Admin',
    scopeLabel: 'All Programmes',
    defaultPath: '/admin',
  },
  {
    id: 'programme_pc',
    label: 'PC',
    scopeLabel: 'Geriatric Medicine',
    defaultPath: '/pc/teaching-events',
  },
  {
    id: 'secretary',
    label: 'Secretary',
    scopeLabel: frontendConfig.demoSecretaryScopeLabel,
    defaultPath: '/secretary/events',
  },
  {
    id: 'resident',
    label: 'NHG Resident',
    scopeLabel: frontendConfig.demoResidentScopeLabel,
    defaultPath: '/resident/submissions',
  },
  {
    id: 'external_resident',
    label: 'Non-NHG Resident',
    scopeLabel: 'NUH - posted to TTSH GRM',
    defaultPath: '/external/submissions',
  },
]

export const defaultPathForRole = (role: AppRole): string => defaultPathForGuardRole(role)

export const roleFromPathname = (pathname: string): AppRole | null => roleForRoutePath(pathname)

export const isPathAllowedForRole = (pathname: string, role: AppRole): boolean => {
  return isRoutePathAllowedForRole(pathname, role)
}

export const navItems: NavItem[] = [
  {
    label: 'Home',
    path: '/admin',
    roles: ['master_admin'],
    icon: 'home',
  },
  {
    label: 'Upload Files',
    path: '/admin/upload',
    roles: ['master_admin'],
    icon: 'upload',
  },
  {
    label: 'Warnings',
    path: '/admin/upload/warnings',
    roles: ['master_admin'],
    icon: 'warn',
  },
  {
    label: 'Configuration',
    path: '/admin/config',
    roles: ['master_admin'],
    icon: 'settings',
  },
  {
    label: 'Admin Logs',
    path: '/admin/logs',
    roles: ['master_admin'],
    icon: 'file',
  },
  {
    label: 'Live Data',
    path: '/admin/parsed-data',
    roles: ['master_admin'],
    icon: 'database',
  },
  {
    label: 'Staff Accounts',
    path: '/admin/staff-accounts',
    roles: ['master_admin'],
    icon: 'settings',
  },
  {
    label: 'Secretary/PC Events',
    path: '/admin/secretary-events',
    roles: ['master_admin'],
    icon: 'calendar',
  },
  {
    label: 'Resident Submissions',
    path: '/admin/submissions',
    roles: ['master_admin'],
    icon: 'grid',
  },
  {
    label: 'Non-NHG Attendance',
    path: '/admin/external-attendance',
    roles: ['master_admin'],
    icon: 'hospital',
  },
  {
    label: 'Upload TTF',
    path: '/pc/upload-ttf',
    roles: ['programme_pc'],
    icon: 'upload',
  },
  {
    label: 'Teaching Events',
    path: '/pc/teaching-events',
    roles: ['programme_pc'],
    icon: 'calendar',
  },
  {
    label: 'Session Types',
    path: '/pc/session-types',
    roles: ['programme_pc'],
    icon: 'settings',
  },
  {
    label: 'Warnings',
    path: '/pc/warnings',
    roles: ['programme_pc'],
    icon: 'warn',
  },
  {
    label: 'Configuration',
    path: '/pc/config',
    roles: ['programme_pc'],
    icon: 'settings',
  },
  {
    label: 'NHG Resident Attendance',
    path: '/pc/resident-attendance',
    roles: ['programme_pc'],
    icon: 'file',
  },
  {
    label: 'Non-NHG Attendance',
    path: '/pc/external-attendance',
    roles: ['programme_pc'],
    icon: 'hospital',
  },
  {
    label: 'Teaching Schedule',
    path: '/secretary/events',
    roles: ['secretary'],
    icon: 'calendar',
  },
  {
    label: 'Update Names of Teaching',
    path: '/secretary/teaching-names',
    roles: ['secretary'],
    icon: 'settings',
  },
  {
    label: 'Submission Portal',
    path: '/resident/submissions',
    roles: ['resident'],
    icon: 'send',
  },
  {
    label: 'Past Submissions',
    path: '/resident/attendance',
    roles: ['resident'],
    icon: 'file',
  },
  {
    label: 'Submission Portal',
    path: '/external/submissions',
    roles: ['external_resident'],
    icon: 'send',
  },
  {
    label: 'Past Submissions',
    path: '/external/attendance',
    roles: ['external_resident'],
    icon: 'file',
  },
]

export const breadcrumbMap: Record<string, string[]> = {
  '/admin': ['Master Admin', 'Home'],
  '/admin/upload': ['Master Admin', 'Upload Files'],
  '/admin/upload/warnings': ['Master Admin', 'Warnings'],
  '/admin/config': ['Master Admin', 'Configuration'],
  '/admin/config/multi': ['Master Admin', 'Configuration', 'Multi-Posting Rules'],
  '/admin/logs': ['Master Admin', 'Admin Logs'],
  '/admin/upload-logs': ['Master Admin', 'Upload Logs'],
  '/admin/parsed-data': ['Master Admin', 'Live Data'],
  '/admin/secretary-events': ['Master Admin', 'Secretary/PC Events'],
  '/admin/staff-accounts': ['Master Admin', 'Staff Accounts'],
  '/admin/submissions': ['Master Admin', 'Resident Submissions'],
  '/admin/external-attendance': ['Master Admin', 'Non-NHG Attendance'],
  '/pc/upload-ttf': ['PC', 'Upload TTF'],
  '/pc/teaching-events': ['PC', 'Teaching Events'],
  '/pc/session-types': ['PC', 'Session Types'],
  '/pc/warnings': ['PC', 'Warnings'],
  '/pc/config': ['PC', 'Configuration'],
  '/pc/resident-attendance': ['PC', 'NHG Resident Attendance'],
  '/pc/external-attendance': ['PC', 'Non-NHG Attendance'],
  '/secretary': ['Secretary', 'Teaching Schedule'],
  '/secretary/events': ['Secretary', 'Teaching Schedule'],
  '/secretary/teaching-names': ['Secretary', 'Update Names of Teaching'],
  '/resident': ['NHG Resident', 'Submission Portal'],
  '/resident/submissions': ['NHG Resident', 'Submission Portal'],
  '/resident/attendance': ['NHG Resident', 'Past Submissions'],
  '/external': ['Non-NHG Resident', 'Submission Portal'],
  '/external/submissions': ['Non-NHG Resident', 'Submission Portal'],
  '/external/attendance': ['Non-NHG Resident', 'Past Submissions'],
}
