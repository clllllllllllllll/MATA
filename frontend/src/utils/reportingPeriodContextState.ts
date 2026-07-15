import type { AuthIdentity } from '../types/auth'
import type { ReportingPeriodOption } from '../types/upload'
import {
  isReportingPeriodStatus,
  isStrictIsoCalendarDate,
  parseCalendarDate,
  retainOrSelectReportingPeriodId,
} from './reportingPeriods.ts'

export interface ReportingPeriodContextState {
  authenticationContextKey: string
  authenticationGeneration: number
  periods: ReportingPeriodOption[]
  selectedId: string
}

export interface ReportingPeriodLoadToken {
  authenticationContextKey: string
  authenticationGeneration: number
}

const sortedUnique = (values: string[]): string[] =>
  Array.from(new Set(values.map((value) => value.trim()).filter(Boolean))).sort()

export const reportingPeriodAuthenticationContextKey = (
  identity: AuthIdentity | null,
): string => {
  if (!identity) {
    return 'unauthenticated'
  }
  const adminLevel = 'adminLevel' in identity ? identity.adminLevel : ''
  const programmeScope = 'programmeScope' in identity
    ? sortedUnique(identity.programmeScope)
    : []
  const operationalScope = 'postingCode' in identity
    ? identity.postingCode
    : 'programmeCode' in identity
      ? identity.programmeCode
      : 'homeCluster' in identity
        ? identity.homeCluster
        : ''
  return JSON.stringify([
    identity.subjectId,
    identity.role,
    adminLevel,
    programmeScope,
    operationalScope,
  ])
}

export const createReportingPeriodContextState = (
  identity: AuthIdentity | null,
): ReportingPeriodContextState => ({
  authenticationContextKey: reportingPeriodAuthenticationContextKey(identity),
  authenticationGeneration: 0,
  periods: [],
  selectedId: '',
})

export const transitionReportingPeriodAuthenticationContext = (
  state: ReportingPeriodContextState,
  identity: AuthIdentity | null,
): ReportingPeriodContextState => {
  const authenticationContextKey = reportingPeriodAuthenticationContextKey(identity)
  if (authenticationContextKey === state.authenticationContextKey) {
    return state
  }
  return {
    authenticationContextKey,
    authenticationGeneration: state.authenticationGeneration + 1,
    periods: [],
    selectedId: '',
  }
}

export const reportingPeriodLoadToken = (
  state: ReportingPeriodContextState,
): ReportingPeriodLoadToken => ({
  authenticationContextKey: state.authenticationContextKey,
  authenticationGeneration: state.authenticationGeneration,
})

export const isReportingPeriodLoadCurrent = (
  state: ReportingPeriodContextState,
  token: ReportingPeriodLoadToken,
): boolean =>
  state.authenticationContextKey === token.authenticationContextKey
  && state.authenticationGeneration === token.authenticationGeneration

export const isValidReportingPeriodList = (
  periods: ReportingPeriodOption[],
): boolean => {
  const ids = new Set<string>()
  return periods.every((period) => {
    const id = period.id.trim()
    const start = parseCalendarDate(period.startDate)
    const end = parseCalendarDate(period.endDate)
    if (
      !id
      || ids.has(id)
      || !period.label.trim()
      || !Number.isFinite(start.getTime())
      || !Number.isFinite(end.getTime())
      || start > end
      || !isReportingPeriodStatus(period.status)
      || !isStrictIsoCalendarDate(period.startDate)
      || !isStrictIsoCalendarDate(period.endDate)
      || (period.activateOn != null && !isStrictIsoCalendarDate(period.activateOn))
      || (period.deactivateOn != null && !isStrictIsoCalendarDate(period.deactivateOn))
    ) {
      return false
    }
    ids.add(id)
    return true
  })
}

export const applyReportingPeriodLoadSuccess = (
  state: ReportingPeriodContextState,
  token: ReportingPeriodLoadToken,
  periods: ReportingPeriodOption[],
  asOf: Date = new Date(),
): ReportingPeriodContextState => {
  if (!isReportingPeriodLoadCurrent(state, token)) {
    return state
  }
  const validatedPeriods = isValidReportingPeriodList(periods) ? periods : []
  return {
    ...state,
    periods: validatedPeriods,
    selectedId: retainOrSelectReportingPeriodId(validatedPeriods, state.selectedId, asOf),
  }
}

export const applyReportingPeriodLoadFailure = (
  state: ReportingPeriodContextState,
  token: ReportingPeriodLoadToken,
): ReportingPeriodContextState =>
  isReportingPeriodLoadCurrent(state, token)
    ? { ...state, periods: [], selectedId: '' }
    : state

export const selectValidatedReportingPeriod = (
  state: ReportingPeriodContextState,
  selectedId: string,
): ReportingPeriodContextState => ({
  ...state,
  selectedId:
    selectedId && state.periods.some((period) => period.id === selectedId)
      ? selectedId
      : '',
})
