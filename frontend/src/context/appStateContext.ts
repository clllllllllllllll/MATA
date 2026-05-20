import { createContext } from 'react'
import type { AppRole } from '../types/app'
import type { NormalizedWarning, ReportingPeriodOption, UploadMeta, WarningStatus } from '../types/upload'

export interface UploadResultInput {
  uploadType: UploadMeta['uploadType']
  response: Record<string, unknown>
  filename?: string
  reportingPeriodId?: string
  reportingPeriodLabel?: string
  programmeCode?: string
}

export interface AppStateContextValue {
  role: AppRole
  setRole: (role: AppRole) => void
  selectedProgrammeCode: string
  setSelectedProgrammeCode: (programmeCode: string) => void
  reportingPeriodId: string
  setReportingPeriodId: (reportingPeriodId: string) => void
  reportingPeriodLabel?: string
  reportingPeriods: ReportingPeriodOption[]
  reportingPeriodsLoading: boolean
  reportingPeriodsError: string | null
  reloadReportingPeriods: () => Promise<void>
  demoAdminId: string
  demoAdminProgrammes: string[]
  uploadHistory: UploadMeta[]
  warnings: NormalizedWarning[]
  addUploadResult: (input: UploadResultInput) => UploadMeta
  updateWarningStatus: (warningId: string, status: WarningStatus) => void
}

export const AppStateContext = createContext<AppStateContextValue | undefined>(undefined)
