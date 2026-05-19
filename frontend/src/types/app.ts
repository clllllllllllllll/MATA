export type AppRole =
  | 'master_admin'
  | 'programme_pc'
  | 'secretary'
  | 'resident'
  | 'external_resident'

export type UploadType = 'public_holidays' | 'rdb' | 'ttf' | 'form_f1'

export interface RoleOption {
  id: AppRole
  label: string
  scopeLabel: string
  defaultPath: string
}

export interface NavItem {
  label: string
  path: string
  roles: AppRole[]
  icon: string
}
