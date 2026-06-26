import type { Programme } from '../../api/programmes'
import { formatProgrammeOptionLabel, type ProgrammeOption } from '../../utils/programmeOptions.ts'

type PcProgrammeScopeMode = 'none' | 'locked' | 'select'

export interface PcProgrammeScopeState {
  mode: PcProgrammeScopeMode
  programmeScope: string[]
  programmeOptions: ProgrammeOption[]
  selectedProgrammeCode: string
  selectedProgrammeLabel: string
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

const buildProgrammeLookup = (programmeCatalogue: Programme[]): Map<string, Programme> => {
  const byCode = new Map<string, Programme>()
  programmeCatalogue.forEach((programme) => {
    const code = programme.code.trim()
    if (code && !byCode.has(code)) {
      byCode.set(code, programme)
    }
  })
  return byCode
}

const buildScopedProgrammeOptions = (
  programmeScope: string[],
  programmeCatalogue: Programme[],
): ProgrammeOption[] => {
  const byCode = buildProgrammeLookup(programmeCatalogue)
  return programmeScope.map((programmeCode) => {
    const programme = byCode.get(programmeCode)
    return {
      code: programmeCode,
      label: programme ? formatProgrammeOptionLabel(programme) : programmeCode,
    }
  })
}

export const resolvePcProgrammeScope = (
  programmeScope: string[],
  requestedProgrammeCode: string,
  programmeCatalogue: Programme[] = [],
): PcProgrammeScopeState => {
  const scopedProgrammes = uniqueProgrammeCodes(programmeScope)
  const programmeOptions = buildScopedProgrammeOptions(scopedProgrammes, programmeCatalogue)
  if (scopedProgrammes.length === 0) {
    return {
      mode: 'none',
      programmeScope: [],
      programmeOptions: [],
      selectedProgrammeCode: '',
      selectedProgrammeLabel: '',
    }
  }

  const selectedProgrammeCode = scopedProgrammes.includes(requestedProgrammeCode)
    ? requestedProgrammeCode
    : scopedProgrammes[0]
  const selectedProgrammeLabel =
    programmeOptions.find((programme) => programme.code === selectedProgrammeCode)?.label ?? selectedProgrammeCode

  return {
    mode: scopedProgrammes.length === 1 ? 'locked' : 'select',
    programmeScope: scopedProgrammes,
    programmeOptions,
    selectedProgrammeCode,
    selectedProgrammeLabel,
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
