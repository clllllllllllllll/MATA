import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  getRouteAccessDecision,
  isPcResidentAttendanceDetailPath,
  isRoutePathAllowedForRole,
} from '../../routeGuards.ts'
import {
  attendanceSourceLabel,
  attendanceStatusLabel,
  displayCurrentPosting,
  pageRangeLabel,
  pcResidentAttendanceDetailPath,
} from './pcResidentAttendancePageLogic.ts'

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const overviewSource = read('./PcResidentAttendancePage.tsx')
const detailSource = read('./PcResidentAttendanceDetailPage.tsx')
const apiSource = read('../../api/pcResidentAttendance.ts')
const appSource = read('../../App.tsx')
const navigationSource = read('../../config/navigation.ts')
const shellSource = read('../../components/AppShell.tsx')
const stylesSource = read('../../index.css')
const nonNhgSource = read('../admin/AdminExternalAttendancePage.tsx')

const residentId = '11111111-2222-3333-4444-555555555555'
const detailPath = `/pc/residents/${residentId}/attendance`

assert.equal(
  pcResidentAttendanceDetailPath(residentId),
  detailPath,
  'resident UUID builds the dedicated attendance-history route',
)
assert.equal(
  pcResidentAttendanceDetailPath(residentId).includes('M00000D'),
  false,
  'MCR is never used in the resident attendance route',
)
assert.equal(isPcResidentAttendanceDetailPath(detailPath), true)
assert.equal(isPcResidentAttendanceDetailPath(`${detailPath}?source=adhoc`), true)
assert.equal(isPcResidentAttendanceDetailPath('/pc/residents/not-a-uuid/attendance'), false)
assert.equal(isPcResidentAttendanceDetailPath(`/pc/residents/${residentId}/attendance/extra`), false)
assert.equal(isRoutePathAllowedForRole(detailPath, 'programme_pc'), true)
assert.equal(isRoutePathAllowedForRole(detailPath, 'master_admin'), false)

assert.equal(
  getRouteAccessDecision({
    pathname: detailPath,
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: false,
    role: null,
  }).kind,
  'redirect_to_login',
  'logged-out detail access is stopped before rendering',
)
for (const role of ['master_admin', 'secretary', 'resident', 'external_resident'] as const) {
  assert.equal(
    getRouteAccessDecision({
      pathname: detailPath,
      routeKind: 'protected',
      isLoading: false,
      hasExplicitSession: true,
      role,
    }).kind,
    'redirect_to_role_default',
    `${role} cannot render a Programme PC resident detail`,
  )
}

assert.equal(attendanceSourceLabel('department_secretary'), 'Department Secretary')
assert.equal(attendanceSourceLabel('Programme PC'), 'Programme PC')
assert.equal(attendanceSourceLabel('adhoc'), 'Ad-hoc')
assert.equal(attendanceStatusLabel('submitted'), 'Submitted')
assert.equal(attendanceStatusLabel('flagged'), 'Flagged')
assert.equal(attendanceStatusLabel('removed'), 'Removed')
assert.equal(
  displayCurrentPosting({ currentPostingCode: null, currentPostingLabel: null }),
  'No current posting',
)
assert.equal(pageRangeLabel(73, 25, 25), '26-50 of 73')

assert(navigationSource.includes("label: 'NHG Resident Attendance'"))
assert(navigationSource.includes("path: '/pc/resident-attendance'"))
assert(navigationSource.includes("label: 'Non-NHG Attendance'"), 'Non-NHG navigation remains separate')
assert(appSource.includes('path="/pc/resident-attendance"'))
assert(appSource.includes('path="/pc/residents/:residentId/attendance"'))
assert(shellSource.includes('isPcResidentAttendanceDetailPath(location.pathname)'))
assert(shellSource.includes("['PC', 'NHG Resident Attendance', 'Resident attendance']"))
assert(
  shellSource.includes("if (path === '/pc/resident-attendance')"),
  'detail route keeps the NHG Resident Attendance navigation item active',
)

assert(apiSource.includes("httpClient.get('/admin/resident-attendance'"))
assert(apiSource.includes('`/admin/resident-attendance/${encodeURIComponent(residentId)}`'))
for (const queryName of [
  'programme_code',
  'search',
  'posting_code',
  'reporting_period_id',
  'date_from',
  'date_to',
  'source',
  'status',
  'limit',
  'offset',
]) {
  assert(apiSource.includes(queryName), `API maps ${queryName}`)
}
assert(apiSource.includes("buildAdminDemoHeaders(adminId, programmeScope, 'programme')"))
assert.equal(/httpClient\.(post|put|patch|delete)/.test(apiSource), false, 'PC attendance API is GET-only')
assert.equal(apiSource.includes('external_attendance_records'), false)
assert.equal(apiSource.includes('externalResident'), false)

assert(overviewSource.includes('title="NHG Resident Attendance"'))
assert(overviewSource.includes('Resident name or MCR'))
assert(overviewSource.includes('Current posting'))
assert(overviewSource.includes('Total attendance submissions'))
assert(overviewSource.includes('View attendance'))
assert(overviewSource.includes('pcResidentAttendanceDetailPath(resident.residentId)'))
assert(overviewSource.includes('No NHG residents found for the selected filters.'))
assert(overviewSource.includes('Loading NHG residents...'))
assert(overviewSource.includes('Retry'))
assert(overviewSource.includes('Previous') && overviewSource.includes('Next'))
assert(
  overviewSource.indexOf('<th>Total attendance submissions</th>')
    < overviewSource.indexOf('<th>Action</th>'),
  'overview keeps distinct attendance-count and Action headers',
)
assert(
  /\.pc-resident-attendance-overview-table th:nth-child\(6\),[\s\S]*?width: 220px;/.test(stylesSource)
    && /\.pc-resident-attendance-overview-table th:nth-child\(7\),[\s\S]*?width: 180px;/.test(stylesSource),
  'overview count and Action columns have independent usable widths',
)

assert(detailSource.includes('useParams<{ residentId: string }>()'))
assert(detailSource.includes('Back to NHG Resident Attendance'))
assert(detailSource.includes('Resident name'))
assert(detailSource.includes('MCR'))
assert(detailSource.includes('Programme'))
assert(detailSource.includes('R year'))
assert(detailSource.includes('Current posting'))
assert(detailSource.includes('Teaching/session name'))
assert(detailSource.includes('Date'))
assert(detailSource.includes('Time'))
assert(detailSource.includes('Posting'))
assert(detailSource.includes('Source'))
assert(detailSource.includes('Status'))
assert(detailSource.includes('No attendance submissions found for this resident.'))
assert(detailSource.includes('Loading resident attendance history...'))
assert(detailSource.includes('Retry'))

for (const filter of [
  'Reporting period',
  'Posting',
  'Date from',
  'Date to',
  'Source',
  'Status',
]) {
  assert(detailSource.includes(filter), `detail exposes ${filter} filter`)
}
assert(detailSource.includes('Apply filters') && detailSource.includes('Clear filters'))
assert(detailSource.includes('onSubmit={applyFilters}'))
assert(detailSource.includes('onClick={clearFilters}'))
assert(
  stylesSource.includes('minmax(12rem, 1.2fr)')
    && stylesSource.includes('minmax(13.5rem, auto)')
    && stylesSource.includes('@media (max-width: 1380px)'),
  'history filters use a compact single-row desktop grid with responsive wrapping',
)

for (const pageSource of [overviewSource, detailSource]) {
  assert(pageSource.includes('responsive-card-list'))
  assert(pageSource.includes('table-scroll'))
  assert.equal(pageSource.includes('DetailDrawer'), false)
  assert.equal(pageSource.includes('window.confirm'), false)
  assert.equal(pageSource.includes('removeResidentAttendance'), false)
  assert.equal(pageSource.includes('deleteResidentAttendance'), false)
  assert.equal(pageSource.includes('Compliance'), false)
  assert.equal(pageSource.includes('traffic-light'), false)
  assert.equal(pageSource.includes('target_70'), false)
  assert.equal(pageSource.includes('target_100'), false)
}

assert(stylesSource.includes('.pc-resident-attendance-mobile-list'))
assert(stylesSource.includes('@media (max-width: 640px)'))
assert(stylesSource.includes('.pc-resident-attendance-table-card .table-scroll'))
assert(
  stylesSource.includes('overflow-x: auto'),
  'desktop table overflow remains contained by the shared table scroller',
)

assert(
  overviewSource.includes('filtersAuthenticationContextKey')
  && overviewSource.includes('visibleDraftFilters')
  && overviewSource.includes('effectiveAppliedFilters'),
  'overview gates visible and request-side filters to the active PC auth context',
)
assert(
  detailSource.includes('filtersViewContextKey')
  && detailSource.includes('visibleDraftFilters')
  && detailSource.includes('effectiveAppliedFilters'),
  'detail gates visible and request-side filters to the active PC/resident context',
)
assert(
  overviewSource.includes('authenticationContextKey !== authenticationContextKeyRef.current')
  && detailSource.includes('viewContextKey !== viewContextKeyRef.current'),
  'stale prior-context responses cannot restore resident data',
)

assert(nonNhgSource.includes('title="Non-NHG Attendance"'))
assert.equal(nonNhgSource.includes('PcResidentAttendancePage'), false)
assert(nonNhgSource.includes('IconRefresh'))
assert(nonNhgSource.includes('Export XLSX'))
for (const filter of ['Start date', 'End date', 'Home cluster', 'Posting', 'MCR', 'Status']) {
  assert(nonNhgSource.includes(filter), `Non-NHG Attendance retains ${filter}`)
}
assert(nonNhgSource.includes('pc-attendance-page external-attendance-page'))
assert(nonNhgSource.includes('pc-attendance-filter-card external-attendance-filters'))
assert(nonNhgSource.includes('pc-attendance-table-card external-attendance-table-card'))
assert(nonNhgSource.includes('pc-attendance-mobile-list external-attendance-mobile-list'))
assert(nonNhgSource.includes('Loading Non-NHG attendance...'))
assert(nonNhgSource.includes('No Non-NHG attendance found.'))
assert(nonNhgSource.includes('Retry'))
assert(nonNhgSource.includes('<th>Status</th>'))
assert(nonNhgSource.includes('StatusBadge tone={statusTone(row.status)}'))
assert.equal(nonNhgSource.includes('MetricTile'), false)
assert.equal(nonNhgSource.includes('external-attendance-metrics'), false)
assert.equal(nonNhgSource.includes('resident-submissions-mobile-summary-card'), false)
assert.equal(nonNhgSource.includes('summary.submittedCount'), false)
assert.equal(/\b(Edit|Delete|Remove|Force delete)\b/.test(nonNhgSource), false)
assert.equal(nonNhgSource.includes('target_70'), false)
assert.equal(nonNhgSource.includes('target_100'), false)
