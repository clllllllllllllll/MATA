import {
  useEffect,
  useCallback,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react'
import { frontendConfig } from '../config/frontendConfig'
import type { AppRole } from '../types/app'
import type { NormalizedWarning, ReportingPeriodOption, UploadMeta, WarningStatus } from '../types/upload'
import {
  AppStateContext,
  type AppStateContextValue,
  type UploadResultInput,
} from './appStateContext'
import {
  loadUploadHistory,
  loadWarningsByScope,
  saveUploadHistory,
  saveWarningsByScope,
} from '../utils/storage'
import {
  makeUploadMeta,
  makeUploadScopeKey,
  normalizeWarningsFromUploadResponse,
} from '../utils/warnings'
import { listReportingPeriods } from '../api/reportingPeriods'
import { ApiRequestError } from '../api/http'

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
  const [warningsByScope, setWarningsByScope] = useState<Record<string, NormalizedWarning[]>>(loadWarningsByScope)

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
    async () =>
      listReportingPeriods({
        adminId: frontendConfig.demoAdminId,
        adminProgrammes: frontendConfig.demoAdminProgrammes,
      }),
    [],
  )

  const reloadReportingPeriods = useCallback(async () => {
    setReportingPeriodsLoading(true)
    setReportingPeriodsError(null)
    try {
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
  }, [fetchReportingPeriods, selectDefaultReportingPeriod])

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
    const uploadMeta = makeUploadMeta({
      uploadType: input.uploadType,
      response: input.response,
      filename: input.filename,
      reportingPeriodId: input.reportingPeriodId,
      reportingPeriodLabel: input.reportingPeriodLabel,
      programmeCode: input.programmeCode,
    })
    const newWarnings = normalizeWarningsFromUploadResponse(uploadMeta)
    const scopeKey = makeUploadScopeKey({
      uploadType: uploadMeta.uploadType,
      reportingPeriodId: uploadMeta.reportingPeriodId,
      programmeCode: uploadMeta.programmeCode,
    })

    setUploadHistory((prev) => {
      const next = [uploadMeta, ...prev].slice(0, 40)
      saveUploadHistory(next)
      return next
    })

    setWarningsByScope((prev) => {
      const next: Record<string, NormalizedWarning[]> = { ...prev }
      if (newWarnings.length === 0) {
        delete next[scopeKey]
        saveWarningsByScope(next)
        return next
      }

      const previousScopeWarnings = prev[scopeKey] ?? []
      const previousStatusById = new Map(previousScopeWarnings.map((warning) => [warning.id, warning.status]))
      const dedupedById = new Map<string, NormalizedWarning>()

      newWarnings.forEach((warning) => {
        const previousStatus = previousStatusById.get(warning.id)
        dedupedById.set(warning.id, {
          ...warning,
          status: previousStatus ?? warning.status,
        })
      })

      next[scopeKey] = Array.from(dedupedById.values())
      saveWarningsByScope(next)
      return next
    })

    return uploadMeta
  }, [])

  const updateWarningStatus = useCallback((warningId: string, status: WarningStatus) => {
    setWarningsByScope((prev) => {
      const next: Record<string, NormalizedWarning[]> = {}
      Object.entries(prev).forEach(([scopeKey, warnings]) => {
        next[scopeKey] = warnings.map((warning) =>
          warning.id === warningId ? { ...warning, status } : warning,
        )
      })
      saveWarningsByScope(next)
      return next
    })
  }, [])

  const warnings = useMemo(() => Object.values(warningsByScope).flat(), [warningsByScope])

  const value = useMemo<AppStateContextValue>(
    () => ({
      role,
      setRole,
      selectedProgrammeCode,
      setSelectedProgrammeCode,
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
      warnings,
      addUploadResult,
      updateWarningStatus,
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
      warnings,
      addUploadResult,
      updateWarningStatus,
    ],
  )

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}
