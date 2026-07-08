import {
  GENERIC_UPLOAD_VALIDATION_MESSAGE,
  resolveUploadErrorMessage,
} from './uploadErrorMessages.ts'

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

const inactiveMessage = 'Selected reporting period is inactive. Activate the reporting period before uploading.'

const inactiveError = {
  message: inactiveMessage,
  status: 422,
  details: {
    detail: inactiveMessage,
    error_code: 'VALIDATION_FAILED',
    errors: [],
    metadata: { reporting_period_id: 'f2f9d5e0-b6fa-4e5b-9f6b-0f5878ea6f15' },
  },
}
assertEqual(
  resolveUploadErrorMessage(inactiveError),
  inactiveMessage,
  'inactive reporting-period upload errors display the backend user-facing message',
)
assert(
  resolveUploadErrorMessage(inactiveError) !== GENERIC_UPLOAD_VALIDATION_MESSAGE,
  'inactive reporting-period upload errors do not fall back to parser/workbook copy',
)

const genericValidationError = {
  message: 'Validation failed',
  status: 422,
  details: {
    detail: 'Validation failed',
    error_code: 'UPLOAD_VALIDATION_FAILED',
    errors: [],
  },
}
assertEqual(
  resolveUploadErrorMessage(genericValidationError),
  GENERIC_UPLOAD_VALIDATION_MESSAGE,
  'generic validation failures keep the upload validation fallback',
)

const multipleErrors = {
  message: 'Upload failed validation',
  status: 422,
  details: {
    detail: 'Upload failed validation',
    error_code: 'UPLOAD_VALIDATION_FAILED',
    errors: [
      'UPLOAD_VALIDATION_FAILED',
      inactiveMessage,
      'warning_issue_id=f2f9d5e0-b6fa-4e5b-9f6b-0f5878ea6f15',
    ],
    metadata: { raw: { status: 422 } },
  },
}
const multipleErrorMessage = resolveUploadErrorMessage(multipleErrors)
assertEqual(
  multipleErrorMessage,
  inactiveMessage,
  'multiple upload validation errors prefer the first safe user-facing message',
)
assert(!multipleErrorMessage.includes('UPLOAD_VALIDATION_FAILED'), 'upload errors do not expose backend error codes')
assert(!multipleErrorMessage.includes('f2f9d5e0'), 'upload errors do not expose UUID-like technical values')
