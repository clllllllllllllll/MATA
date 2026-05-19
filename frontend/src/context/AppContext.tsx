import {
  useCallback,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react'
import { frontendConfig } from '../config/frontendConfig'
import type { AppRole } from '../types/app'
import type { NormalizedWarning, UploadMeta } from '../types/upload'
import {
  AppStateContext,
  type AppStateContextValue,
  type UploadResultInput,
} from './appStateContext'
import {
  loadUploadHistory,
  loadWarnings,
  saveUploadHistory,
  saveWarnings,
} from '../utils/storage'
import { makeUploadMeta, normalizeWarningsFromUploadResponse } from '../utils/warnings'

export const AppStateProvider = ({ children }: PropsWithChildren) => {
  const [role, setRole] = useState<AppRole>(frontendConfig.defaultRole)
  const [selectedProgrammeCode, setSelectedProgrammeCode] = useState<string>(
    frontendConfig.defaultProgrammeCode,
  )
  const [reportingPeriodId, setReportingPeriodId] = useState<string>(
    frontendConfig.defaultReportingPeriodId,
  )
  const [uploadHistory, setUploadHistory] = useState<UploadMeta[]>(loadUploadHistory)
  const [warnings, setWarnings] = useState<NormalizedWarning[]>(loadWarnings)

  const addUploadResult = useCallback((input: UploadResultInput): UploadMeta => {
    const uploadMeta = makeUploadMeta({
      uploadType: input.uploadType,
      response: input.response,
      reportingPeriodId: input.reportingPeriodId,
      programmeCode: input.programmeCode,
    })
    const newWarnings = normalizeWarningsFromUploadResponse(uploadMeta)

    setUploadHistory((prev) => {
      const next = [uploadMeta, ...prev].slice(0, 40)
      saveUploadHistory(next)
      return next
    })

    setWarnings((prev) => {
      const next = [...newWarnings, ...prev]
      saveWarnings(next)
      return next
    })

    return uploadMeta
  }, [])

  const markWarningResolved = useCallback((warningId: string) => {
    setWarnings((prev) => {
      const next = prev.map((warning) =>
        warning.id === warningId ? { ...warning, status: 'resolved' as const } : warning,
      )
      saveWarnings(next)
      return next
    })
  }, [])

  const value = useMemo<AppStateContextValue>(
    () => ({
      role,
      setRole,
      selectedProgrammeCode,
      setSelectedProgrammeCode,
      reportingPeriodId,
      setReportingPeriodId,
      demoAdminId: frontendConfig.demoAdminId,
      demoAdminProgrammes: frontendConfig.demoAdminProgrammes,
      uploadHistory,
      warnings,
      addUploadResult,
      markWarningResolved,
    }),
    [
      role,
      selectedProgrammeCode,
      reportingPeriodId,
      uploadHistory,
      warnings,
      addUploadResult,
      markWarningResolved,
    ],
  )

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}
