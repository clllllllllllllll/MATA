import {
  buildPcTtfWarningsPath,
  resolvePcProgrammeScope,
} from './pcUploadTtfPageLogic'

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
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
