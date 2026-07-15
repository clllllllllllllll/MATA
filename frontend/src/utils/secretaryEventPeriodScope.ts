import type { ReportingPeriodOption } from '../types/upload'

export interface SecretaryEventDateRange {
  dateFrom?: string
  dateTo?: string
}

export const secretaryEventDateRange = (
  period: ReportingPeriodOption | undefined,
): SecretaryEventDateRange | undefined =>
  period ? { dateFrom: period.startDate, dateTo: period.endDate } : undefined

export const loadSecretaryEventsForPeriod = async <T>(
  period: ReportingPeriodOption | undefined,
  load: (range: SecretaryEventDateRange) => Promise<T>,
): Promise<T | undefined> => {
  const range = secretaryEventDateRange(period)
  return range ? load(range) : undefined
}

export const shouldApplySecretaryEventLoad = (
  requestedPeriodId: string | null,
  currentPeriodId: string | null,
): boolean => requestedPeriodId === currentPeriodId
