import {
  defaultDeactivateOn,
  reportingPeriodDisplayStatus,
  retainOrSelectReportingPeriodId,
  selectCurrentReportingPeriodId,
} from './reportingPeriods.ts'
import type { ReportingPeriodOption } from '../types/upload.ts'

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const periods = [
  {
    id: 'reopened-past',
    label: 'Reopened 2025',
    startDate: '2025-07-01',
    endDate: '2025-12-31',
    status: 'active',
    deactivateOn: '2026-12-31',
  },
  {
    id: 'current',
    label: 'Current 2026',
    startDate: '2026-07-01',
    endDate: '2026-12-31',
    status: 'active',
  },
  {
    id: 'uat-2099',
    label: 'UAT semantic test 2099',
    startDate: '2099-01-01',
    endDate: '2099-06-30',
    status: 'active',
  },
] satisfies ReportingPeriodOption[]

const currentDate = new Date(2026, 6, 15)

assertEqual(
  selectCurrentReportingPeriodId(periods, currentDate),
  'current',
  'current-period default ignores reopened past and future active periods',
)
assertEqual(
  retainOrSelectReportingPeriodId(periods, 'reopened-past', currentDate),
  'reopened-past',
  'an explicitly selected historical period remains selectable',
)
assertEqual(
  retainOrSelectReportingPeriodId(periods, 'uat-2099', currentDate),
  'uat-2099',
  'an explicitly selected future period remains selectable',
)
assertEqual(
  selectCurrentReportingPeriodId([periods[0], periods[2]], currentDate),
  '',
  'no current-date period produces no unsafe active-period fallback',
)
assertEqual(
  selectCurrentReportingPeriodId([
    periods[1],
    { ...periods[1], id: 'overlapping-current', label: 'Overlapping current' },
  ], currentDate),
  '',
  'overlapping current periods fail closed without a frontend default',
)
assertEqual(
  defaultDeactivateOn('2026-12-31'),
  '2027-01-14',
  'default deactivation is fourteen calendar days after the period end date',
)
assertEqual(
  reportingPeriodDisplayStatus(periods[0], currentDate),
  'Active — reopened',
  'active past periods are labelled as reopened rather than current',
)
assertEqual(
  reportingPeriodDisplayStatus(periods[2], currentDate),
  'Upcoming',
  'active future periods are labelled as upcoming',
)
