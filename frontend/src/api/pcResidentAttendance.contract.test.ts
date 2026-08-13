import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(
  fileURLToPath(new URL('./pcResidentAttendance.ts', import.meta.url)),
  'utf8',
)

for (const field of [
  'resident_id',
  'name',
  'mcr',
  'programme_code',
  'r_year',
  'current_posting_code',
  'current_posting_label',
  'attendance_count',
  'attendance_id',
  'teaching_event_id',
  'teaching_name',
  'details_of_session',
  'event_date',
  'start_time',
  'end_time',
  'posting_label',
  'submitted_at',
  'submitted_during_loa',
  'loa_type',
]) {
  assert(source.includes(field), `PC resident attendance mapper consumes ${field}`)
}

assert(source.includes("'department_secretary'"))
assert(source.includes("'programme_pc'"))
assert(source.includes("'adhoc'"))
assert(source.includes("'submitted'"))
assert(source.includes("'flagged'"))
assert(source.includes("'removed'"))
assert(source.includes('encodeURIComponent(residentId)'))
assert(source.includes("buildAdminDemoHeaders(adminId, programmeScope, 'programme')"))
assert.equal(/httpClient\.(post|put|patch|delete)/.test(source), false)
