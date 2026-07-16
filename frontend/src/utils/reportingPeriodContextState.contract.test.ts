import type { AuthIdentity } from '../types/auth.ts'
import type { ReportingPeriodOption } from '../types/upload.ts'
import {
  applyReportingPeriodLoadFailure,
  applyReportingPeriodLoadSuccess,
  createReportingPeriodContextState,
  reportingPeriodLoadToken,
  reportingPeriodAuthenticationContextKey,
  selectValidatedReportingPeriod,
  transitionReportingPeriodAuthenticationContext,
} from './reportingPeriodContextState.ts'
import { withValidatedReportingPeriod } from './reportingPeriods.ts'

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const currentDate = new Date(2026, 6, 15)
const periods = [
  {
    id: 'reopened-past',
    label: 'Reopened past',
    startDate: '2025-07-01',
    endDate: '2025-12-31',
    status: 'active',
    deactivateOn: '2026-12-31',
  },
  {
    id: 'current',
    label: 'Current',
    startDate: '2026-07-01',
    endDate: '2026-12-31',
    status: 'active',
  },
  {
    id: 'future-active',
    label: 'Future test period',
    startDate: '2099-01-01',
    endDate: '2099-06-30',
    status: 'active',
  },
  {
    id: 'inactive-history',
    label: 'Inactive history',
    startDate: '2024-01-01',
    endDate: '2024-06-30',
    status: 'inactive',
  },
] satisfies ReportingPeriodOption[]

const principalA: AuthIdentity = {
  role: 'programme_pc',
  subjectId: 'principal-a',
  adminLevel: 'programme',
  programmeScope: ['DR'],
  staffActorNameRequired: false,
}
const principalB: AuthIdentity = {
  role: 'programme_pc',
  subjectId: 'principal-b',
  adminLevel: 'programme',
  programmeScope: ['DR'],
  staffActorNameRequired: false,
}

assertEqual(
  reportingPeriodAuthenticationContextKey({ ...principalA, programmeScope: ['GERI', 'DR', 'DR'] }),
  reportingPeriodAuthenticationContextKey({ ...principalA, programmeScope: ['DR', 'GERI'] }),
  'equivalent programme scopes have a deterministic order-insensitive context key',
)
assertEqual(
  reportingPeriodAuthenticationContextKey(principalA)
    === reportingPeriodAuthenticationContextKey({
      ...principalA,
      adminLevel: 'master',
    } as unknown as AuthIdentity),
  false,
  'an isolated admin-level change creates a new context key',
)
const secretaryIdentity: AuthIdentity = {
  role: 'secretary',
  subjectId: 'secretary-principal',
  postingCode: 'SITE-A',
  staffActorNameRequired: false,
}
assertEqual(
  reportingPeriodAuthenticationContextKey(secretaryIdentity)
    === reportingPeriodAuthenticationContextKey({ ...secretaryIdentity, postingCode: 'SITE-B' }),
  false,
  'a Secretary posting-scope change creates a new context key',
)

let state = createReportingPeriodContextState(principalA)
let token = reportingPeriodLoadToken(state)
state = applyReportingPeriodLoadSuccess(state, token, periods, currentDate)
assertEqual(state.selectedId, 'current', 'initial load selects the unique current period')

state = selectValidatedReportingPeriod(state, 'reopened-past')
const samePrincipal = { ...principalA, name: 'Updated display only' }
state = transitionReportingPeriodAuthenticationContext(state, samePrincipal)
token = reportingPeriodLoadToken(state)
state = applyReportingPeriodLoadSuccess(state, token, periods, currentDate)
assertEqual(
  state.selectedId,
  'reopened-past',
  'same principal reload retains an explicit historical period',
)

const beforeLogoutToken = reportingPeriodLoadToken(state)
state = transitionReportingPeriodAuthenticationContext(state, null)
assertEqual(state.periods.length, 0, 'logout clears the reporting-period list')
assertEqual(state.selectedId, '', 'logout clears the selected period')
const afterStaleLogoutCompletion = applyReportingPeriodLoadSuccess(
  state,
  beforeLogoutToken,
  periods,
  currentDate,
)
assertEqual(afterStaleLogoutCompletion.periods.length, 0, 'a stale pre-logout response cannot restore the list')
assertEqual(afterStaleLogoutCompletion.selectedId, '', 'a stale pre-logout response cannot restore selection')

state = transitionReportingPeriodAuthenticationContext(state, principalB)
token = reportingPeriodLoadToken(state)
state = applyReportingPeriodLoadSuccess(state, token, periods, currentDate)
assertEqual(state.selectedId, 'current', 'a new principal receives the current default, not the prior future selection')

state = selectValidatedReportingPeriod(state, 'reopened-past')
state = transitionReportingPeriodAuthenticationContext(state, {
  ...principalB,
  role: 'master_admin',
  adminLevel: 'master',
  programmeScope: [],
})
assertEqual(state.selectedId, '', 'role or admin-level changes clear the prior selection')

state = createReportingPeriodContextState(principalB)
token = reportingPeriodLoadToken(state)
state = applyReportingPeriodLoadSuccess(state, token, periods, currentDate)
state = selectValidatedReportingPeriod(state, 'reopened-past')
state = transitionReportingPeriodAuthenticationContext(state, {
  ...principalB,
  programmeScope: ['DR', 'GERI'],
})
assertEqual(state.selectedId, '', 'programme-scope changes clear the prior selection')

state = createReportingPeriodContextState(principalA)
token = reportingPeriodLoadToken(state)
state = applyReportingPeriodLoadSuccess(state, token, periods, currentDate)
state = selectValidatedReportingPeriod(state, 'future-active')
token = reportingPeriodLoadToken(state)
state = applyReportingPeriodLoadFailure(state, token)
assertEqual(state.periods.length, 0, 'load failure clears the period list')
assertEqual(state.selectedId, '', 'load failure clears the selected period')

state = createReportingPeriodContextState(principalA)
token = reportingPeriodLoadToken(state)
state = applyReportingPeriodLoadSuccess(
  state,
  token,
  [{ ...periods[1], id: '' }],
  currentDate,
)
assertEqual(state.periods.length, 0, 'an invalid period response clears the period list')
assertEqual(state.selectedId, '', 'an invalid period response cannot establish a selection')

state = createReportingPeriodContextState(principalA)
token = reportingPeriodLoadToken(state)
state = applyReportingPeriodLoadSuccess(
  state,
  token,
  periods.filter((period) => period.id !== 'current'),
  currentDate,
)
assertEqual(state.selectedId, '', 'no current applicable period has no unsafe fallback')

const staleCalls: string[] = []
const staleResult = await withValidatedReportingPeriod(periods, 'missing-period', async (period) => {
  staleCalls.push(period.id)
  return ['event']
})
assertEqual(staleResult, undefined, 'an unvalidated PC period produces no operation result')
assertEqual(staleCalls.length, 0, 'an unvalidated PC period makes zero operational calls')

for (const explicitId of ['reopened-past', 'future-active', 'inactive-history']) {
  const calls: string[] = []
  const result = await withValidatedReportingPeriod(periods, explicitId, async (period) => {
    calls.push(period.id)
    return ['event']
  })
  assertEqual(result?.length, 1, `${explicitId} remains available when explicitly selected`)
  assertEqual(calls.length, 1, `${explicitId} makes one validated scoped call`)
}
