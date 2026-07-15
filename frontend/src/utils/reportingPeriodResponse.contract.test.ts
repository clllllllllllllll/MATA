import { parseReportingPeriodListResponse } from './reportingPeriodResponse.ts'
import type { AuthIdentity } from '../types/auth.ts'
import type { ReportingPeriodOption } from '../types/upload.ts'
import {
  applyReportingPeriodLoadFailure,
  applyReportingPeriodLoadSuccess,
  createReportingPeriodContextState,
  reportingPeriodLoadToken,
  selectValidatedReportingPeriod,
} from './reportingPeriodContextState.ts'
import { isEffectivelyActiveReportingPeriod } from './reportingPeriods.ts'

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const assertRejected = (value: unknown, label: string) => {
  let rejected = false
  try {
    parseReportingPeriodListResponse(value)
  } catch {
    rejected = true
  }
  assertEqual(rejected, true, label)
}

const validRow = {
  id: 'current',
  label: 'Current period',
  start_date: '2026-07-01',
  end_date: '2026-12-31',
  status: 'active',
  activate_on: null,
  deactivate_on: null,
}

const valid = parseReportingPeriodListResponse([validRow])
assertEqual(valid.length, 1, 'a fully valid array is accepted')
assertEqual(valid[0]?.activateOn, null, 'a null activation date is accepted')
assertEqual(valid[0]?.deactivateOn, null, 'a null deactivation date is accepted')

for (const status of ['pending', '', 'open', 'closed', 'archived']) {
  assertRejected([{ ...validRow, status }], `${status || 'empty'} status rejects the complete response`)
}

assertRejected([{ ...validRow, start_date: 'not-a-date' }], 'an invalid start date is rejected')
assertRejected([{ ...validRow, end_date: '31-Dec-2026' }], 'an arbitrary end-date string is rejected')
assertRejected([{ ...validRow, start_date: '2026-02-30' }], 'an impossible calendar date is rejected')
assertRejected([{ ...validRow, activate_on: '2026-02-30' }], 'an invalid activation date is rejected')
assertRejected([{ ...validRow, deactivate_on: 'tomorrow' }], 'an invalid deactivation date is rejected')
assertRejected(
  [{ ...validRow, start_date: '2027-01-01', end_date: '2026-12-31' }],
  'a reversed period range is rejected',
)
assertRejected([validRow, { ...validRow, id: '' }], 'one malformed row rejects the complete mixed array')
assertRejected([validRow, null], 'a non-object row rejects the complete mixed array')
assertRejected({ items: [validRow] }, 'a non-array top-level response is rejected')

const principal: AuthIdentity = {
  role: 'programme_pc',
  subjectId: 'principal',
  adminLevel: 'programme',
  programmeScope: ['DR'],
  staffActorNameRequired: false,
}
const currentDate = new Date(2026, 6, 15)
const futurePeriod: ReportingPeriodOption = {
  id: 'future-test',
  label: 'Future test',
  startDate: '2099-01-01',
  endDate: '2099-06-30',
  status: 'active',
}
let state = createReportingPeriodContextState(principal)
let token = reportingPeriodLoadToken(state)
state = applyReportingPeriodLoadSuccess(state, token, [valid[0]!, futurePeriod], currentDate)
state = selectValidatedReportingPeriod(state, futurePeriod.id)
try {
  parseReportingPeriodListResponse([{ ...validRow, status: 'pending' }])
} catch {
  token = reportingPeriodLoadToken(state)
  state = applyReportingPeriodLoadFailure(state, token)
}
assertEqual(state.periods.length, 0, 'a malformed refresh clears the prior period list')
assertEqual(state.selectedId, '', 'a malformed refresh clears a prior explicit future selection')

assertEqual(
  isEffectivelyActiveReportingPeriod({
    status: 'pending',
    activateOn: '2026-01-01',
  } as unknown as ReportingPeriodOption, currentDate),
  false,
  'an unknown status is never considered effectively active even with a due activation date',
)
