export type NonNhgMappingStatus = 'pending' | 'active'

export interface NonNhgRegistrationInstitution {
  code: string
  name: string
}

export interface NonNhgRegistrationAvailability {
  institutionCode: string
  available: boolean
  status: NonNhgMappingStatus
}

export interface NonNhgRegistrationProgramme {
  programmeCode: string
  programmeName: string
  institutions: NonNhgRegistrationAvailability[]
}

export interface NonNhgRegistrationOptions {
  institutions: NonNhgRegistrationInstitution[]
  programmes: NonNhgRegistrationProgramme[]
}

const optionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value.trim() : undefined

const requiredString = (value: unknown): string => optionalString(value) ?? ''

const isNonNhgMappingStatus = (value: unknown): value is NonNhgMappingStatus =>
  value === 'pending' || value === 'active'

export const parseNonNhgRegistrationOptions = (
  value: unknown,
): NonNhgRegistrationOptions => {
  if (!value || typeof value !== 'object') {
    throw new Error('Malformed registration options response.')
  }
  const response = value as Record<string, unknown>
  if (!Array.isArray(response.institutions) || !Array.isArray(response.programmes)) {
    throw new Error('Malformed registration options response.')
  }

  const institutions = response.institutions.map((entry) => {
    if (!entry || typeof entry !== 'object') {
      throw new Error('Malformed registration options response.')
    }
    const row = entry as Record<string, unknown>
    const code = requiredString(row.code)
    const name = requiredString(row.name)
    if (!code || !name) {
      throw new Error('Malformed registration options response.')
    }
    return { code, name }
  })

  const programmes = response.programmes.map((entry) => {
    if (!entry || typeof entry !== 'object') {
      throw new Error('Malformed registration options response.')
    }
    const row = entry as Record<string, unknown>
    const programmeCode = requiredString(row.programme_code)
    const programmeName = requiredString(row.programme_name)
    if (!programmeCode || !programmeName || !Array.isArray(row.institutions)) {
      throw new Error('Malformed registration options response.')
    }
    const programmeInstitutions = row.institutions.map((entryValue) => {
      if (!entryValue || typeof entryValue !== 'object') {
        throw new Error('Malformed registration options response.')
      }
      const institution = entryValue as Record<string, unknown>
      const institutionCode = requiredString(institution.institution_code)
      const status = institution.status
      if (
        !institutionCode ||
        typeof institution.available !== 'boolean' ||
        !isNonNhgMappingStatus(status) ||
        (status === 'pending' && institution.available)
      ) {
        throw new Error('Malformed registration options response.')
      }
      return { institutionCode, available: institution.available, status }
    })
    return { programmeCode, programmeName, institutions: programmeInstitutions }
  })

  return { institutions, programmes }
}
