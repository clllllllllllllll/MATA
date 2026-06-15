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
import { listReportingPeriods } from '../api/reportingPeriods'
import { ApiRequestError } from '../api/http'
import {
  clearMemoryCache,
  makeScopedCacheKey,
  readThroughMemoryCache,
  type CacheScope,
} from '../utils/memoryReadCache'

export const AppStateProvider = ({ children }: PropsWithChildren) => {
  const [role, setRole] = useState<AppRole>(frontendConfig.defaultRole)
  const [selectedProgrammeCode, setSelectedProgrammeCode] = useState<string>(
    frontendConfig.defaultProgrammeCode,
  )
  const [reportingPeriodId, setReportingPeriodId] = useState<string>(
    frontendConfig.defaultReportingPeriodId,
  )
  const [reportingPeriods, setReportingPeriods] = useState<ReportingPeriodOption[]>([])
  const [reportingPeriodsLoading, setReportingPeriodsLoading] = useState(true)
  const [reportingPeriodsError, setReportingPeriodsError] = useState<string | null>(null)
  const [uploadHistory, setUploadHistory] = useState<UploadMeta[]>(loadUploadHistory)

  const adminCacheScope = useMemo<CacheScope>(() => ({
    role,
    userId: frontendConfig.demoAdminId,
    programmeScope: frontendConfig.demoAdminProgrammes,
  }), [role])

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
      const { data } = await readThroughMemoryCache(
        makeScopedCacheKey(adminCacheScope, 'admin.reporting-periods.list', {}),
        () => listReportingPeriods({
          adminId: frontendConfig.demoAdminId,
          adminProgrammes: frontendConfig.demoAdminProgrammes,
        }),
      )
      return data
    },
    [adminCacheScope],
  )

  const reloadReportingPeriods = useCallback(async () => {
    setReportingPeriodsLoading(true)
    setReportingPeriodsError(null)
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
  }, [adminCacheScope, fetchReportingPeriods, selectDefaultReportingPeriod])

  useEffect(() => {
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
  }, [fetchReportingPeriods, selectDefaultReportingPeriod])

  const reportingPeriodLabel = useMemo(
    () => reportingPeriods.find((item) => item.id === reportingPeriodId)?.label,
    [reportingPeriods, reportingPeriodId],
  )

  const addUploadResult = useCallback((input: UploadResultInput): UploadMeta => {
    clearMemoryCache()
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
