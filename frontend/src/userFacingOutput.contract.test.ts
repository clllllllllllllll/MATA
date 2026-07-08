/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { formatUserFacingApiError, isSafeUserFacingMessage } from './utils/userFacingErrors.ts'

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const assertNoTechnicalText = (value: string, label: string) => {
  assert(!/\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/i.test(value), `${label} hides UUID-like values`)
  assert(!/\b(4\d\d|5\d\d)\b/.test(value), `${label} hides HTTP status codes`)
  assert(!/\b[A-Z][A-Z0-9_]{2,}\b/.test(value), `${label} hides internal error codes`)
  assert(!/reporting_period_id|upload_log_id|warning_issue_id|entity_id|log_id|source_payload|metadata_json|before_json|after_json|workflow_status|fingerprint/i.test(value), `${label} hides raw field names`)
  assert(!/^\s*[{[]/.test(value), `${label} hides raw JSON`)
}

const dataRevalidationSource = read('./components/DataRevalidationCallout.tsx')
assert(!dataRevalidationSource.includes('<pre'), 'data revalidation callout does not render preformatted raw JSON')
assert(!dataRevalidationSource.includes('Affected warning issue IDs'), 'data revalidation callout does not label warning UUID lists')
assert(!dataRevalidationSource.includes('Raw details'), 'data revalidation callout does not expose raw details')
assert(!dataRevalidationSource.includes('Warning candidate cap'), 'data revalidation callout does not expose candidate cap internals')

const adminWarningsSource = read('./pages/admin/AdminWarningsPage.tsx')
assert(!adminWarningsSource.includes('Latest Source Payload'), 'admin warning detail hides source payload JSON section')
assert(!adminWarningsSource.includes('<JsonBlock'), 'admin warning detail does not render JSON blocks')
assert(!adminWarningsSource.includes('<span>Fingerprint</span>'), 'admin warning detail hides fingerprints')
assert(!adminWarningsSource.includes('<span>Audit log</span>'), 'admin warning source-cell apply result hides audit log IDs')
assert(!adminWarningsSource.includes('Parsed candidate rows'), 'admin warning source-cell preview hides parser candidate JSON')
assert(!adminWarningsSource.includes('Parser warnings and errors'), 'admin warning source-cell preview hides parser warning/error JSON')

const secretaryScheduleSource = read('./pages/secretary/SecretaryTeachingSchedulePage.tsx')
assert(!secretaryScheduleSource.includes('Show developer details'), 'secretary event form does not offer developer details')
assert(!secretaryScheduleSource.includes('submitErrorDetails'), 'secretary event form does not retain raw submit error details for UI')
assert(!secretaryScheduleSource.includes('JSON.stringify(submitErrorDetails'), 'secretary event form does not stringify raw API details')

const parsedDataSource = read('./pages/admin/AdminParsedDataPage.tsx')
assert(!parsedDataSource.includes('Object.entries(selectedRow)'), 'parsed data detail uses an allowlisted row display instead of every raw field')
assert(!parsedDataSource.includes("label: 'Upload ID'"), 'parsed data table does not show upload UUID columns')
assert(!parsedDataSource.includes('<span>Rule ID</span>'), 'parsed data source context does not show rule UUIDs')
assert(!parsedDataSource.includes('warningId}</a>'), 'parsed data source context does not show warning UUID links')

const adminUploadSource = read('./pages/admin/AdminUploadPage.tsx')
const uploadCardSource = read('./components/UploadCard.tsx')
const uploadLogsSource = read('./pages/admin/AdminUploadLogsPage.tsx')
assert(!adminUploadSource.includes('reporting_period_id sent'), 'admin upload page avoids reporting_period_id copy')
assert(!adminUploadSource.includes('UUID fallback'), 'admin upload page avoids UUID fallback copy')
assert(!adminUploadSource.includes('reporting_periods.id'), 'admin upload page avoids reporting_periods.id copy')
assert(!uploadCardSource.includes('Reporting period ID'), 'upload card validation avoids reporting period ID copy')
assert(!uploadLogsSource.includes('reporting_period_label ?? log.reporting_period_id'), 'upload log table does not fall back to raw reporting period IDs')
assert(!uploadLogsSource.includes('reporting_period_label ?? selectedLog.reporting_period_id'), 'upload log detail does not fall back to raw reporting period IDs')

const warningsSource = read('./utils/warnings.ts')
assert(warningsSource.includes('UNKNOWN_WARNING_MESSAGE'), 'unknown upload warnings use a named friendly fallback')
assert(
  warningsSource.includes('raw: warning'),
  'unknown upload warnings keep raw data internally for audit/debugging without displaying it',
)
assert(!warningsSource.includes('JSON.stringify(warning)'), 'unknown upload warnings are not stringified for display')

const rawValidationMessage = formatUserFacingApiError({
  status: 422,
  message: 'UPLOAD_VALIDATION_FAILED',
  details: {
    detail: 'Request failed with status 422',
    error_code: 'UPLOAD_VALIDATION_FAILED',
    metadata: { reporting_period_id: 'f2f9d5e0-b6fa-4e5b-9f6b-0f5878ea6f15' },
  },
})
assertEqual(
  rawValidationMessage,
  'Some information could not be saved. Review the form and try again.',
  'shared API formatter maps raw validation failures to friendly copy',
)
assertNoTechnicalText(rawValidationMessage, 'raw validation API fallback')

const serverMessage = formatUserFacingApiError({
  status: 500,
  message: 'sqlalchemy.exc.IntegrityError: duplicate key value violates unique constraint',
})
assertEqual(
  serverMessage,
  'The system could not complete the request. Try again later.',
  'shared API formatter maps server failures to friendly copy',
)
assertNoTechnicalText(serverMessage, 'server API fallback')

const safeValidation = 'Teaching events cannot be created on public holidays.'
assert(isSafeUserFacingMessage(safeValidation), 'shared API formatter recognises friendly validation copy')
assertEqual(
  formatUserFacingApiError({ status: 422, message: safeValidation }),
  safeValidation,
  'shared API formatter preserves safe validation guidance',
)
