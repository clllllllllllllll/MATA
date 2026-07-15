import type { ReportingPeriodOption } from '../types/upload'

export type ReportingPeriodStatus = 'active' | 'inactive'

export const isReportingPeriodStatus = (status: unknown): status is ReportingPeriodStatus =>
  status === 'active' || status === 'inactive'

export const normaliseReportingPeriodStatus = (status?: string | null): ReportingPeriodStatus => {
  return status === 'active' ? 'active' : 'inactive'
}

export const isActiveReportingPeriodStatus = (status?: string | null): boolean =>
  normaliseReportingPeriodStatus(status) === 'active'

export const reportingPeriodStatusLabel = (status?: string | null): string =>
  normaliseReportingPeriodStatus(status) === 'active' ? 'Active' : 'Inactive'

const strictIsoDateParts = (value: unknown): [number, number, number] | null => {
  if (typeof value !== 'string') {
    return null
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) {
    return null
  }
  return [Number(match[1]), Number(match[2]), Number(match[3])]
}

export const parseStrictIsoCalendarDate = (value: unknown): Date | null => {
  const parts = strictIsoDateParts(value)
  if (!parts) {
    return null
  }
  const [year, month, day] = parts
  const parsed = new Date(0)
  parsed.setHours(0, 0, 0, 0)
  parsed.setFullYear(year, month - 1, day)
  return parsed.getFullYear() === year
    && parsed.getMonth() === month - 1
    && parsed.getDate() === day
    ? parsed
    : null
}

export const isStrictIsoCalendarDate = (value: unknown): value is string =>
  parseStrictIsoCalendarDate(value) !== null

export const parseCalendarDate = (value: string): Date =>
  parseStrictIsoCalendarDate(value) ?? new Date(Number.NaN)

const calendarDate = (value: Date | string): Date =>
  value instanceof Date
    ? new Date(value.getFullYear(), value.getMonth(), value.getDate())
    : parseCalendarDate(value)

const isValidCalendarDate = (value: Date) => Number.isFinite(value.getTime())

export const effectiveReportingPeriodStatus = (
  period: Pick<ReportingPeriodOption, 'status' | 'activateOn' | 'deactivateOn'>,
  asOf: Date = new Date(),
): ReportingPeriodStatus => {
  if (
    !isReportingPeriodStatus(period.status)
    || (period.activateOn != null && !isStrictIsoCalendarDate(period.activateOn))
    || (period.deactivateOn != null && !isStrictIsoCalendarDate(period.deactivateOn))
  ) {
    return 'inactive'
  }
  const asOfDate = calendarDate(asOf)
  const activateOn = period.activateOn ? parseCalendarDate(period.activateOn) : null
  const deactivateOn = period.deactivateOn ? parseCalendarDate(period.deactivateOn) : null
  const activateDue = Boolean(activateOn && isValidCalendarDate(activateOn) && asOfDate >= activateOn)
  const deactivateDue = Boolean(deactivateOn && isValidCalendarDate(deactivateOn) && asOfDate >= deactivateOn)

  if (!activateDue && !deactivateDue) {
    return normaliseReportingPeriodStatus(period.status)
  }
  if (!activateDue) {
    return 'inactive'
  }
  if (!deactivateDue) {
    return 'active'
  }
  // The backend resolves ties in favour of deactivation.
  return deactivateOn! >= activateOn! ? 'inactive' : 'active'
}

export const isEffectivelyActiveReportingPeriod = (
  period: Pick<ReportingPeriodOption, 'status' | 'activateOn' | 'deactivateOn'>,
  asOf: Date = new Date(),
): boolean => effectiveReportingPeriodStatus(period, asOf) === 'active'

export const reportingPeriodContainsDate = (
  period: Pick<ReportingPeriodOption, 'startDate' | 'endDate'>,
  relevantDate: Date = new Date(),
): boolean => {
  const date = calendarDate(relevantDate)
  const start = parseCalendarDate(period.startDate)
  const end = parseCalendarDate(period.endDate)
  return isValidCalendarDate(date) && isValidCalendarDate(start) && isValidCalendarDate(end)
    && start <= date && date <= end
}

export const selectCurrentReportingPeriodId = (
  periods: ReportingPeriodOption[],
  asOf: Date = new Date(),
): string => {
  const matches = periods.filter((period) =>
    isEffectivelyActiveReportingPeriod(period, asOf) && reportingPeriodContainsDate(period, asOf),
  )
  return matches.length === 1 ? matches[0].id : ''
}

export const retainOrSelectReportingPeriodId = (
  periods: ReportingPeriodOption[],
  selectedId: string,
  asOf: Date = new Date(),
): string =>
  selectedId && periods.some((period) => period.id === selectedId)
    ? selectedId
    : selectCurrentReportingPeriodId(periods, asOf)

export const validatedReportingPeriod = (
  periods: ReportingPeriodOption[],
  selectedId: string,
): ReportingPeriodOption | undefined =>
  selectedId ? periods.find((period) => period.id === selectedId) : undefined

export const withValidatedReportingPeriod = async <T>(
  periods: ReportingPeriodOption[],
  selectedId: string,
  operation: (period: ReportingPeriodOption) => Promise<T>,
): Promise<T | undefined> => {
  const period = validatedReportingPeriod(periods, selectedId)
  return period ? operation(period) : undefined
}

export const reportingPeriodDisplayStatus = (
  period: ReportingPeriodOption,
  asOf: Date = new Date(),
): string => {
  if (!isEffectivelyActiveReportingPeriod(period, asOf)) {
    return 'Inactive'
  }
  if (reportingPeriodContainsDate(period, asOf)) {
    return 'Current active'
  }
  const date = calendarDate(asOf)
  const start = parseCalendarDate(period.startDate)
  const end = parseCalendarDate(period.endDate)
  if (isValidCalendarDate(start) && start > date) {
    return 'Upcoming'
  }
  if (isValidCalendarDate(end) && end < date) {
    return 'Active — reopened'
  }
  return 'Active'
}

export const defaultDeactivateOn = (endDate: string): string => {
  const end = parseCalendarDate(endDate)
  if (!isValidCalendarDate(end)) {
    return ''
  }
  end.setDate(end.getDate() + 14)
  return [end.getFullYear(), String(end.getMonth() + 1).padStart(2, '0'), String(end.getDate()).padStart(2, '0')]
    .join('-')
}

const formatPeriodBoundaryDate = (value: string) => {
  const parsed = parseCalendarDate(value)
  if (!Number.isFinite(parsed.getTime())) {
    return null
  }
  return parsed.toLocaleDateString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })
}

export const formatReportingPeriodOptionLabel = (period: ReportingPeriodOption): string => {
  const start = formatPeriodBoundaryDate(period.startDate)
  const end = formatPeriodBoundaryDate(period.endDate)
  return start && end ? `${period.label} (${start} - ${end})` : period.label
}
