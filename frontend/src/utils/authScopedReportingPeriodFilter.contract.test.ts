import assert from 'node:assert/strict'
import test from 'node:test'
import type { ReportingPeriodOption } from '../types/upload.ts'
import {
  AuthScopedReportingPageRequestController,
  authScopedReportingPageReducer,
  createAuthScopedReportingPageState,
  revalidateReportingPeriodFilterId,
  type AuthScopedReportingPageState,
} from './authScopedReportingPeriodFilter.ts'

interface TestFilters {
  reportingPeriodId: string
  programmeCode: string
  postingCode: string
}

interface TestRow {
  id: string
}

interface TestSummary {
  count: number
}

interface TestDetail extends TestRow {
  loaded: true
}

interface TestDetailError {
  id: string
  message: string
}

type TestPageState = AuthScopedReportingPageState<
  TestFilters,
  TestRow,
  TestSummary,
  TestDetail,
  TestDetailError
>

const periods: ReportingPeriodOption[] = [
  {
    id: 'current',
    label: 'Current',
    startDate: '2026-07-01',
    endDate: '2026-12-31',
    status: 'active',
  },
  {
    id: 'history',
    label: 'Historical',
    startDate: '2025-01-01',
    endDate: '2025-06-30',
    status: 'inactive',
  },
  {
    id: 'future-test',
    label: 'Future test',
    startDate: '2099-01-01',
    endDate: '2099-06-30',
    status: 'active',
  },
]

const filters = (reportingPeriodId: string, programmeCode = 'all'): TestFilters => ({
  reportingPeriodId,
  programmeCode,
  postingCode: 'all',
})

const emptySummary = (): TestSummary => ({ count: 0 })

const loadedState = (authenticationContextVersion: string): TestPageState =>
  authScopedReportingPageReducer(
    createAuthScopedReportingPageState<TestFilters, TestRow, TestSummary, TestDetail, TestDetailError>(
      authenticationContextVersion,
      filters('history', 'OLD'),
      emptySummary(),
      'detail-old',
    ),
    {
      type: 'merge',
      changes: {
        rows: [{ id: 'row-old' }],
        summary: { count: 7 },
        total: 7,
        offset: 25,
        selectedRow: { id: 'row-old' },
        selectedDetail: { id: 'detail-old', loaded: true },
        detailError: { id: 'detail-old', message: 'old error' },
      },
    },
  )

const deferred = <T,>() => {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const registerPageBehaviorTests = (pageName: string) => {
  test(`${pageName}: retains a valid historical filter and sends one scoped request`, async () => {
    const state = loadedState('principal-a')
    const controller = new AuthScopedReportingPageRequestController('principal-a')
    assert.equal(controller.synchronizeAuthenticationContext('principal-a'), false)
    assert.equal(
      revalidateReportingPeriodFilterId(periods, state.filters.reportingPeriodId, 'current'),
      'history',
    )

    const calls: Array<string | undefined> = []
    const result = await controller.runListRequest(
      periods,
      state.filters.reportingPeriodId,
      async (reportingPeriodId) => {
        calls.push(reportingPeriodId)
        return [{ id: 'historical-row' }]
      },
    )

    assert.deepEqual(calls, ['history'])
    assert.equal(result.status, 'success')
  })

  test(`${pageName}: retains an explicitly selected future period in the same context`, () => {
    assert.equal(
      revalidateReportingPeriodFilterId(periods, 'future-test', 'current'),
      'future-test',
    )
  })

  test(`${pageName}: principal change clears page data, pagination, selection, detail, and URL state`, () => {
    const controller = new AuthScopedReportingPageRequestController('principal-a')
    assert.equal(controller.synchronizeAuthenticationContext('principal-b'), true)
    const reset = authScopedReportingPageReducer(loadedState('principal-a'), {
      type: 'authentication-context-changed',
      authenticationContextVersion: 'principal-b',
      filters: filters('current', 'NEW'),
      summary: emptySummary(),
    })

    assert.equal(reset.authenticationResetPending, true)
    assert.equal(reset.filters.reportingPeriodId, 'current')
    assert.equal(reset.filters.programmeCode, 'NEW')
    assert.deepEqual(reset.rows, [])
    assert.deepEqual(reset.summary, emptySummary())
    assert.equal(reset.total, 0)
    assert.equal(reset.offset, 0)
    assert.equal(reset.selectedRow, null)
    assert.equal(reset.selectedDetail, null)
    assert.equal(reset.detailError, null)
    assert.equal(reset.detailId, '')
  })

  test(`${pageName}: programme-scope change clears the old filter and results`, () => {
    const reset = authScopedReportingPageReducer(loadedState('principal-a:OLD'), {
      type: 'authentication-context-changed',
      authenticationContextVersion: 'principal-a:NEW',
      filters: filters('', 'NEW'),
      summary: emptySummary(),
    })

    assert.equal(reset.authenticationContextVersion, 'principal-a:NEW')
    assert.equal(reset.filters.reportingPeriodId, '')
    assert.equal(reset.filters.programmeCode, 'NEW')
    assert.deepEqual(reset.rows, [])
    assert.equal(reset.total, 0)
  })

  test(`${pageName}: invalid non-empty period makes zero API calls and clears stale state`, async () => {
    const controller = new AuthScopedReportingPageRequestController('principal-a')
    let requestCount = 0
    const result = await controller.runListRequest(periods, 'missing', async () => {
      requestCount += 1
      return [{ id: 'unsafe-row' }]
    })
    const cleared = authScopedReportingPageReducer(loadedState('principal-a'), {
      type: 'invalid-reporting-period',
      summary: emptySummary(),
    })

    assert.equal(result.status, 'invalid-period')
    assert.equal(requestCount, 0)
    assert.deepEqual(cleared.rows, [])
    assert.equal(cleared.total, 0)
    assert.equal(cleared.offset, 0)
    assert.equal(cleared.selectedRow, null)
    assert.equal(cleared.selectedDetail, null)
    assert.equal(cleared.detailId, '')
  })

  test(`${pageName}: new context seeds and requests only its shared period`, async () => {
    const previous = authScopedReportingPageReducer(loadedState('principal-a'), {
      type: 'merge',
      changes: { filters: filters('future-test', 'OLD') },
    })
    const reset = authScopedReportingPageReducer(previous, {
      type: 'authentication-context-changed',
      authenticationContextVersion: 'principal-b',
      filters: filters('current', 'NEW'),
      summary: emptySummary(),
    })

    assert.equal(reset.filters.reportingPeriodId, 'current')
    assert.notEqual(reset.filters.reportingPeriodId, 'future-test')
    const controller = new AuthScopedReportingPageRequestController('principal-b')
    const calls: Array<string | undefined> = []
    await controller.runListRequest(periods, reset.filters.reportingPeriodId, async (periodId) => {
      calls.push(periodId)
      return []
    })
    assert.deepEqual(calls, ['current'])
    assert.equal(calls.includes('future-test'), false)
  })

  test(`${pageName}: stale prior-principal list response cannot restore rows or totals`, async () => {
    const pending = deferred<TestRow[]>()
    const controller = new AuthScopedReportingPageRequestController('principal-a')
    const request = controller.runListRequest(periods, 'history', async () => pending.promise)
    assert.equal(controller.synchronizeAuthenticationContext('principal-b'), true)
    const reset = authScopedReportingPageReducer(loadedState('principal-a'), {
      type: 'authentication-context-changed',
      authenticationContextVersion: 'principal-b',
      filters: filters('current', 'NEW'),
      summary: emptySummary(),
    })
    pending.resolve([{ id: 'late-old-row' }])

    assert.equal((await request).status, 'stale')
    assert.deepEqual(reset.rows, [])
    assert.equal(reset.total, 0)
  })

  test(`${pageName}: stale prior-principal detail response cannot reopen the drawer`, async () => {
    const pending = deferred<TestDetail>()
    const controller = new AuthScopedReportingPageRequestController('principal-a')
    const request = controller.runDetailRequest(async () => pending.promise)
    assert.equal(controller.synchronizeAuthenticationContext('principal-b'), true)
    const reset = authScopedReportingPageReducer(loadedState('principal-a'), {
      type: 'authentication-context-changed',
      authenticationContextVersion: 'principal-b',
      filters: filters('current', 'NEW'),
      summary: emptySummary(),
    })
    pending.resolve({ id: 'late-old-detail', loaded: true })

    assert.equal((await request).status, 'stale')
    assert.equal(reset.selectedRow, null)
    assert.equal(reset.selectedDetail, null)
    assert.equal(reset.detailId, '')
  })

  test(`${pageName}: stale prior-principal mutation cannot update the new context`, async () => {
    const pending = deferred<{ deleted: true }>()
    const controller = new AuthScopedReportingPageRequestController('principal-a')
    const request = controller.runMutationRequest(async () => pending.promise)
    assert.equal(controller.synchronizeAuthenticationContext('principal-b'), true)
    pending.resolve({ deleted: true })

    assert.equal((await request).status, 'stale')
  })
}

registerPageBehaviorTests('Admin Resident Submissions')
registerPageBehaviorTests('Admin Secretary Events')
