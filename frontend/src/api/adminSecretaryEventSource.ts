export type AdminSecretaryEventSourceType = 'secretary' | 'programme_pc'
export type AdminSecretaryEventSourceFilter = 'all' | AdminSecretaryEventSourceType

interface SourceFallbackOptions {
  createdForProgrammeCode: unknown
}

export const resolveAdminSecretaryEventSourceType = (
  value: unknown,
  fallback?: SourceFallbackOptions,
): AdminSecretaryEventSourceType => {
  if (value === 'secretary' || value === 'programme_pc') {
    return value
  }
  if ((value === null || value === undefined || value === '') && fallback) {
    if (fallback.createdForProgrammeCode === null || fallback.createdForProgrammeCode === undefined) {
      return 'secretary'
    }
    if (typeof fallback.createdForProgrammeCode === 'string') {
      return 'programme_pc'
    }
  }
  throw new Error('Invalid Secretary/PC event source type')
}
