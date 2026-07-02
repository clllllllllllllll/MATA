import {
  useEffect,
  useCallback,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react'
import { frontendConfig } from '../config/frontendConfig'
import type { AppRole } from '../types/app'
import type { ReportingPeriodOption, UploadMeta } from '../types/upload'
import {
  AppStateContext,
  type AppStateContextValue,
  type UploadResultInput,
} from './appStateContext'
import {
  loadUploadHistory,
  saveUploadHistory,
} from '../utils/storage'
import {
  makeUploadMeta,
} from '../utils/warnings'
import { authSessionChangedEvent, readStoredAuthSession } from '../api/auth'
import { listReportingPeriods } from '../api/reportingPeriods'
import { ApiRequestError } from '../api/http'
import type { AuthIdentity } from '../types/auth'
import {
  clearMemoryCache,
  clearMemoryCacheResource,
  makeScopedCacheKey,
  readThroughMemoryCache,
  type CacheScope,
} from '../utils/memoryReadCache'

const canIdentityLoadReportingPeriodData = (identity: AuthIdentity | null): boolean => {
  if (!identity) {
    return false
  }
  if (identity.role === 'master_admin') {
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
  const [sessionIdentity, setSessionIdentity] = useState<AuthIdentity | null>(
    () => readStoredAuthSession()?.identity ?? null,
  )
  const canLoadReportingPeriodData = canIdentityLoadReportingPeriodData(sessionIdentity)
  const [selectedProgrammeCode, setSelectedProgrammeCode] = useState<string>(
    frontendConfig.defaultProgrammeCode,
  )
  const [reportingPeriodId, setReportingPeriodId] = useState<string>(
    frontendConfig.defaultReportingPeriodId,
  )
  const [reportingPeriods, setReportingPeriods] = useState<ReportingPeriodOption[]>([])
  const [reportingPeriodsLoading, setReportingPeriodsLoading] = useState(canLoadReportingPeriodData)
  const [reportingPeriodsError, setReportingPeriodsError] = useState<string | null>(null)
  const [uploadHistory, setUploadHistory] = useState<UploadMeta[]>(loadUploadHistory)

  const adminCacheScope = useMemo<CacheScope>(() => ({
    role,
    userId: sessionIdentity?.subjectId ?? frontendConfig.demoAdminId,
    programmeScope:
      sessionIdentity?.role === 'master_admin' || sessionIdentity?.role === 'programme_pc'
        ? sessionIdentity.programmeScope
        : [],
  }), [role, sessionIdentity])

  const updateRole = useCallback((nextRole: AppRole) => {
    clearMemoryCache()
    setRole(nextRole)
  }, [])

  const updateSelectedProgrammeCode = useCallback((programmeCode: string) => {
    clearMemoryCache()
    setSelectedProgrammeCode(programmeCode)
  }, [])

  const selectDefaultReportingPeriod = useCallback((periods: ReportingPeriodOption[]) => {
    if (periods.length === 0) {
      return ''
    }
    const now = new Date()
    const open = periods.filter((item) => item.status.toLowerCase() === 'open')
    const currentOpen = open.find((item) => {
      const start = new Date(item.startDate)
      const end = new Date(item.endDate)
      return Number.isFinite(start.getTime()) && Number.isFinite(end.getTime()) && start <= now && now <= end
    })
    return currentOpen?.id ?? open[0]?.id ?? periods[0].id
  }, [])

  const fetchReportingPeriods = useCallback(
    async () => {
      if (!canLoadReportingPeriodData) {
        return []
      }
      const { data } = await readThroughMemoryCache(
        makeScopedCacheKey(adminCacheScope, 'admin.reporting-periods.list', {}),
        () => listReportingPeriods({
          adminId: sessionIdentity?.subjectId ?? frontendConfig.demoAdminId,
          adminProgrammes: reportingPeriodProgrammeScope(sessionIdentity),
        }),
      )
      return data
    },
    [adminCacheScope, canLoadReportingPeriodData, sessionIdentity],
  )

  const reloadReportingPeriods = useCallback(async () => {
    setReportingPeriodsLoading(true)
    setReportingPeriodsError(null)
    if (!canLoadReportingPeriodData) {
      setReportingPeriods([])
      setReportingPeriodId('')
      setReportingPeriodsLoading(false)
      return
    }
    try {
      clearMemoryCache((key) => key === makeScopedCacheKey(adminCacheScope, 'admin.reporting-periods.list', {}))
      const periods = await fetchReportingPeriods()
      setReportingPeriods(periods)
      setReportingPeriodId((prev) => {
        if (prev && periods.some((item) => item.id === prev)) {
          return prev
        }
        return selectDefaultReportingPeriod(periods)
      })
    } catch (error) {
      const message =
        error instanceof ApiRequestError ? error.message : 'Unable to load reporting periods from backend.'
      setReportingPeriodsError(message)
      setReportingPeriods([])
    } finally {
      setReportingPeriodsLoading(false)
    }
  }, [adminCacheScope, canLoadReportingPeriodData, fetchReportingPeriods, selectDefaultReportingPeriod])

  useEffect(() => {
    if (!canLoadReportingPeriodData) {
      return
    }
    let active = true
    ;(async () => {
      try {
        const periods = await fetchReportingPeriods()
        if (!active) {
          return
        }
        setReportingPeriods(periods)
        setReportingPeriodId((prev) => {
          if (prev && periods.some((item) => item.id === prev)) {
            return prev
          }
          return selectDefaultReportingPeriod(periods)
        })
      } catch (error) {
        if (!active) {
          return
        }
        const message =
          error instanceof ApiRequestError ? error.message : 'Unable to load reporting periods from backend.'
        setReportingPeriodsError(message)
        setReportingPeriods([])
      } finally {
        if (active) {
          setReportingPeriodsLoading(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [canLoadReportingPeriodData, fetchReportingPeriods, selectDefaultReportingPeriod])

  useEffect(() => {
    const onAuthSessionChanged = () => {
      const nextIdentity = readStoredAuthSession()?.identity ?? null
      setSessionIdentity(nextIdentity)
      if (!canIdentityLoadReportingPeriodData(nextIdentity)) {
        setReportingPeriods([])
        setReportingPeriodsError(null)
        setReportingPeriodsLoading(false)
      }
    }
    window.addEventListener(authSessionChangedEvent, onAuthSessionChanged)
    return () => window.removeEventListener(authSessionChangedEvent, onAuthSessionChanged)
  }, [])

  const reportingPeriodLabel = useMemo(
    () => reportingPeriods.find((item) => item.id === reportingPeriodId)?.label,
    [reportingPeriods, reportingPeriodId],
  )

  const addUploadResult = useCallback((input: UploadResultInput): UploadMeta => {
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
      setReportingPeriodId,
      reportingPeriodLabel,
      reportingPeriods,
      reportingPeriodsLoading,
      reportingPeriodsError,
      reloadReportingPeriods,
      demoAdminId: frontendConfig.demoAdminId,
      demoAdminProgrammes: frontendConfig.demoAdminProgrammes,
      uploadHistory,
      addUploadResult,
    }),
    [
      role,
      selectedProgrammeCode,
      reportingPeriodId,
      reportingPeriodLabel,
      reportingPeriods,
      reportingPeriodsLoading,
      reportingPeriodsError,
      reloadReportingPeriods,
      uploadHistory,
      addUploadResult,
      updateRole,
      updateSelectedProgrammeCode,
    ],
  )

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}
