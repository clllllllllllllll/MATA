import type { Programme } from '../../api/programmes'
import { formatProgrammeOptionLabel, type ProgrammeOption } from '../../utils/programmeOptions.ts'

export type MasterAdminTtfProgrammeOption = ProgrammeOption

export const buildMasterAdminTtfProgrammeOptions = (
  programmes: Programme[],
  fallbackProgrammeScope: string[],
): MasterAdminTtfProgrammeOption[] => {
  const seen = new Set<string>()
  const options = programmes
    .map((programme) => {
      const code = programme.code.trim()
      return {
        code,
        label: formatProgrammeOptionLabel(programme),
      }
    })
    .filter((programme) => {
      if (!programme.code || seen.has(programme.code)) {
        return false
      }
      seen.add(programme.code)
      return true
    })

  if (options.length > 0) {
    return options
  }

  return fallbackProgrammeScope
    .map((programmeCode) => programmeCode.trim())
    .filter((programmeCode) => {
      if (!programmeCode || seen.has(programmeCode)) {
        return false
      }
      seen.add(programmeCode)
      return true
    })
    .map((programmeCode) => ({
      code: programmeCode,
      label: programmeCode,
    }))
}
