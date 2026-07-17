export type ResidentLoginPayload = {
  role: 'resident'
  mcr: string
}

export const normaliseMcr = (mcr: string): string => mcr.trim().toUpperCase()

export const createResidentLoginPayload = (mcr: string): ResidentLoginPayload => ({
  role: 'resident',
  mcr: normaliseMcr(mcr),
})
