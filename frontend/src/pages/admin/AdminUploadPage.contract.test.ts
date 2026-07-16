import type { Programme } from '../../api/programmes'
import type { UploadRequest } from '../../api/uploads'
import { resolveUploadCardAvailability } from '../../components/uploadCardLogic.ts'
import type { ReportingPeriodOption } from '../../types/upload.ts'
import { selectCurrentReportingPeriodId } from '../../utils/reportingPeriods.ts'
import {
  buildAdminUploadWarningsPath,
  buildMasterAdminTtfProgrammeOptions,
  buildReviewWarningsPathForUploadSlot,
  INACTIVE_REPORTING_PERIOD_MESSAGE,
  INVALID_REPORTING_PERIOD_MESSAGE,
  MISSING_REPORTING_PERIOD_MESSAGE,
  resolveAdminUploadReportingPeriod,
  submitAdminUpload,
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

const reportingPeriods = [
  {
    id: 'reopened-historical-period',
    label: 'Reopened Historical Period',
    startDate: '2025-07-01',
    endDate: '2025-12-31',
    status: 'active',
    deactivateOn: '2026-12-31',
  },
  {
    id: 'current-period',
    label: 'Current Period',
    startDate: '2026-07-01',
    endDate: '2026-12-31',
    status: 'active',
  },
  {
    id: 'future-test-period',
    label: 'Future Test Period',
    startDate: '2099-01-01',
    endDate: '2099-06-30',
    status: 'active',
  },
  {
    id: 'inactive-period',
    label: 'Inactive Period',
    startDate: '2024-01-01',
    endDate: '2024-06-30',
    status: 'inactive',
  },
] satisfies ReportingPeriodOption[]

const file = { name: 'upload.xlsx' } as File
const submittedRequests: UploadRequest[] = []
const recordSubmission = async (request: UploadRequest): Promise<Record<string, unknown>> => {
  submittedRequests.push(request)
  return { accepted: true }
}
const submitInput = {
  file,
  adminId: 'master-admin',
  adminProgrammes: ['DR'],
  adminLevel: 'master' as const,
}

const historicalSelection = resolveAdminUploadReportingPeriod(
  reportingPeriods,
  'reopened-historical-period',
)
assertEqual(historicalSelection.state, 'active', 'a reopened historical period is valid for explicit upload')

submittedRequests.length = 0
await submitAdminUpload({
  ...submitInput,
  uploadType: 'rdb',
  reportingPeriod: historicalSelection,
}, recordSubmission)
assertEqual(submittedRequests.length, 1, 'explicit historical RDB upload makes one request')
assertEqual(
  submittedRequests[0]?.reportingPeriodId,
  'reopened-historical-period',
  'explicit historical RDB upload sends the selected reporting period',
)

submittedRequests.length = 0
await submitAdminUpload({
  ...submitInput,
  uploadType: 'form_f1',
  reportingPeriod: historicalSelection,
}, recordSubmission)
assertEqual(submittedRequests.length, 1, 'explicit historical FormF1 upload makes one request')
assertEqual(
  submittedRequests[0]?.reportingPeriodId,
  'reopened-historical-period',
  'explicit historical FormF1 upload sends the selected reporting period',
)

submittedRequests.length = 0
await submitAdminUpload({
  ...submitInput,
  uploadType: 'ttf',
  reportingPeriod: historicalSelection,
  programmeCode: ' DR ',
}, recordSubmission)
assertEqual(submittedRequests.length, 1, 'explicit historical TTF upload makes one request')
assertEqual(
  submittedRequests[0]?.reportingPeriodId,
  'reopened-historical-period',
  'explicit historical TTF upload sends the selected reporting period',
)
assertEqual(submittedRequests[0]?.programmeCode, 'DR', 'explicit historical TTF upload sends the programme code')

const currentDate = new Date(2026, 6, 15)
assertEqual(
  selectCurrentReportingPeriodId(reportingPeriods, currentDate),
  'current-period',
  'automatic selection remains date-aware when a future active period exists',
)
const futureSelection = resolveAdminUploadReportingPeriod(reportingPeriods, 'future-test-period')
const futureAvailability = resolveUploadCardAvailability({
  hasFile: true,
  status: 'selected',
  requiresReportingPeriod: true,
  reportingPeriodId: futureSelection.reportingPeriodId,
  reportingPeriodValidationMessage: futureSelection.validationMessage,
  requiresProgramme: false,
})
assertEqual(futureSelection.state, 'active', 'an explicitly selected future active period is valid')
assertEqual(futureAvailability.disabled, false, 'an explicitly selected future active period enables upload')

const inactiveSelection = resolveAdminUploadReportingPeriod(reportingPeriods, 'inactive-period')
const inactiveAvailability = resolveUploadCardAvailability({
  hasFile: true,
  status: 'selected',
  requiresReportingPeriod: true,
  reportingPeriodId: inactiveSelection.reportingPeriodId,
  reportingPeriodValidationMessage: inactiveSelection.validationMessage,
  requiresProgramme: false,
})
assertEqual(inactiveAvailability.disabled, true, 'an inactive selected period disables upload')
assertEqual(
  inactiveAvailability.reportingPeriodMessage,
  INACTIVE_REPORTING_PERIOD_MESSAGE,
  'an inactive selected period displays the inactive message',
)
assertEqual(
  inactiveAvailability.reportingPeriodMessage === MISSING_REPORTING_PERIOD_MESSAGE,
  false,
  'an inactive selected period is not reported as missing',
)
submittedRequests.length = 0
const inactiveResult = await submitAdminUpload({
  ...submitInput,
  uploadType: 'rdb',
  reportingPeriod: inactiveSelection,
}, recordSubmission)
assertEqual(inactiveResult, undefined, 'an inactive selected period does not produce an upload result')
assertEqual(submittedRequests.length, 0, 'an inactive selected period sends no request')

const missingSelection = resolveAdminUploadReportingPeriod(reportingPeriods, '')
const missingAvailability = resolveUploadCardAvailability({
  hasFile: true,
  status: 'selected',
  requiresReportingPeriod: true,
  reportingPeriodId: missingSelection.reportingPeriodId,
  reportingPeriodValidationMessage: missingSelection.validationMessage,
  requiresProgramme: false,
})
assertEqual(missingAvailability.disabled, true, 'no selected period keeps uploads disabled')
assertEqual(
  missingAvailability.reportingPeriodMessage,
  MISSING_REPORTING_PERIOD_MESSAGE,
  'no selected period displays the missing-period message',
)
for (const uploadType of ['rdb', 'form_f1', 'ttf'] as const) {
  submittedRequests.length = 0
  const missingResult = await submitAdminUpload({
    ...submitInput,
    uploadType,
    reportingPeriod: missingSelection,
    programmeCode: uploadType === 'ttf' ? 'DR' : undefined,
  }, recordSubmission)
  assertEqual(missingResult, undefined, `${uploadType} without a selected period has no result`)
  assertEqual(submittedRequests.length, 0, `${uploadType} without a selected period sends no request`)
}

const invalidSelection = resolveAdminUploadReportingPeriod(reportingPeriods, 'absent-period')
const invalidAvailability = resolveUploadCardAvailability({
  hasFile: true,
  status: 'selected',
  requiresReportingPeriod: true,
  reportingPeriodId: invalidSelection.reportingPeriodId,
  reportingPeriodValidationMessage: invalidSelection.validationMessage,
  requiresProgramme: false,
})
assertEqual(invalidAvailability.disabled, true, 'a selected ID absent from the loaded list disables upload')
assertEqual(
  invalidAvailability.reportingPeriodMessage,
  INVALID_REPORTING_PERIOD_MESSAGE,
  'a selected ID absent from the loaded list is reported as unavailable',
)
submittedRequests.length = 0
const invalidResult = await submitAdminUpload({
  ...submitInput,
  uploadType: 'form_f1',
  reportingPeriod: invalidSelection,
}, recordSubmission)
assertEqual(invalidResult, undefined, 'a selected ID absent from the loaded list has no result')
assertEqual(submittedRequests.length, 0, 'a selected ID absent from the loaded list sends no request')
