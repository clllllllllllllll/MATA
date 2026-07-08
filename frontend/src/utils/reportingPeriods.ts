import type { ReportingPeriodOption } from '../types/upload'

export type ReportingPeriodStatus = 'active' | 'inactive'

export const normaliseReportingPeriodStatus = (status?: string | null): ReportingPeriodStatus => {
  const value = status?.trim().toLowerCase()
  return value === 'inactive' || value === 'closed' ? 'inactive' : 'active'
}

export const isActiveReportingPeriodStatus = (status?: string | null): boolean =>
  normaliseReportingPeriodStatus(status) === 'active'

export const reportingPeriodStatusLabel = (status?: string | null): string =>
  normaliseReportingPeriodStatus(status) === 'active' ? 'Active' : 'Inactive'

const parseCalendarDate = (value: string) => {
  const dateOnlyMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (dateOnlyMatch) {
    const [, year, month, day] = dateOnlyMatch
    return new Date(Number(year), Number(month) - 1, Number(day))
  }
  return new Date(value)
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
