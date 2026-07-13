import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  downloadSecretaryTeachingScheduleCsv,
  type CsvDownloadEnvironment,
  SECRETARY_TEACHING_EVENT_EXPORT_ERROR,
} from './secretaryTeachingScheduleExport.ts'

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

let deferredCleanup: unknown = null
let revokedUrl: string | null = null
let receivedBlob: unknown = null
const calls: string[] = []
const link = {
  href: '',
  download: '',
  click: () => calls.push('click'),
} as unknown as HTMLAnchorElement

const environment: CsvDownloadEnvironment = {
  createObjectUrl: (blob) => {
    receivedBlob = blob
    calls.push('createObjectUrl')
    return 'blob:secretary-export'
  },
  revokeObjectUrl: (url) => {
    revokedUrl = url
    calls.push('revokeObjectUrl')
  },
  createLink: () => {
    calls.push('createLink')
    return link
  },
  appendLink: () => calls.push('appendLink'),
  removeLink: () => calls.push('removeLink'),
  defer: (callback) => {
    deferredCleanup = callback
    calls.push('defer')
  },
}

downloadSecretaryTeachingScheduleCsv('Teaching Type\nDepartment Teaching', environment)

assertEqual((receivedBlob as Blob | null)?.type, 'text/csv;charset=utf-8', 'CSV export creates a CSV Blob')
assertEqual(link.href, 'blob:secretary-export', 'CSV export assigns the Blob URL to the download link')
assertEqual(link.download, 'secretary-teaching-schedule.csv', 'CSV export assigns a sensible filename')
assertEqual(calls.join(','), 'createObjectUrl,createLink,appendLink,click,removeLink,defer', 'CSV export triggers a download')
assertEqual(revokedUrl, null, 'CSV export does not revoke the Blob URL before the download starts')
assert(typeof deferredCleanup === 'function', 'CSV export schedules Blob URL cleanup')
if (typeof deferredCleanup === 'function') {
  deferredCleanup()
}
assertEqual(revokedUrl, 'blob:secretary-export', 'CSV export revokes the Blob URL after the download starts')

let failedCleanup: unknown = null
let failed = false
try {
  downloadSecretaryTeachingScheduleCsv('Teaching Type', {
    ...environment,
    createLink: () => {
      throw new Error('link creation failed')
    },
    defer: (callback) => {
      failedCleanup = callback
    },
  })
} catch {
  failed = true
}
assert(failed, 'CSV export propagates browser download failures to the page error handler')
assert(typeof failedCleanup === 'function', 'CSV export still schedules cleanup when browser download setup fails')

const pageSource = readFileSync(
  fileURLToPath(new URL('./SecretaryTeachingSchedulePage.tsx', import.meta.url)),
  'utf8',
)
assert(
  pageSource.includes('downloadSecretaryTeachingScheduleCsv(buildEventCsv(visibleEvents))'),
  'Secretary export action invokes the browser download helper for the scoped event list',
)
assert(
  pageSource.includes('setExportError(SECRETARY_TEACHING_EVENT_EXPORT_ERROR)'),
  'Secretary export action shows a safe error when browser download setup fails',
)
assert(
  pageSource.includes('role="alert"') && pageSource.includes('{exportError ? ('),
  'Secretary export error is announced in the page UI',
)
assert(
  !pageSource.includes('URL.revokeObjectURL(url)'),
  'Secretary page does not synchronously revoke the download URL',
)
assertEqual(
  SECRETARY_TEACHING_EVENT_EXPORT_ERROR,
  'Unable to export teaching events. Please try again.',
  'Secretary export failure copy is safe and user-facing',
)

console.log('Secretary teaching schedule export contract checks passed.')
