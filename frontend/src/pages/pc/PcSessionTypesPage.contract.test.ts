import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { getRouteAccessDecision, routeAccessRules } from '../../routeGuards.ts'
import { resolvePcProgrammeScope } from './pcUploadTtfPageLogic.ts'
import {
  MAX_BULK_MAPPING_ITEMS,
  prepareBulkMappingChanges,
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

const mapping = (overrides: Record<string, unknown> = {}) => ({
  id: 'mapping-1',
  teachingNameId: 'name-1',
  teachingName: 'Ward teaching',
  teachingNameIsActive: true,
  teachingNameRevision: 1,
  reportingPeriodId: 'period-1',
  programmeCode: 'PC-1',
  postingCode: 'POST-1',
  rYear: 'R1',
  teachingTargetId: null,
  state: 'pending' as const,
  revision: 1,
  availableTargetOptions: [target],
  ...overrides,
})

test('Session Types route is Programme PC-only and is registered in navigation', () => {
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
  assert.equal(coordinator.tryBegin('bulk-impact-preview'), false)
  assert.equal(coordinator.openOverlay('name-drawer'), false)
  assert.equal(coordinator.replacePendingWithOverlay('mapping-impact-preview', 'single-confirmation'), true)
  assert.deepEqual(coordinator.snapshot(), { pendingAction: null, overlay: 'single-confirmation' })
  assert.equal(coordinator.tryBegin('lifecycle-mutation'), false)

  assert.equal(coordinator.openOverlay('name-drawer'), true)
  assert.deepEqual(coordinator.snapshot(), { pendingAction: null, overlay: 'name-drawer' })
  assert.equal(coordinator.beginWithinOverlay('name-drawer', 'lifecycle-mutation'), true)
  assert.equal(coordinator.openOverlay('bulk-confirmation'), false)
  assert.equal(coordinator.tryBegin('mapping-impact-preview'), false)
  assert.equal(coordinator.complete('lifecycle-mutation'), true)

  assert.equal(coordinator.openOverlay('bulk-confirmation'), true)
  assert.deepEqual(coordinator.snapshot(), { pendingAction: null, overlay: 'bulk-confirmation' })
  assert.equal(coordinator.closeOverlay('bulk-confirmation'), true)
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
  assert.match(pageSource, /Pending names remain available for events and attendance\./)
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
  assert.match(pageSource, /future classification on the next read/)
  assert.match(pageSource, /does not edit historical events or attendance records/)

  assert.match(apiSource, /metadata\.impact/)
  assert.match(apiSource, /affected_event_count/)
  assert.match(apiSource, /affected_attendance_count/)
})

test('bulk mapping is bounded, validates every selected exact target, and reports all-or-nothing behavior', () => {
  assert.equal(MAX_BULK_MAPPING_ITEMS, 100)
  assert.equal(targetOptionLabel(target), 'Teaching round — 3 per month · tracked · not reallocatable · tag: Core')

  const ready = prepareBulkMappingChanges(
    [mapping()],
    new Set(['mapping-1']),
    { 'mapping-1': 'target-1' },
  )
  assert.deepEqual(ready, {
    kind: 'ready',
    items: [{ mappingId: 'mapping-1', expectedRevision: 1, teachingTargetId: 'target-1' }],
  })

  const unchanged = prepareBulkMappingChanges(
    [mapping({ teachingTargetId: 'target-1', state: 'mapped' })],
    new Set(['mapping-1']),
    { 'mapping-1': 'target-1' },
  )
  assert.equal(unchanged.kind, 'invalid')

  const tooMany = Array.from({ length: MAX_BULK_MAPPING_ITEMS + 1 }, (_, index) =>
    mapping({ id: `mapping-${index}` }),
  )
  const oversized = prepareBulkMappingChanges(
    tooMany,
    new Set(tooMany.map((row) => row.id)),
    Object.fromEntries(tooMany.map((row) => [row.id, 'target-1'])),
  )
  assert.deepEqual(oversized, {
    kind: 'invalid',
    message: 'Bulk mapping is limited to 100 rows.',
  })

  assert.match(pageSource, /Bulk changes are atomic: if any selected row is invalid or stale, no row is applied\./)
  assert.match(pageSource, /Confirm atomic bulk change/)
  assert.match(pageSource, /All rows are applied together or none are applied\./)
  assert.equal(pageSource.includes('CSV'), false)
  assert.equal(pageSource.includes('type="file"'), false)
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
  assert.match(pageSource, /aria-pressed=\{mappingFilter === value\}/)
  assert.match(pageSource, /aria-label=\{value === 'all' \? 'Show all mappings' : `Show \$\{value\} mappings`\}/)
  assert.match(pageSource, /aria-pressed=\{nameFilter === value\}/)
  assert.match(pageSource, /aria-label=\{value === 'all' \? 'Show all Names of Teaching' : `Show \$\{value\} Names of Teaching`\}/)
  assert.match(pageSource, /const interactionLocked = interaction\.pendingAction !== null \|\| interaction\.overlay !== null/)
  assert.match(pageSource, /beginInteraction\('mapping-impact-preview'\)/)
  assert.match(pageSource, /beginInteraction\('bulk-impact-preview'\)/)
  assert.match(pageSource, /beginInteraction\('lifecycle-mutation'\)/)
  assert.match(pageSource, /open=\{interaction\.overlay === 'single-confirmation' && singleConfirmation !== null\}/)
  assert.match(pageSource, /open=\{interaction\.overlay === 'bulk-confirmation' && bulkConfirmation !== null\}/)
  assert.match(pageSource, /disabled=\{interactionLocked\}/)
  assert.match(cssSource, /\.pc-session-types-mobile-list/)
  assert.match(cssSource, /@media \(max-width: 720px\)/)
  assert.match(cssSource, /grid-template-columns: 1fr;/)
  assert.match(drawerSource, /role="dialog"/)
  assert.match(drawerSource, /createPortal/)
  assert.match(drawerSource, /setAttribute\('inert', ''\)/)
  assert.match(drawerSource, /focusTrapTargetIndex/)
  assert.match(drawerSource, /previousActiveElement\.focus\(\)/)
})
