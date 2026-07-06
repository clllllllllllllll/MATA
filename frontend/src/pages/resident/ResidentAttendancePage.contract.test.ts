import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const pageSource = readFileSync(
  fileURLToPath(new URL('./ResidentAttendancePage.tsx', import.meta.url)),
  'utf8',
)
const apiSource = readFileSync(
  fileURLToPath(new URL('../../api/residentSubmissions.ts', import.meta.url)),
  'utf8',
)
const appSource = readFileSync(fileURLToPath(new URL('../../App.tsx', import.meta.url)), 'utf8')

assert(pageSource.includes('title="Past Submissions"'), 'Past Submissions page hero title is present')
assert(pageSource.includes('NHG Resident - Your submitted teachings'), 'Past Submissions subtitle uses NHG Resident wording')
assert(pageSource.includes('filter'), 'Past Submissions page includes a filter bar')
assert(pageSource.includes('dateFrom'), 'Past Submissions filters include start date')
assert(pageSource.includes('dateTo'), 'Past Submissions filters include end date')
assert(pageSource.includes('postingCode'), 'Past Submissions filters include posting')
assert(pageSource.includes('teachingName'), 'Past Submissions filters include teaching name')
assert(pageSource.includes('source'), 'Past Submissions filters include source')
assert(pageSource.includes('status'), 'Past Submissions filters include status')
assert(apiSource.includes('/resident/attendance'), 'Past Submissions API uses /resident/attendance')
assert(apiSource.includes('source'), 'Past Submissions API sends source filter')
assert(apiSource.includes('status'), 'Past Submissions API sends status filter')
assert(apiSource.includes('delete'), 'resident API includes delete/remove attendance request')
assert(pageSource.includes('handleDeleteAttendance'), 'Past Submissions page can delete submitted rows')
assert(pageSource.includes("row.status.toLowerCase() === 'submitted'"), 'delete action only appears for submitted rows')
assert(!pageSource.includes('const canDelete = !isExternalResident'), 'Non-NHG residents can delete their submitted external rows')
assert(pageSource.includes('const showStatusColumn = !isExternalResident'), 'Non-NHG Past Submissions hides visible status values')
assert(pageSource.includes('{showStatusColumn ? <th>Status</th> : null}'), 'Non-NHG Past Submissions table omits Status column')
assert(pageSource.includes('{showStatusColumn ? (') && pageSource.includes('formatAttendanceStatus(row.status)'), 'NHG status display remains conditional')
assert(pageSource.includes('button-danger resident-delete-button'), 'Past Submissions delete action uses danger styling')
assert(pageSource.includes('resident-attendance-card-list'), 'Past Submissions page has mobile card layout')
assert(pageSource.includes('table'), 'Past Submissions page has desktop table layout')
assert(!pageSource.includes('Created By'), 'Past Submissions page does not show Created By')
assert(!pageSource.includes('Created by'), 'Past Submissions page does not show Created by')
assert(appSource.includes("path=\"/resident/attendance\""), '/resident/attendance route is registered')
