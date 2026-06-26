type PcProgrammeScopeMode = 'none' | 'locked' | 'select'

export interface PcProgrammeScopeState {
  mode: PcProgrammeScopeMode
  programmeScope: string[]
  selectedProgrammeCode: string
}

export interface PcTtfWarningsPathInput {
  programmeCode: string
  reportingPeriodId?: string
}

const uniqueProgrammeCodes = (programmeScope: string[]): string[] => {
  const seen = new Set<string>()
  return programmeScope
    .map((programmeCode) => programmeCode.trim())
    .filter((programmeCode) => {
      if (!programmeCode || seen.has(programmeCode)) {
        return false
      }
      seen.add(programmeCode)
      return true
    })
}

export const resolvePcProgrammeScope = (
  programmeScope: string[],
  requestedProgrammeCode: string,
): PcProgrammeScopeState => {
  const scopedProgrammes = uniqueProgrammeCodes(programmeScope)
  if (scopedProgrammes.length === 0) {
    return {
      mode: 'none',
      programmeScope: [],
      selectedProgrammeCode: '',
    }
  }

  const selectedProgrammeCode = scopedProgrammes.includes(requestedProgrammeCode)
    ? requestedProgrammeCode
    : scopedProgrammes[0]

  return {
    mode: scopedProgrammes.length === 1 ? 'locked' : 'select',
    programmeScope: scopedProgrammes,
    selectedProgrammeCode,
  }
}

export const buildPcTtfWarningsPath = ({
  programmeCode,
  reportingPeriodId,
}: PcTtfWarningsPathInput): string => {
  const params = new URLSearchParams({
    mode: 'active',
    upload_type: 'ttf',
    programme_code: programmeCode,
  })

  if (reportingPeriodId?.trim()) {
    params.set('reporting_period_id', reportingPeriodId.trim())
  }

  return `/pc/warnings?${params.toString()}`
}
