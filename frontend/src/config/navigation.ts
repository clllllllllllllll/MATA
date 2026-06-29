import type { NavItem, RoleOption } from '../types/app'
import { frontendConfig } from './frontendConfig'

export const roleOptions: RoleOption[] = [
  {
    id: 'master_admin',
    label: 'Master Admin',
    scopeLabel: 'All Programmes',
    defaultPath: '/admin',
  },
  {
    id: 'programme_pc',
    label: 'Programme PC',
    scopeLabel: 'Geriatric Medicine',
    defaultPath: '/pc/upload-ttf',
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
    defaultPath: '/external',
  },
]

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
    label: 'Secretary Events',
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
    label: 'Teaching Schedule',
    path: '/secretary/events',
    roles: ['secretary'],
    icon: 'calendar',
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
    label: 'Non-NHG Portal',
    path: '/external',
    roles: ['external_resident'],
    icon: 'hospital',
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
  '/admin/secretary-events': ['Master Admin', 'Secretary Events'],
  '/admin/submissions': ['Master Admin', 'Resident Submissions'],
  '/pc/upload-ttf': ['Programme PC', 'Upload TTF'],
  '/pc/teaching-events': ['Programme PC', 'Teaching Events'],
  '/pc/warnings': ['Programme PC', 'Warnings'],
  '/pc/config': ['Programme PC', 'Configuration'],
  '/secretary': ['Secretary', 'Teaching Schedule'],
  '/secretary/events': ['Secretary', 'Teaching Schedule'],
  '/resident': ['NHG Resident', 'Submission Portal'],
  '/resident/submissions': ['NHG Resident', 'Submission Portal'],
  '/resident/attendance': ['NHG Resident', 'Past Submissions'],
  '/external': ['Non-NHG Resident', 'Submission Portal'],
}
