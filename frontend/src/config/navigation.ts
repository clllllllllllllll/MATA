import type { NavItem, RoleOption } from '../types/app'

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
    scopeLabel: 'TTSH Geriatric Medicine',
    defaultPath: '/secretary',
  },
  {
    id: 'resident',
    label: 'Native Resident',
    scopeLabel: 'TTSH Geriatric Medicine · MCR M00001A',
    defaultPath: '/resident',
  },
  {
    id: 'external_resident',
    label: 'External Resident',
    scopeLabel: 'NUH · posted to TTSH GRM',
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
    path: '/admin/config/multi',
    roles: ['master_admin'],
    icon: 'settings',
  },
  {
    label: 'Upload TTF',
    path: '/pc/upload-ttf',
    roles: ['programme_pc'],
    icon: 'upload',
  },
  {
    label: 'Dashboard',
    path: '/secretary',
    roles: ['secretary'],
    icon: 'home',
  },
  {
    label: 'Submission Portal',
    path: '/resident',
    roles: ['resident'],
    icon: 'send',
  },
  {
    label: 'External Portal',
    path: '/external',
    roles: ['external_resident'],
    icon: 'hospital',
  },
]

export const breadcrumbMap: Record<string, string[]> = {
  '/admin': ['Master Admin', 'Home'],
  '/admin/upload': ['Master Admin', 'Upload Files'],
  '/admin/upload/warnings': ['Master Admin', 'Warning Review'],
  '/admin/config/multi': ['Master Admin', 'Multi-Posting Rules'],
  '/pc/upload-ttf': ['Programme PC', 'Upload TTF'],
  '/secretary': ['Secretary', 'Dashboard'],
  '/resident': ['Native Resident', 'Submission Portal'],
  '/external': ['External Resident', 'Submission Portal'],
}
