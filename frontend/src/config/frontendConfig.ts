import type { UploadType } from '../types/app'
import type { AuthMode, FrontendAppEnv } from '../types/auth'

const parseAppEnv = (input: string | undefined): FrontendAppEnv => {
  if (input === 'preview' || input === 'production') {
    return input
  }
  return 'local'
}

const parseAuthMode = (input: string | undefined): AuthMode => {
  if (input === 'demo' || input === 'supabase') {
    return input
  }
  return 'stub'
}

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

const defaultSecretaryId =
  import.meta.env.VITE_DEMO_SECRETARY_USER_ID ??
  import.meta.env.VITE_DEMO_SECRETARY_ID ??
  '00000000-0000-0000-0000-0000000000aa'

const defaultSecretarySite = import.meta.env.VITE_DEMO_SECRETARY_SITE ?? 'TTSHGerMed'

const defaultSecretaryScopeLabel =
  import.meta.env.VITE_DEMO_SECRETARY_SCOPE_LABEL ?? 'TTSH Geriatric Medicine'

const defaultResidentId =
  import.meta.env.VITE_DEMO_RESIDENT_USER_ID ??
  '00000000-0000-0000-0000-0000000000bb'

const defaultResidentMcr = import.meta.env.VITE_DEMO_RESIDENT_MCR ?? 'M00001A'
const defaultResidentProgramme = import.meta.env.VITE_DEMO_RESIDENT_PROGRAMME ?? 'GERI'
const defaultResidentScopeLabel =
  import.meta.env.VITE_DEMO_RESIDENT_SCOPE_LABEL ??
  `TTSH Geriatric Medicine - MCR ${defaultResidentMcr}`

export const frontendConfig = {
  appEnv: parseAppEnv(import.meta.env.VITE_APP_ENV),
  authMode: parseAuthMode(import.meta.env.VITE_AUTH_MODE),
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api/v1',
  defaultRole: 'master_admin' as const,
  defaultProgrammeCode,
  defaultReportingPeriodId: import.meta.env.VITE_DEFAULT_REPORTING_PERIOD_ID ?? '',
  demoAdminId: defaultAdminId,
  demoAdminProgrammes: configuredProgrammes,
  demoSecretaryId: defaultSecretaryId,
  demoSecretarySite: defaultSecretarySite,
  demoSecretaryScopeLabel: defaultSecretaryScopeLabel,
  demoResidentId: defaultResidentId,
  demoResidentMcr: defaultResidentMcr,
  demoResidentProgramme: defaultResidentProgramme,
  demoResidentScopeLabel: defaultResidentScopeLabel,
  supabaseUrl: import.meta.env.VITE_SUPABASE_URL ?? '',
  supabasePublishableKey: import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? '',
  supabaseAnonKey: import.meta.env.VITE_SUPABASE_ANON_KEY ?? '',
}

export const uploadLabels: Record<UploadType, string> = {
  public_holidays: 'Academic Calendar / Public Holidays',
  rdb: 'RDB Posting Schedule',
  ttf: 'Teaching Target File',
  form_f1: 'FormF1',
}
