import { createContext } from 'react'
import type { AppRole } from '../types/app'
import type { NormalizedWarning, UploadMeta } from '../types/upload'

export interface UploadResultInput {
  uploadType: UploadMeta['uploadType']
  response: Record<string, unknown>
  reportingPeriodId?: string
  programmeCode?: string
}

export interface AppStateContextValue {
  role: AppRole
  setRole: (role: AppRole) => void
  selectedProgrammeCode: string
  setSelectedProgrammeCode: (programmeCode: string) => void
  reportingPeriodId: string
  setReportingPeriodId: (reportingPeriodId: string) => void
  demoAdminId: string
  demoAdminProgrammes: string[]
  uploadHistory: UploadMeta[]
  warnings: NormalizedWarning[]
  addUploadResult: (input: UploadResultInput) => UploadMeta
  markWarningResolved: (warningId: string) => void
}

export const AppStateContext = createContext<AppStateContextValue | undefined>(undefined)
