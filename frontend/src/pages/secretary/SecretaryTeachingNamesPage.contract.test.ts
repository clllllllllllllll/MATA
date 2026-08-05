import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { getRouteAccessDecision, routeAccessRules } from '../../routeGuards.ts'

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const pageSource = read('./SecretaryTeachingNamesPage.tsx')
const namesApiSource = read('../../api/secretaryTeachingNames.ts')
const scheduleSource = read('./SecretaryTeachingSchedulePage.tsx')
const eventsApiSource = read('../../api/secretaryEvents.ts')
const teachingNameStateSource = read('../../utils/secretaryTeachingNameState.ts')
const teachingNameLifecycleSource = read('../../utils/secretaryTeachingNameLifecycle.ts')
const scheduleStateSource = read('../../utils/secretaryTeachingScheduleState.ts')
const appSource = read('../../App.tsx')
const navigationSource = read('../../config/navigation.ts')
const cssSource = read('../../index.css')
const drawerSource = read('../../components/DetailDrawer.tsx')

test('Secretary Teaching Name route is protected for Secretary only', () => {
  assert.ok(routeAccessRules.some((rule) => rule.path === '/secretary/teaching-names'))
  assert.equal(getRouteAccessDecision({
    pathname: '/secretary/teaching-names',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'secretary',
  }).kind, 'allow')
  assert.deepEqual(getRouteAccessDecision({
    pathname: '/secretary/teaching-names',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'programme_pc',
  }), {
    kind: 'redirect_to_role_default',
    to: '/pc/teaching-events',
  })
  assert.match(appSource, /path="\/secretary\/teaching-names"/)
  assert.match(navigationSource, /label: 'Update Names of Teaching'/)
})

test('Secretary management uses only backend-derived capability and scoped lifecycle APIs', () => {
  assert.match(namesApiSource, /get\('\/secretary\/teaching-name-programmes'/)
  assert.match(namesApiSource, /reporting_period_id: params\.reportingPeriodId/)
  assert.match(namesApiSource, /programme_code: params\.programmeCode/)
  assert.match(namesApiSource, /expected_revision: params\.expectedRevision/)
  assert.match(namesApiSource, /data: \{ expected_revision: params\.expectedRevision \}/)
  assert.equal(namesApiSource.includes('force_delete'), false)
  assert.equal(namesApiSource.includes('/admin/teaching-names'), false)
  assert.match(pageSource, /No Teaching Name access/)
  assert.match(pageSource, /isSingleProgramme \? \(/)
  assert.match(pageSource, /programmes\.length > 1 \? \(/)
  assert.match(pageSource, /setSelectedProgrammeCode\(event\.target\.value\)/)
  assert.match(pageSource, /setReportingPeriodId\(period\.id\)/)
  assert.equal(pageSource.includes('native_teaching_posting_code'), false)
  assert.equal(pageSource.includes('mapping'), false)
})

test('Secretary lifecycle handles list states and controlled mutation conflicts', () => {
  assert.match(pageSource, /type LifecycleFilter = 'active' \| 'inactive' \| 'all'/)
  assert.match(pageSource, /No Names of Teaching match this scope\./)
  assert.match(pageSource, /createSecretaryTeachingName/)
  assert.match(pageSource, /renameSecretaryTeachingName/)
  assert.match(pageSource, /deactivateSecretaryTeachingName/)
  assert.match(pageSource, /reactivateSecretaryTeachingName/)
  assert.match(pageSource, /deleteSecretaryTeachingName/)
  assert.match(pageSource, /resolveTeachingNameLifecycleError/)
  assert.match(teachingNameStateSource, /resolveTeachingNameLifecycleConflict/)
  assert.match(teachingNameLifecycleSource, /already exists in the selected programme and reporting period/)
  assert.match(teachingNameLifecycleSource, /changed by someone else\. Refresh the list and retry\./)
  assert.match(teachingNameLifecycleSource, /in use and cannot be deleted\. Deactivate it instead\./)
  assert.match(pageSource, /Refresh list/)
  assert.match(pageSource, /\[selectedProgrammeCode, selectedPeriodId\]/)
  assert.match(pageSource, /setNames\(\[\]\)/)
  assert.match(pageSource, /selectedScopeRef\.current !== requestedScopeKey/)
  assert.match(pageSource, /namesRequestFenceRef\.current\.isCurrent/)
})

test('Secretary schedule uses exact active source IDs from the selected programme', () => {
  assert.match(eventsApiSource, /programme_code: params\?\.programmeCode \|\| undefined/)
  assert.match(scheduleSource, /programmeCode: selectedTeachingNameProgrammeCode \|\| undefined/)
  assert.match(scheduleSource, /listSecretaryTeachingNameProgrammes/)
  assert.match(scheduleSource, /Teaching Name programme/)
  assert.match(eventsApiSource, /teaching_name_id: payload\.teachingNameId \?\? null/)
  assert.match(eventsApiSource, /global_session_type_id: payload\.globalSessionTypeId \?\? null/)
  assert.equal(eventsApiSource.includes('teaching_name: payload.'), false)
  assert.match(scheduleSource, /1 hour \(fixed\)/)
  assert.match(scheduleSource, /End time is calculated by the server\./)
  assert.match(scheduleSource, /poolStartTimeValidationError/)
  assert.match(scheduleStateSource, /Pool-backed teaching events must start no later than 23:00\./)
  assert.match(scheduleSource, /serverComputedPoolEndTime/)
  assert.match(scheduleSource, /Source programme/)
  assert.match(scheduleSource, /prepareEventSourceProgramme/)
  assert.match(scheduleSource, /shouldTemporarilyRetainPoolSource/)
  assert.match(scheduleSource, /isCurrentTeachingSourceEligible/)
  assert.match(scheduleSource, /poolSourceRequiresReselection/)
  assert.match(scheduleSource, /pendingSourceProgrammeContextKey/)
  assert.match(eventsApiSource, /sourceProgrammeCode: optionalString\(value\.source_programme_code\)/)
  assert.match(eventsApiSource, /'\/secretary\/teaching-events\/duplicate'/)
  assert.match(scheduleSource, /START_TIME_OPTIONS/)
  assert.match(scheduleSource, /nameOptionsRequestFenceRef\.current\.isCurrent/)
  assert.match(scheduleSource, /nameOptionsContextKeyRef\.current !== requestedOptionsContextKey/)
  assert.equal(scheduleSource.includes('mapping controls'), false)
})

test('Secretary Teaching Name page keeps mobile and dialog controls accessible', () => {
  assert.match(pageSource, /aria-label="Programme"/)
  assert.match(pageSource, /Search Names of Teaching/)
  assert.match(pageSource, /role="alert"/)
  assert.match(pageSource, /secretary-teaching-names-mobile-list/)
  assert.match(cssSource, /\.secretary-teaching-names-mobile-list/)
  assert.match(cssSource, /@media \(max-width: 720px\)/)
  assert.match(cssSource, /grid-template-columns: 1fr;/)
  assert.match(drawerSource, /role="dialog"/)
  assert.match(drawerSource, /createPortal/)
  assert.match(drawerSource, /setAttribute\('inert', ''\)/)
  assert.match(drawerSource, /focusTrapTargetIndex/)
  assert.match(drawerSource, /requestAnimationFrame/)
  assert.match(drawerSource, /previousActiveElement\.focus\(\)/)
})
