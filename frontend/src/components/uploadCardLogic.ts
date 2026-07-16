export type UploadCardStatus =
  | 'idle'
  | 'selected'
  | 'uploading'
  | 'parsing'
  | 'success'
  | 'error'

export interface UploadCardAvailabilityInput {
  hasFile: boolean
  status: UploadCardStatus
  requiresReportingPeriod: boolean
  reportingPeriodId?: string
  reportingPeriodValidationMessage?: string
  requiresProgramme: boolean
  programmeCode?: string
}

export interface UploadCardAvailability {
  disabled: boolean
  reportingPeriodMessage?: string
  programmeMessage?: string
}

const MISSING_REPORTING_PERIOD_MESSAGE = 'Select a reporting period before uploading.'
const MISSING_PROGRAMME_MESSAGE =
  'Programme code is required for TTF and must be one programme within your configured scope.'

export const resolveUploadCardAvailability = ({
  hasFile,
  status,
  requiresReportingPeriod,
  reportingPeriodId,
  reportingPeriodValidationMessage,
  requiresProgramme,
  programmeCode,
}: UploadCardAvailabilityInput): UploadCardAvailability => {
  const reportingPeriodMessage = requiresReportingPeriod
    ? reportingPeriodValidationMessage?.trim()
      || (reportingPeriodId?.trim() ? undefined : MISSING_REPORTING_PERIOD_MESSAGE)
    : undefined
  const programmeMessage = requiresProgramme && !programmeCode?.trim()
    ? MISSING_PROGRAMME_MESSAGE
    : undefined

  return {
    disabled:
      !hasFile
      || status === 'uploading'
      || status === 'parsing'
      || Boolean(reportingPeriodMessage)
      || Boolean(programmeMessage),
    reportingPeriodMessage,
    programmeMessage,
  }
}
