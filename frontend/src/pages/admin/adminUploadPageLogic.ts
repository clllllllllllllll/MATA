import type { Programme } from '../../api/programmes'
import type { UploadRequest } from '../../api/uploads'
import type { UploadType } from '../../types/app'
import type { ReportingPeriodOption } from '../../types/upload'
import { formatProgrammeOptionLabel, type ProgrammeOption } from '../../utils/programmeOptions.ts'

export type MasterAdminTtfProgrammeOption = ProgrammeOption

export const MISSING_REPORTING_PERIOD_MESSAGE = 'Select a reporting period before uploading.'
export const INACTIVE_REPORTING_PERIOD_MESSAGE = 'Selected reporting period is inactive.'
export const INVALID_REPORTING_PERIOD_MESSAGE = 'Selected reporting period is unavailable.'

export type AdminUploadReportingPeriodState = 'missing' | 'invalid' | 'inactive' | 'active'

export interface AdminUploadReportingPeriodSelection {
  state: AdminUploadReportingPeriodState
  period?: ReportingPeriodOption
  reportingPeriodId: string
  validationMessage?: string
}

export const resolveAdminUploadReportingPeriod = (
  reportingPeriods: ReportingPeriodOption[],
  selectedId: string,
): AdminUploadReportingPeriodSelection => {
  if (!selectedId.trim()) {
    return {
      state: 'missing',
      reportingPeriodId: '',
      validationMessage: MISSING_REPORTING_PERIOD_MESSAGE,
    }
  }

  const period = reportingPeriods.find((candidate) => candidate.id === selectedId)
  if (!period) {
    return {
      state: 'invalid',
      reportingPeriodId: '',
      validationMessage: INVALID_REPORTING_PERIOD_MESSAGE,
    }
  }

  if (period.status !== 'active') {
    return {
      state: 'inactive',
      period,
      reportingPeriodId: period.id,
      validationMessage: INACTIVE_REPORTING_PERIOD_MESSAGE,
    }
  }

  return {
    state: 'active',
    period,
    reportingPeriodId: period.id,
  }
}

export interface SubmitAdminUploadInput extends Omit<UploadRequest, 'reportingPeriodId'> {
  reportingPeriod: AdminUploadReportingPeriodSelection
}

export interface SubmittedAdminUpload {
  request: UploadRequest
  response: Record<string, unknown>
}

type AdminUploadSubmitter = (request: UploadRequest) => Promise<Record<string, unknown>>

const uploadRequiresReportingPeriod = (uploadType: UploadType): boolean =>
  uploadType === 'rdb' || uploadType === 'ttf' || uploadType === 'form_f1'

export const submitAdminUpload = async (
  input: SubmitAdminUploadInput,
  submit: AdminUploadSubmitter,
): Promise<SubmittedAdminUpload | undefined> => {
  const requiresReportingPeriod = uploadRequiresReportingPeriod(input.uploadType)
  if (
    requiresReportingPeriod
    && (
      input.reportingPeriod.state !== 'active'
      || !input.reportingPeriod.period
      || input.reportingPeriod.period.id !== input.reportingPeriod.reportingPeriodId
    )
  ) {
    return undefined
  }

  const programmeCode = input.programmeCode?.trim()
  if (input.uploadType === 'ttf' && !programmeCode) {
    return undefined
  }

  const request: UploadRequest = {
    uploadType: input.uploadType,
    file: input.file,
    reportingPeriodId: requiresReportingPeriod
      ? input.reportingPeriod.reportingPeriodId
      : undefined,
    programmeCode,
    adminProgrammes: input.adminProgrammes,
    adminId: input.adminId,
    adminLevel: input.adminLevel,
    actorName: input.actorName,
  }
  const response = await submit(request)
  return { request, response }
}

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
