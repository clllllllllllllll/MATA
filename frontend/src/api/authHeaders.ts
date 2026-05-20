import { frontendConfig } from '../config/frontendConfig'

export const buildAdminDemoHeaders = (adminId: string, adminProgrammes: string[]): Record<string, string> => ({
  'X-User-Role': 'admin',
  'X-User-Id': adminId,
  'X-User-Programme': adminProgrammes.join(','),
})

export const buildSecretaryDemoHeaders = (overrides?: {
  secretaryId?: string
  secretarySite?: string
}): Record<string, string> => ({
  'X-User-Role': 'secretary',
  'X-User-Id': overrides?.secretaryId ?? frontendConfig.demoSecretaryId,
  'X-User-Site': overrides?.secretarySite ?? frontendConfig.demoSecretarySite,
})
