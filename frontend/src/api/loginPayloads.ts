export type ResidentLoginRole = 'resident' | 'external_resident'

export type ResidentLoginPayload = {
  role: ResidentLoginRole
  mcr: string
}

export const normaliseMcr = (mcr: string): string => mcr.trim().toUpperCase()

export const createResidentLoginPayload = (
  mcr: string,
  role: ResidentLoginRole = 'resident',
): ResidentLoginPayload => ({
  role,
  mcr: normaliseMcr(mcr),
})
