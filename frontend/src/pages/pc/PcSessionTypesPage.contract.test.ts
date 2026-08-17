import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { getRouteAccessDecision, routeAccessRules } from '../../routeGuards.ts'
import { resolvePcProgrammeScope } from './pcUploadTtfPageLogic.ts'
import {
  targetOptionLabel,
} from './pcSessionTypesPageLogic.ts'
import { createPcSessionTypesInteractionCoordinator } from './pcSessionTypesInteractionCoordinator.ts'

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const pageSource = read('./PcSessionTypesPage.tsx')
const apiSource = read('../../api/pcTeachingNameMappings.ts')
const appSource = read('../../App.tsx')
const navigationSource = read('../../config/navigation.ts')
const cssSource = read('../../index.css')
const drawerSource = read('../../components/DetailDrawer.tsx')

const target = {
  id: 'target-1',
  sessionTypeId: 'session-type-1',
  sessionTypeName: 'Teaching round',
  durationHours: 1,
  monthlyTarget: 3,
  isTracked: true,
  isReallocatable: false,
  tag: 'Core',
}

test('Session Types route is PC-only and is registered in navigation', () => {
  assert.ok(routeAccessRules.some((rule) => rule.path === '/pc/session-types'))
  assert.equal(getRouteAccessDecision({
    pathname: '/pc/session-types',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'programme_pc',
  }).kind, 'allow')
  assert.deepEqual(getRouteAccessDecision({
    pathname: '/pc/session-types',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'master_admin',
  }), {
    kind: 'redirect_to_role_default',
    to: '/admin',
  })
  assert.deepEqual(getRouteAccessDecision({
    pathname: '/pc/session-types',
    routeKind: 'protected',
    isLoading: false,
    hasExplicitSession: true,
    role: 'secretary',
  }), {
    kind: 'redirect_to_role_default',
    to: '/secretary/events',
  })
  assert.match(appSource, /path="\/pc\/session-types"/)
  assert.match(navigationSource, /label: 'Session Types'/)
  assert.match(navigationSource, /'\/pc\/session-types': \['PC', 'Session Types'\]/)
})

test('PC scope is persisted, fixed for one programme, selectable for many, and empty means no access', () => {
  assert.equal(resolvePcProgrammeScope([], 'PC-1').mode, 'none')
  assert.equal(resolvePcProgrammeScope(['PC-1'], 'other').mode, 'locked')
  assert.equal(resolvePcProgrammeScope(['PC-1', 'PC-2'], 'PC-2').mode, 'select')
  assert.match(pageSource, /identity\?\.role === 'programme_pc' \? identity\.programmeScope : \[\]/)
  assert.match(pageSource, /No programme scope/)
  assert.match(pageSource, /programmeScope\.mode === 'locked'/)
  assert.match(pageSource, /aria-label="Programme"/)
  assert.match(pageSource, /setSelectedProgrammeCode\(programmeCode\)/)
  assert.match(pageSource, /setReportingPeriodId\(periodId\)/)
  assert.match(pageSource, /clearScopeBoundState\(\)/)
  assert.match(pageSource, /mappingRequestFenceRef\.current\.invalidate\(\)/)
  assert.match(pageSource, /namesRequestFenceRef\.current\.invalidate\(\)/)
})

test('the shared interaction coordinator blocks overlapping work and keeps exactly one overlay', () => {
  const coordinator = createPcSessionTypesInteractionCoordinator()

  assert.deepEqual(coordinator.snapshot(), { pendingAction: null, overlay: null })
  assert.equal(coordinator.tryBegin('mapping-impact-preview'), true)
  assert.equal(coordinator.tryBegin('lifecycle-mutation'), false)
  assert.equal(coordinator.openOverlay('name-drawer'), false)
  assert.equal(coordinator.replacePendingWithOverlay('mapping-impact-preview', 'single-confirmation'), true)
  assert.deepEqual(coordinator.snapshot(), { pendingAction: null, overlay: 'single-confirmation' })
  assert.equal(coordinator.tryBegin('lifecycle-mutation'), false)

  assert.equal(coordinator.openOverlay('name-drawer'), true)
  assert.deepEqual(coordinator.snapshot(), { pendingAction: null, overlay: 'name-drawer' })
  assert.equal(coordinator.beginWithinOverlay('name-drawer', 'lifecycle-mutation'), true)
  assert.equal(coordinator.openOverlay('single-confirmation'), false)
  assert.equal(coordinator.tryBegin('mapping-impact-preview'), false)
  assert.equal(coordinator.complete('lifecycle-mutation'), true)

  assert.equal(coordinator.openOverlay('single-confirmation'), true)
  assert.deepEqual(coordinator.snapshot(), { pendingAction: null, overlay: 'single-confirmation' })
  assert.equal(coordinator.closeOverlay('single-confirmation'), true)
  assert.deepEqual(coordinator.snapshot(), { pendingAction: null, overlay: null })
})

test('mapping adapter preserves the guarded Phase D request shapes and PC lifecycle boundary', () => {
  assert.match(apiSource, /get\('\/admin\/teaching-name-mappings'/)
  assert.match(apiSource, /reporting_period_id: params\.reportingPeriodId/)
  assert.match(apiSource, /programme_code: params\.programmeCode/)
  assert.match(apiSource, /teaching_target_id: params\.teachingTargetId/)
  assert.match(apiSource, /expected_revision: params\.expectedRevision/)
  assert.match(apiSource, /confirm_impact: params\.confirmImpact/)
  assert.match(apiSource, /post\('\/admin\/teaching-name-mappings\/bulk'/)
  assert.match(apiSource, /mapping_id: item\.mappingId/)
  assert.match(apiSource, /httpClient\.delete\(`\/admin\/teaching-names\/\$\{params\.teachingNameId\}`/)
  assert.equal(apiSource.includes('force_delete'), false)
  assert.equal(apiSource.includes('/secretary/teaching-names'), false)
})

test('queue rendering uses backend exact targets with pending and mapped filters, no fuzzy matching, and no personal identifiers', () => {
  assert.match(pageSource, /\['pending', 'mapped', 'all'\]/)
  assert.match(pageSource, /Name of Teaching/)
  assert.match(pageSource, /Exact session type target/)
  assert.match(pageSource, /targetOptionsForMapping\(mapping\)/)
  assert.match(pageSource, /targetOptionLabel\(target\)/)
  assert.doesNotMatch(pageSource, /Pending names remain available with a temporary one-hour event duration until mapped\./)
  assert.match(pageSource, /setMappings\(response\.items\)/)
  assert.equal(pageSource.includes('resident_id'), false)
  assert.equal(pageSource.includes('mcr'), false)
  assert.equal(pageSource.includes('fuzzy'), false)
  assert.equal(pageSource.includes('suggestion'), false)
})

test('single mapping workflow previews count-only impact, supports assign/change/clear, and refreshes stale revisions', () => {
  assert.match(pageSource, /getProgrammePcTeachingNameMappingImpact/)
  assert.match(pageSource, /applyProgrammePcTeachingNameMapping/)
  assert.match(pageSource, /mappingId: mapping\.id/)
  assert.match(pageSource, /expectedRevision: mapping\.revision/)
  assert.match(pageSource, /teachingTargetId,/)
  assert.match(pageSource, /confirmImpact,/)
  assert.match(pageSource, /Clear to pending/)
  assert.match(pageSource, /mergeReturnedMapping\(response\)/)
  assert.match(pageSource, /This mapping changed by someone else\. Refresh the queue and retry\./)
  assert.match(pageSource, /Existing event durations and end times were recalculated/)
  assert.match(pageSource, /Attendance submissions were preserved/)
  assert.match(pageSource, /display the updated event duration/)
  assert.match(pageSource, /conflicting durations/)
  assert.match(pageSource, /No mapping changes were applied/)
  assert.doesNotMatch(pageSource, /A mapping updates existing event duration and end time for the exact scope/)

  assert.match(apiSource, /metadata\.impact/)
  assert.match(apiSource, /affected_event_count/)
  assert.match(apiSource, /affected_attendance_count/)
})

test('the queue presents compact single-row mapping controls without bulk selection', () => {
  assert.equal(targetOptionLabel(target), 'Teaching round — 3 per month · tracked · not reallocatable · tag: Core')
  assert.doesNotMatch(pageSource, /selectedMappingIds/)
  assert.doesNotMatch(pageSource, /Select all visible mappings/)
  assert.doesNotMatch(pageSource, /Select for bulk change/)
  assert.doesNotMatch(pageSource, /Apply prepared changes/)
  assert.doesNotMatch(pageSource, /bulk-confirmation/)
  assert.match(pageSource, /pc-session-types-no-target/)
  assert.match(cssSource, /\.pc-session-types-no-target[\s\S]*white-space: nowrap/)
  assert.match(cssSource, /\.pc-session-types-target-select[\s\S]*width: min\(100%, 340px\)/)
})

test('Teaching Name lifecycle, filters, mobile cards, and confirmation drawers remain accessible', () => {
  assert.match(pageSource, /createProgrammePcTeachingName/)
  assert.match(pageSource, /renameProgrammePcTeachingName/)
  assert.match(pageSource, /deactivateProgrammePcTeachingName/)
  assert.match(pageSource, /reactivateProgrammePcTeachingName/)
  assert.match(pageSource, /deleteProgrammePcTeachingName/)
  assert.match(pageSource, /resolveTeachingNameLifecycleError/)
  assert.match(pageSource, /Delete unused/)
  assert.match(pageSource, /pc-session-types-mobile-list/)
  assert.match(pageSource, /pc-session-types-names-mobile-list/)
  assert.match(pageSource, /aria-label="Mapping state"/)
  assert.match(pageSource, /aria-label="Teaching Name lifecycle state"/)
  assert.equal(
    pageSource.match(/placeholder="Search Name of Teaching"/g)?.length,
    2,
  )
  assert.doesNotMatch(pageSource, /placeholder="Search by name"/)
  assert.doesNotMatch(pageSource, /<span[^>]*>Search Names? of Teaching<\/span>/)
  assert.match(pageSource, /placeholder="Posting"[\s\S]*aria-label="Posting"/)
  assert.match(pageSource, /placeholder="R-year"[\s\S]*aria-label="R-year"/)
  assert.doesNotMatch(pageSource, /<span[^>]*>Posting<\/span>/)
  assert.doesNotMatch(pageSource, /<span[^>]*>R-year<\/span>/)
  assert.doesNotMatch(pageSource, /Department Secretary names appear after an actual resident posting admits them/)
  assert.doesNotMatch(pageSource, /PC · NHG names are managed here/)
  assert.doesNotMatch(pageSource, /mappingTotal} mapping/)
  assert.doesNotMatch(pageSource, /onClick=\{\(\) => void loadTeachingNames\(\)\} disabled=\{namesLoading \|\| interactionLocked\}/)
  assert.match(pageSource, /aria-pressed=\{mappingFilter === value\}/)
  assert.match(pageSource, /aria-label=\{value === 'all' \? 'Show all mappings' : `Show \$\{value\} mappings`\}/)
  assert.match(pageSource, /aria-pressed=\{nameFilter === value\}/)
  assert.match(pageSource, /aria-label=\{value === 'all' \? 'Show all Names of Teaching' : `Show \$\{value\} Names of Teaching`\}/)
  assert.match(pageSource, /const interactionLocked = interaction\.pendingAction !== null \|\| interaction\.overlay !== null/)
  assert.match(pageSource, /beginInteraction\('mapping-impact-preview'\)/)
  assert.match(pageSource, /beginInteraction\('lifecycle-mutation'\)/)
  assert.match(pageSource, /open=\{interaction\.overlay === 'single-confirmation' && singleConfirmation !== null\}/)
  assert.match(pageSource, /disabled=\{interactionLocked\}/)
  assert.match(cssSource, /\.pc-session-types-mobile-list/)
  assert.match(cssSource, /@media \(max-width: 720px\)/)
  assert.match(cssSource, /grid-template-columns: 1fr;/)
  assert.match(drawerSource, /role="dialog"/)
  assert.match(drawerSource, /createPortal/)
  assert.match(drawerSource, /setAttribute\('inert', ''\)/)
  assert.match(drawerSource, /focusTrapTargetIndex/)
  assert.match(drawerSource, /previousActiveElement\.focus\(\)/)
  assert.match(pageSource, /mappingGroups/)
  assert.match(pageSource, /expandedMappingGroupIds/)
  assert.match(pageSource, /aria-expanded=\{expanded\}/)
  assert.match(pageSource, /mappedCount} of \{group\.items\.length} mapped/)
  assert.doesNotMatch(pageSource, /<th>Revision<\/th>/)
  assert.match(pageSource, /Programme options are limited to your current PC scope:/)
  assert.match(pageSource, /Department Secretary-created Names of Teaching can only be edited or deleted by that Department Secretary\./)
  assert.match(pageSource, /PCs can manage only PC-created Names of Teaching in their programme\./)
  assert.doesNotMatch(pageSource, /<h2>Scope<\/h2>/)
  assert.doesNotMatch(pageSource, /callout-warning pc-session-types-pending-callout/)
  assert.match(cssSource, /\.pc-session-types-group-summary-row td[\s\S]*background: #fff/)
})

test('cross-posting source provenance is visible and Department Secretary lifecycle controls are read-only', () => {
  assert.match(apiSource, /teaching_name_owner_programme_code/)
  assert.match(apiSource, /teaching_name_origin_posting_code/)
  assert.match(apiSource, /teaching_name_admission_reason/)
  assert.match(pageSource, /Department Secretary/)
  assert.match(pageSource, /name\.canManageName \? \(/)
  assert.doesNotMatch(pageSource, /Source owner manages this name/)
  assert.match(pageSource, /pc-session-types-name-state-cell/)
  assert.match(pageSource, /pc-session-types-name-actions-cell/)
  assert.match(cssSource, /\.pc-session-types-names-table-wrap \.table \.pc-session-types-name-state-cell,[\s\S]*text-align: center/)
  assert.match(pageSource, /Add PC Name of Teaching/)
  assert.match(pageSource, /PC \\u00b7 NHG/)
  assert.doesNotMatch(pageSource, /private to this programme/)
})
