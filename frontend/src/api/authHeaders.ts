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

export const buildResidentDemoHeaders = (overrides?: {
  residentId?: string
  residentProgramme?: string
  residentMcr?: string
}): Record<string, string> => ({
  'X-User-Role': 'resident',
  'X-User-Id': overrides?.residentId ?? frontendConfig.demoResidentId,
  'X-User-Programme': overrides?.residentProgramme ?? frontendConfig.demoResidentProgramme,
  'X-User-MCR': overrides?.residentMcr ?? frontendConfig.demoResidentMcr,
})
