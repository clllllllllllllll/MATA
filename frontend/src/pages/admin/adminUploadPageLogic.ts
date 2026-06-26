import type { Programme } from '../../api/programmes'
import type { UploadType } from '../../types/app'
import { formatProgrammeOptionLabel, type ProgrammeOption } from '../../utils/programmeOptions.ts'

export type MasterAdminTtfProgrammeOption = ProgrammeOption

type AdminUploadWarningMode = 'active' | 'history'

interface AdminUploadWarningContext {
  reportingPeriodId?: string | null
  programmeCode?: string | null
}

export interface AdminUploadWarningsPathInput extends AdminUploadWarningContext {
  mode?: AdminUploadWarningMode
  uploadType?: UploadType | null
}

export interface AdminUploadSlotWarningsPathInput {
  uploadType: UploadType
  selectedReportingPeriodId: string
  selectedProgrammeCode: string
  latestUpload?: AdminUploadWarningContext | null
}

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

const trimOptional = (value?: string | null): string | undefined => {
  const trimmed = value?.trim()
  return trimmed || undefined
}

export const buildAdminUploadWarningsPath = ({
  mode = 'active',
  uploadType,
  reportingPeriodId,
  programmeCode,
}: AdminUploadWarningsPathInput): string => {
  const params = new URLSearchParams({ mode })
  const normalisedUploadType = uploadType ?? undefined
  const normalisedReportingPeriodId = trimOptional(reportingPeriodId)
  const normalisedProgrammeCode = trimOptional(programmeCode)

  if (normalisedUploadType) {
    params.set('upload_type', normalisedUploadType)
  }
  if (normalisedReportingPeriodId) {
    params.set('reporting_period_id', normalisedReportingPeriodId)
  }
  if (normalisedProgrammeCode) {
    params.set('programme_code', normalisedProgrammeCode)
  }

  return `/admin/upload/warnings?${params.toString()}`
}

export const buildReviewWarningsPathForUploadSlot = ({
  uploadType,
  selectedReportingPeriodId,
  selectedProgrammeCode,
  latestUpload,
}: AdminUploadSlotWarningsPathInput): string => {
  const hasLatestUpload = latestUpload !== undefined && latestUpload !== null
  return buildAdminUploadWarningsPath({
    mode: 'active',
    uploadType,
    reportingPeriodId: hasLatestUpload
      ? latestUpload.reportingPeriodId
      : uploadType === 'rdb' || uploadType === 'form_f1' || uploadType === 'ttf'
        ? selectedReportingPeriodId
        : undefined,
    programmeCode: hasLatestUpload
      ? latestUpload.programmeCode
      : uploadType === 'ttf'
        ? selectedProgrammeCode
        : undefined,
  })
}
