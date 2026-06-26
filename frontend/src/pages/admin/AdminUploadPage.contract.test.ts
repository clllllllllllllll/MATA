import type { Programme } from '../../api/programmes'
import {
  buildAdminUploadWarningsPath,
  buildMasterAdminTtfProgrammeOptions,
  buildReviewWarningsPathForUploadSlot,
} from './adminUploadPageLogic.ts'

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const programmes = [
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
    code: 'GRM',
    name: 'Geriatric Medicine',
    ayDateCategory: 'non_im_subspec',
    rYearRequired: true,
    isSubspecialty: false,
  },
  {
    id: '3',
    code: 'ORTHO',
    name: 'Orthopaedic Surgery',
    ayDateCategory: 'non_im_subspec',
    rYearRequired: true,
    isSubspecialty: false,
  },
] satisfies Programme[]

const masterOptions = buildMasterAdminTtfProgrammeOptions(programmes, ['DR'])
assertEqual(masterOptions.length, 3, 'master admin TTF selector uses canonical programme list')
assertEqual(masterOptions[2]?.code, 'ORTHO', 'master admin TTF selector includes programmes outside demo scope')
assertEqual(
  masterOptions[0]?.label,
  'DR - Diagnostic Radiology',
  'master admin TTF selector labels include programme names when available',
)

const fullProgrammeCatalogue = Array.from({ length: 28 }, (_, index) => ({
  id: String(index + 1),
  code: `P${String(index + 1).padStart(2, '0')}`,
  name: `Programme ${index + 1}`,
  ayDateCategory: 'non_im_subspec',
  rYearRequired: true,
  isSubspecialty: false,
})) satisfies Programme[]
const allProgrammeOptions = buildMasterAdminTtfProgrammeOptions(fullProgrammeCatalogue, ['P01'])
assertEqual(allProgrammeOptions.length, 28, 'master admin TTF selector exposes all valid catalogue programmes')
assertEqual(allProgrammeOptions[27]?.code, 'P28', 'master admin TTF selector keeps out-of-scope catalogue option values as codes')
assertEqual(
  allProgrammeOptions[27]?.label,
  'P28 - Programme 28',
  'master admin TTF selector labels full catalogue options with names',
)

const fallbackOptions = buildMasterAdminTtfProgrammeOptions([], ['DR', 'DR', ' GERI '])
assertEqual(fallbackOptions.length, 2, 'fallback selector options are deduped')
assertEqual(fallbackOptions[1]?.code, 'GERI', 'fallback selector trims configured scope values')

const selectedTtfWarningsPath = buildReviewWarningsPathForUploadSlot({
  uploadType: 'ttf',
  selectedReportingPeriodId: 'period-1',
  selectedProgrammeCode: 'ORTHO',
})
assertEqual(
  selectedTtfWarningsPath,
  '/admin/upload/warnings?mode=active&upload_type=ttf&reporting_period_id=period-1&programme_code=ORTHO',
  'admin TTF warning link keeps selected programme and reporting period when no upload log context exists',
)

const latestTtfWarningsPath = buildReviewWarningsPathForUploadSlot({
  uploadType: 'ttf',
  selectedReportingPeriodId: 'period-1',
  selectedProgrammeCode: 'DR',
  latestUpload: {
    reportingPeriodId: 'period-2',
    programmeCode: 'GERI',
  },
})
assertEqual(
  latestTtfWarningsPath,
  '/admin/upload/warnings?mode=active&upload_type=ttf&reporting_period_id=period-2&programme_code=GERI',
  'admin TTF warning link prefers latest upload programme and reporting period context',
)

const uploadLogWarningsPath = buildAdminUploadWarningsPath({
  mode: 'history',
  uploadType: 'ttf',
  reportingPeriodId: 'period-3',
  programmeCode: 'DR',
})
assertEqual(
  uploadLogWarningsPath,
  '/admin/upload/warnings?mode=history&upload_type=ttf&reporting_period_id=period-3&programme_code=DR',
  'upload-log related-warning link preserves TTF programme and reporting period context',
)
