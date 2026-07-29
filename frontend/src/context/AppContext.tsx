import {
  useEffect,
  useCallback,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react'
import { frontendConfig } from '../config/frontendConfig'
import type { AppRole } from '../types/app'
import type { UploadMeta } from '../types/upload'
import {
  AppStateContext,
  type AppStateContextValue,
  type UploadResultInput,
} from './appStateContext'
import {
  clearUploadHistory,
  loadUploadHistory,
  saveUploadHistory,
} from '../utils/storage'
import {
  makeUploadMeta,
} from '../utils/warnings'
import {
  authSessionChangedEvent,
  isAuthSessionFenceCurrent,
  readStoredAuthSession,
} from '../api/auth'
import { listReportingPeriods } from '../api/reportingPeriods'
import { listSecretaryReportingPeriods } from '../api/secretaryEvents'
import { formatUserFacingApiError } from '../utils/userFacingErrors'
import type { AuthIdentity } from '../types/auth'
import {
  clearMemoryCache,
  clearMemoryCacheResource,
  makeScopedCacheKey,
  readThroughMemoryCache,
  type CacheScope,
} from '../utils/memoryReadCache'
import {
  applyReportingPeriodLoadFailure,
  applyReportingPeriodLoadSuccess,
  createReportingPeriodContextState,
  isReportingPeriodLoadCurrent,
  reportingPeriodLoadToken,
  selectValidatedReportingPeriod,
  transitionReportingPeriodAuthenticationContext,
  type ReportingPeriodContextState,
} from '../utils/reportingPeriodContextState'

const canIdentityLoadReportingPeriodData = (identity: AuthIdentity | null): boolean => {
  if (!identity) {
    return false
  }
  if (identity.role === 'master_admin') {
    return true
  }
  if (identity.role === 'secretary') {
    return true
  }
  return identity.role === 'programme_pc' && identity.programmeScope.length > 0
}

const reportingPeriodProgrammeScope = (identity: AuthIdentity | null): string[] => {
  if (identity?.role === 'master_admin' || identity?.role === 'programme_pc') {
    return identity.programmeScope
  }
  return []
}

export const AppStateProvider = ({ children }: PropsWithChildren) => {
  const [role, setRole] = useState<AppRole>(frontendConfig.defaultRole)
  const roleRef = useRef(role)
  const [sessionIdentity, setSessionIdentity] = useState<AuthIdentity | null>(
    () => readStoredAuthSession()?.identity ?? null,
  )
  const canLoadReportingPeriodData = canIdentityLoadReportingPeriodData(sessionIdentity)
  const [selectedProgrammeCode, setSelectedProgrammeCode] = useState<string>(
    frontendConfig.defaultProgrammeCode,
  )
  const [reportingPeriodContext, setReportingPeriodContext] = useState<ReportingPeriodContextState>(
    () => createReportingPeriodContextState(sessionIdentity),
  )
  const reportingPeriodContextRef = useRef(reportingPeriodContext)
  const reportingPeriodRequestVersionRef = useRef(0)
  const reportingPeriodId = reportingPeriodContext.selectedId
  const reportingPeriods = reportingPeriodContext.periods
  const reportingPeriodAuthenticationContextVersion = JSON.stringify([
    reportingPeriodContext.authenticationContextKey,
    reportingPeriodContext.authenticationGeneration,
  ])
  const [reportingPeriodsLoading, setReportingPeriodsLoading] = useState(canLoadReportingPeriodData)
  const [reportingPeriodsError, setReportingPeriodsError] = useState<string | null>(null)
  const [uploadHistory, setUploadHistory] = useState<UploadMeta[]>(loadUploadHistory)

  const clearUploadState = useCallback(() => {
    clearUploadHistory()
    setUploadHistory([])
  }, [])

  const updateReportingPeriodContext = useCallback(
    (transition: (state: ReportingPeriodContextState) => ReportingPeriodContextState) => {
      const next = transition(reportingPeriodContextRef.current)
      reportingPeriodContextRef.current = next
      setReportingPeriodContext(next)
      return next
    },
    [],
  )

  const invalidateReportingPeriodRequests = useCallback(() => {
    reportingPeriodRequestVersionRef.current += 1
  }, [])

  const adminCacheScope = useMemo<CacheScope>(() => ({
    role,
    userId: sessionIdentity?.subjectId ?? frontendConfig.demoAdminId,
    programmeScope:
      sessionIdentity?.role === 'master_admin' || sessionIdentity?.role === 'programme_pc'
        ? sessionIdentity.programmeScope
        : [],
    postingCode: sessionIdentity?.role === 'secretary'
      ? sessionIdentity.postingCode
      : undefined,
    residentId:
      sessionIdentity?.role === 'resident' || sessionIdentity?.role === 'external_resident'
        ? sessionIdentity.subjectId
        : undefined,
  }), [role, sessionIdentity])

  const updateRole = useCallback((nextRole: AppRole) => {
    clearMemoryCache()
    if (nextRole !== roleRef.current) {
      roleRef.current = nextRole
      invalidateReportingPeriodRequests()
      updateReportingPeriodContext((state) => ({
        ...state,
        authenticationGeneration: state.authenticationGeneration + 1,
        periods: [],
        selectedId: '',
      }))
    }
    setRole(nextRole)
  }, [invalidateReportingPeriodRequests, updateReportingPeriodContext])

  const updateSelectedProgrammeCode = useCallback((programmeCode: string) => {
    clearMemoryCache()
    setSelectedProgrammeCode(programmeCode)
  }, [])

  const fetchReportingPeriods = useCallback(
    async () => {
      if (!canLoadReportingPeriodData) {
        return []
      }
      const { data } = await readThroughMemoryCache(
        makeScopedCacheKey(adminCacheScope, 'admin.reporting-periods.list', {}),
        () => sessionIdentity?.role === 'secretary'
          ? listSecretaryReportingPeriods()
          : listReportingPeriods({
              adminId: sessionIdentity?.subjectId ?? frontendConfig.demoAdminId,
              adminProgrammes: reportingPeriodProgrammeScope(sessionIdentity),
            }),
      )
      return data
    },
    [adminCacheScope, canLoadReportingPeriodData, sessionIdentity],
  )

  const reloadReportingPeriods = useCallback(async () => {
    const loadToken = reportingPeriodLoadToken(reportingPeriodContextRef.current)
    const requestVersion = reportingPeriodRequestVersionRef.current + 1
    reportingPeriodRequestVersionRef.current = requestVersion
    setReportingPeriodsLoading(true)
    setReportingPeriodsError(null)
    if (!canLoadReportingPeriodData) {
      updateReportingPeriodContext((state) => applyReportingPeriodLoadFailure(state, loadToken))
      setReportingPeriodsLoading(false)
      return
    }
    try {
      clearMemoryCache((key) => key === makeScopedCacheKey(adminCacheScope, 'admin.reporting-periods.list', {}))
      const periods = await fetchReportingPeriods()
      if (
        requestVersion !== reportingPeriodRequestVersionRef.current
        || !isReportingPeriodLoadCurrent(reportingPeriodContextRef.current, loadToken)
      ) {
        return
      }
      updateReportingPeriodContext((state) => applyReportingPeriodLoadSuccess(state, loadToken, periods))
    } catch (error) {
      if (
        requestVersion !== reportingPeriodRequestVersionRef.current
        || !isReportingPeriodLoadCurrent(reportingPeriodContextRef.current, loadToken)
      ) {
        return
      }
      const message = formatUserFacingApiError(error, {
        fallbackMessage: 'Reporting periods could not be loaded. Try refreshing the page.',
      })
      setReportingPeriodsError(message)
      updateReportingPeriodContext((state) => applyReportingPeriodLoadFailure(state, loadToken))
    } finally {
      if (
        requestVersion === reportingPeriodRequestVersionRef.current
        && isReportingPeriodLoadCurrent(reportingPeriodContextRef.current, loadToken)
      ) {
        setReportingPeriodsLoading(false)
      }
    }
  }, [adminCacheScope, canLoadReportingPeriodData, fetchReportingPeriods, updateReportingPeriodContext])

  useEffect(() => {
    if (!canLoadReportingPeriodData) {
      return
    }
    let active = true
    const loadToken = reportingPeriodLoadToken(reportingPeriodContextRef.current)
    const requestVersion = reportingPeriodRequestVersionRef.current + 1
    reportingPeriodRequestVersionRef.current = requestVersion
    ;(async () => {
      try {
        const periods = await fetchReportingPeriods()
        if (
          !active
          || requestVersion !== reportingPeriodRequestVersionRef.current
          || !isReportingPeriodLoadCurrent(reportingPeriodContextRef.current, loadToken)
        ) {
          return
        }
        setReportingPeriodsError(null)
        updateReportingPeriodContext((state) => applyReportingPeriodLoadSuccess(state, loadToken, periods))
      } catch (error) {
        if (
          !active
          || requestVersion !== reportingPeriodRequestVersionRef.current
          || !isReportingPeriodLoadCurrent(reportingPeriodContextRef.current, loadToken)
        ) {
          return
        }
        const message = formatUserFacingApiError(error, {
          fallbackMessage: 'Reporting periods could not be loaded. Try refreshing the page.',
        })
        setReportingPeriodsError(message)
        updateReportingPeriodContext((state) => applyReportingPeriodLoadFailure(state, loadToken))
      } finally {
        if (
          active
          && requestVersion === reportingPeriodRequestVersionRef.current
          && isReportingPeriodLoadCurrent(reportingPeriodContextRef.current, loadToken)
        ) {
          setReportingPeriodsLoading(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [canLoadReportingPeriodData, fetchReportingPeriods, updateReportingPeriodContext])

  useEffect(() => {
    const onAuthSessionChanged = () => {
      const nextIdentity = readStoredAuthSession()?.identity ?? null
      const previousContext = reportingPeriodContextRef.current
      const nextContext = transitionReportingPeriodAuthenticationContext(previousContext, nextIdentity)
      if (!nextIdentity || nextContext !== previousContext) {
        clearUploadState()
      }
      if (nextContext !== previousContext) {
        invalidateReportingPeriodRequests()
        reportingPeriodContextRef.current = nextContext
        setReportingPeriodContext(nextContext)
        setReportingPeriodsError(null)
        setReportingPeriodsLoading(canIdentityLoadReportingPeriodData(nextIdentity))
      }
      setSessionIdentity(nextIdentity)
      if (!canIdentityLoadReportingPeriodData(nextIdentity)) {
        setReportingPeriodsLoading(false)
      }
    }
    window.addEventListener(authSessionChangedEvent, onAuthSessionChanged)
    return () => window.removeEventListener(authSessionChangedEvent, onAuthSessionChanged)
  }, [clearUploadState, invalidateReportingPeriodRequests])

  const updateReportingPeriodId = useCallback((selectedId: string) => {
    updateReportingPeriodContext((state) => selectValidatedReportingPeriod(state, selectedId))
  }, [updateReportingPeriodContext])

  const reportingPeriodLabel = useMemo(
    () => reportingPeriods.find((item) => item.id === reportingPeriodId)?.label,
    [reportingPeriods, reportingPeriodId],
  )

  const addUploadResult = useCallback((input: UploadResultInput): UploadMeta | null => {
    if (!isAuthSessionFenceCurrent(input.authSessionFence)) {
      return null
    }
    clearMemoryCacheResource('admin.upload-logs.list')
    clearMemoryCacheResource('admin.upload-warnings.list')
    clearMemoryCacheResource('admin.parsed-data')
    clearMemoryCacheResource('admin.upload-logs.rdb-source-list')
    const uploadMeta = makeUploadMeta({
      uploadType: input.uploadType,
      response: input.response,
      filename: input.filename,
      reportingPeriodId: input.reportingPeriodId,
      reportingPeriodLabel: input.reportingPeriodLabel,
      programmeCode: input.programmeCode,
    })

    setUploadHistory((prev) => {
      const next = [uploadMeta, ...prev].slice(0, 40)
      saveUploadHistory(next)
      return next
    })

    return uploadMeta
  }, [])

  const value = useMemo<AppStateContextValue>(
    () => ({
      role,
      setRole: updateRole,
      selectedProgrammeCode,
      setSelectedProgrammeCode: updateSelectedProgrammeCode,
      reportingPeriodId,
      setReportingPeriodId: updateReportingPeriodId,
      reportingPeriodLabel,
      reportingPeriodAuthenticationContextVersion,
      reportingPeriods,
      reportingPeriodsLoading,
      reportingPeriodsError,
      reloadReportingPeriods,
      demoAdminId: frontendConfig.demoAdminId,
      demoAdminProgrammes: frontendConfig.demoAdminProgrammes,
      authCacheScope: adminCacheScope,
      uploadHistory,
      addUploadResult,
    }),
    [
      role,
      selectedProgrammeCode,
      reportingPeriodId,
      reportingPeriodLabel,
      reportingPeriodAuthenticationContextVersion,
      reportingPeriods,
      reportingPeriodsLoading,
      reportingPeriodsError,
      reloadReportingPeriods,
      uploadHistory,
      addUploadResult,
      adminCacheScope,
      updateRole,
      updateReportingPeriodId,
      updateSelectedProgrammeCode,
    ],
  )

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}
