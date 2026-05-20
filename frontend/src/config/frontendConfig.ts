import type { UploadType } from '../types/app'

const parseProgrammeList = (input: string | undefined): string[] => {
  if (!input) {
    return ['DR', 'GERI']
  }
  return input
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

const configuredProgrammes = parseProgrammeList(
  import.meta.env.VITE_DEMO_ADMIN_PROGRAMME_SCOPE ?? import.meta.env.VITE_DEMO_ADMIN_PROGRAMMES,
)

const defaultProgrammeCode =
  import.meta.env.VITE_DEFAULT_PROGRAMME_CODE ?? configuredProgrammes[0] ?? 'DR'

const defaultAdminId =
  import.meta.env.VITE_DEMO_ADMIN_USER_ID ??
  import.meta.env.VITE_DEMO_ADMIN_ID ??
  '5635c7b4-e0f1-4f59-88e1-f0b976b62d29'

export const frontendConfig = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1',
  defaultRole: 'master_admin' as const,
  defaultProgrammeCode,
  defaultReportingPeriodId: import.meta.env.VITE_DEFAULT_REPORTING_PERIOD_ID ?? '',
  demoAdminId: defaultAdminId,
  demoAdminProgrammes: configuredProgrammes,
}

export const uploadLabels: Record<UploadType, string> = {
  public_holidays: 'Academic Calendar / Public Holidays',
  rdb: 'RDB Posting Schedule',
  ttf: 'Teaching Target File',
  form_f1: 'FormF1',
}
