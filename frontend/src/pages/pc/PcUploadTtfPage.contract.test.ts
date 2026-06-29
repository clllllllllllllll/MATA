import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  buildPcTtfWarningsPath,
  resolvePcProgrammeScope,
} from './pcUploadTtfPageLogic.ts'
import type { Programme } from '../../api/programmes'

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const singleProgramme = resolvePcProgrammeScope(['GERI'], 'DR')
assertEqual(singleProgramme.mode, 'locked', 'single programme PC uses locked mode')
assertEqual(singleProgramme.selectedProgrammeCode, 'GERI', 'single programme PC is pinned to scope')

const scopedSelection = resolvePcProgrammeScope(['DR', 'GERI'], 'GERI')
assertEqual(scopedSelection.mode, 'select', 'multi programme PC uses dropdown mode')
assertEqual(scopedSelection.selectedProgrammeCode, 'GERI', 'in-scope selected programme is preserved')

const fallbackSelection = resolvePcProgrammeScope(['DR', 'GERI'], 'ORTHO')
assertEqual(fallbackSelection.selectedProgrammeCode, 'DR', 'out-of-scope selection falls back to first scoped programme')

const programmeCatalogue = [
  {
    id: '1',
    code: 'DR',
    name: 'Diagnostic Radiology',
    ayDateCategory: 'non_im_subspec',
    rYearRequired: true,
    isSubspecialty: false,
  },
  {
    id: '2',
    code: 'GERI',
    name: 'Geriatric Medicine',
    ayDateCategory: 'im_subspec',
    rYearRequired: false,
    isSubspecialty: false,
  },
  {
    id: '3',
    code: 'ORTHO',
    name: 'Orthopaedic Surgery',
    ayDateCategory: 'non_im_subspec',
    rYearRequired: false,
    isSubspecialty: false,
  },
] satisfies Programme[]

const namedProgrammeScope = resolvePcProgrammeScope(['DR', 'GERI'], 'GERI', programmeCatalogue)
assertEqual(
  namedProgrammeScope.selectedProgrammeCode,
  'GERI',
  'PC upload state keeps the raw selected programme code when labels include names',
)
assertEqual(
  namedProgrammeScope.programmeOptions[0]?.code,
  'DR',
  'PC programme selector option value remains the programme code',
)
assertEqual(
  namedProgrammeScope.programmeOptions[0]?.label,
  'DR - Diagnostic Radiology',
  'PC programme selector includes programme name when catalogue is available',
)
assertEqual(
  namedProgrammeScope.programmeOptions[1]?.label,
  'GERI - Geriatric Medicine',
  'PC programme selector formats each scoped programme with its full name',
)
assertEqual(
  namedProgrammeScope.programmeOptions.some((programme) => programme.code === 'ORTHO'),
  false,
  'PC programme selector excludes out-of-scope catalogue programmes',
)
assertEqual(
  namedProgrammeScope.selectedProgrammeLabel,
  'GERI - Geriatric Medicine',
  'locked/static PC display can use the selected programme full label',
)

const codeOnlyProgrammeScope = resolvePcProgrammeScope(['DR'], 'DR', [])
assertEqual(
  codeOnlyProgrammeScope.programmeOptions[0]?.label,
  'DR',
  'PC programme selector falls back to code-only labels when catalogue names are unavailable',
)

const warningsPath = buildPcTtfWarningsPath({
  programmeCode: 'GERI',
  reportingPeriodId: 'period-1',
})
assertEqual(
  warningsPath,
  '/pc/warnings?mode=active&upload_type=ttf&programme_code=GERI&reporting_period_id=period-1',
  'warnings link is filtered to TTF, programme, and reporting period',
)

const warningsPathWithoutPeriod = buildPcTtfWarningsPath({
  programmeCode: 'DR',
  reportingPeriodId: '',
})
assertEqual(
  warningsPathWithoutPeriod,
  '/pc/warnings?mode=active&upload_type=ttf&programme_code=DR',
  'warnings link omits blank reporting period',
)

const uploadPageSource = readFileSync(
  fileURLToPath(new URL('./PcUploadTtfPage.tsx', import.meta.url)),
  'utf8',
)
assert(
  uploadPageSource.includes('pc-programme-readonly-field'),
  'single-scope PC upload programme display uses read-only field styling',
)
assert(uploadPageSource.includes('readOnly'), 'single-scope PC upload programme display is read-only')
assert(
  !uploadPageSource.includes('pc-programme-lock-chip'),
  'single-scope PC upload programme display does not render the old blue chip class',
)
assert(
  !uploadPageSource.includes('Assigned programme:'),
  'single-scope PC upload programme display does not use assigned-programme chip wording',
)
assert(
  uploadPageSource.includes('programmeCode: selectedPcProgrammeCode'),
  'PC upload request keeps sending the raw selected programme code',
)
