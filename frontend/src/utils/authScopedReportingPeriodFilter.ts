import type { ReportingPeriodOption } from '../types/upload'

interface ValidatedReportingPeriodFilter {
  isValid: boolean
  reportingPeriodId?: string
}

export const revalidateReportingPeriodFilterId = (
  periods: ReportingPeriodOption[],
  localReportingPeriodId: string,
  sharedReportingPeriodId: string,
): string => {
  if (localReportingPeriodId && periods.some((period) => period.id === localReportingPeriodId)) {
    return localReportingPeriodId
  }
  return sharedReportingPeriodId && periods.some((period) => period.id === sharedReportingPeriodId)
    ? sharedReportingPeriodId
    : ''
}

const validateReportingPeriodFilter = (
  periods: ReportingPeriodOption[],
  reportingPeriodId: string,
): ValidatedReportingPeriodFilter => {
  if (!reportingPeriodId) {
    return { isValid: true }
  }
  return periods.some((period) => period.id === reportingPeriodId)
    ? { isValid: true, reportingPeriodId }
    : { isValid: false }
}

export interface AuthScopedReportingPageState<Filters, Row, Summary, Detail, DetailError> {
  authenticationContextVersion: string
  authenticationResetPending: boolean
  filters: Filters
  rows: Row[]
  summary: Summary
  total: number
  offset: number
  selectedRow: Row | null
  selectedDetail: Detail | null
  detailError: DetailError | null
  detailId: string
}

export type AuthScopedReportingPageAction<Filters, Row, Summary, Detail, DetailError> =
  | {
      type: 'authentication-context-changed'
      authenticationContextVersion: string
      filters: Filters
      summary: Summary
    }
  | { type: 'authentication-reset-completed' }
  | { type: 'invalid-reporting-period'; summary: Summary }
  | {
      type: 'merge'
      changes:
        | Partial<AuthScopedReportingPageState<Filters, Row, Summary, Detail, DetailError>>
        | ((
            state: AuthScopedReportingPageState<Filters, Row, Summary, Detail, DetailError>,
          ) => Partial<AuthScopedReportingPageState<Filters, Row, Summary, Detail, DetailError>>)
    }

export const createAuthScopedReportingPageState = <Filters, Row, Summary, Detail, DetailError>(
  authenticationContextVersion: string,
  filters: Filters,
  summary: Summary,
  detailId = '',
): AuthScopedReportingPageState<Filters, Row, Summary, Detail, DetailError> => ({
  authenticationContextVersion,
  authenticationResetPending: false,
  filters,
  rows: [],
  summary,
  total: 0,
  offset: 0,
  selectedRow: null,
  selectedDetail: null,
  detailError: null,
  detailId,
})

export const authScopedReportingPageReducer = <Filters, Row, Summary, Detail, DetailError>(
  state: AuthScopedReportingPageState<Filters, Row, Summary, Detail, DetailError>,
  action: AuthScopedReportingPageAction<Filters, Row, Summary, Detail, DetailError>,
): AuthScopedReportingPageState<Filters, Row, Summary, Detail, DetailError> => {
  if (action.type === 'authentication-context-changed') {
    return {
      ...createAuthScopedReportingPageState<Filters, Row, Summary, Detail, DetailError>(
        action.authenticationContextVersion,
        action.filters,
        action.summary,
      ),
      authenticationResetPending: true,
    }
  }
  if (action.type === 'authentication-reset-completed') {
    return { ...state, authenticationResetPending: false }
  }
  if (action.type === 'invalid-reporting-period') {
    return {
      ...state,
      rows: [],
      summary: action.summary,
      total: 0,
      offset: 0,
      selectedRow: null,
      selectedDetail: null,
      detailError: null,
      detailId: '',
    }
  }
  const changes = typeof action.changes === 'function' ? action.changes(state) : action.changes
  return { ...state, ...changes }
}

export type AuthScopedRequestResult<T> =
  | { status: 'success'; value: T }
  | { status: 'invalid-period' }
  | { status: 'stale' }
  | { status: 'error'; error: unknown }

export class AuthScopedReportingPageRequestController {
  private authenticationContextVersion: string
  private listRequestVersion = 0
  private detailRequestVersion = 0

  constructor(authenticationContextVersion: string) {
    this.authenticationContextVersion = authenticationContextVersion
  }

  synchronizeAuthenticationContext(authenticationContextVersion: string): boolean {
    if (authenticationContextVersion === this.authenticationContextVersion) {
      return false
    }
    this.authenticationContextVersion = authenticationContextVersion
    this.invalidateAll()
    return true
  }

  invalidateAll() {
    this.listRequestVersion += 1
    this.detailRequestVersion += 1
  }

  invalidateList() {
    this.listRequestVersion += 1
  }

  invalidateDetail() {
    this.detailRequestVersion += 1
  }

  async runListRequest<T>(
    periods: ReportingPeriodOption[],
    reportingPeriodId: string,
    request: (reportingPeriodId?: string) => Promise<T>,
  ): Promise<AuthScopedRequestResult<T>> {
    const periodFilter = validateReportingPeriodFilter(periods, reportingPeriodId)
    const requestVersion = this.listRequestVersion + 1
    this.listRequestVersion = requestVersion
    const authenticationContextVersion = this.authenticationContextVersion
    if (!periodFilter.isValid) {
      this.invalidateDetail()
      return { status: 'invalid-period' }
    }
    try {
      const value = await request(periodFilter.reportingPeriodId)
      return this.isListRequestCurrent(authenticationContextVersion, requestVersion)
        ? { status: 'success', value }
        : { status: 'stale' }
    } catch (error) {
      return this.isListRequestCurrent(authenticationContextVersion, requestVersion)
        ? { status: 'error', error }
        : { status: 'stale' }
    }
  }

  async runDetailRequest<T>(request: () => Promise<T>): Promise<AuthScopedRequestResult<T>> {
    const requestVersion = this.detailRequestVersion + 1
    this.detailRequestVersion = requestVersion
    const authenticationContextVersion = this.authenticationContextVersion
    try {
      const value = await request()
      return this.isDetailRequestCurrent(authenticationContextVersion, requestVersion)
        ? { status: 'success', value }
        : { status: 'stale' }
    } catch (error) {
      return this.isDetailRequestCurrent(authenticationContextVersion, requestVersion)
        ? { status: 'error', error }
        : { status: 'stale' }
    }
  }

  private isListRequestCurrent(authenticationContextVersion: string, requestVersion: number) {
    return authenticationContextVersion === this.authenticationContextVersion
      && requestVersion === this.listRequestVersion
  }

  private isDetailRequestCurrent(authenticationContextVersion: string, requestVersion: number) {
    return authenticationContextVersion === this.authenticationContextVersion
      && requestVersion === this.detailRequestVersion
  }
}
