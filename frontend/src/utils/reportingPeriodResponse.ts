import type { DataRevalidationImpact } from '../types/dataRevalidation.ts'
import type { ReportingPeriodOption } from '../types/upload.ts'
import {
  isReportingPeriodStatus,
  isStrictIsoCalendarDate,
  parseCalendarDate,
} from './reportingPeriods.ts'

const invalidReportingPeriodResponse = () => new Error('Reporting period response was invalid.')

const requiredNonEmptyString = (value: unknown): string => {
  if (typeof value !== 'string' || !value.trim()) {
    throw invalidReportingPeriodResponse()
  }
  return value
}

const optionalStrictIsoDate = (value: unknown): string | null => {
  if (value === null || value === undefined) {
    return null
  }
  if (!isStrictIsoCalendarDate(value)) {
    throw invalidReportingPeriodResponse()
  }
  return value
}

const toReportingPeriod = (
  value: unknown,
  mapDataRevalidation?: (value: unknown) => DataRevalidationImpact | null,
): ReportingPeriodOption => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw invalidReportingPeriodResponse()
  }
  const row = value as Record<string, unknown>
  const id = requiredNonEmptyString(row.id)
  const label = requiredNonEmptyString(row.label)
  const startDate = requiredNonEmptyString(row.start_date)
  const endDate = requiredNonEmptyString(row.end_date)
  if (!isStrictIsoCalendarDate(startDate) || !isStrictIsoCalendarDate(endDate)) {
    throw invalidReportingPeriodResponse()
  }
  if (parseCalendarDate(startDate) > parseCalendarDate(endDate)) {
    throw invalidReportingPeriodResponse()
  }
  if (!isReportingPeriodStatus(row.status)) {
    throw invalidReportingPeriodResponse()
  }
  return {
    id,
    label,
    startDate,
    endDate,
    status: row.status,
    activateOn: optionalStrictIsoDate(row.activate_on),
    deactivateOn: optionalStrictIsoDate(row.deactivate_on),
    createdAt: typeof row.created_at === 'string' ? row.created_at : undefined,
    updatedAt: typeof row.updated_at === 'string' ? row.updated_at : undefined,
    dataRevalidation: mapDataRevalidation?.(row.data_revalidation),
  }
}

export const parseReportingPeriodListResponse = (
  value: unknown,
  mapDataRevalidation?: (value: unknown) => DataRevalidationImpact | null,
): ReportingPeriodOption[] => {
  if (!Array.isArray(value)) {
    throw invalidReportingPeriodResponse()
  }
  return value.map((row) => toReportingPeriod(row, mapDataRevalidation))
}

export const parseReportingPeriodResponse = (
  value: unknown,
  mapDataRevalidation?: (value: unknown) => DataRevalidationImpact | null,
): ReportingPeriodOption => toReportingPeriod(value, mapDataRevalidation)
