import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  adminEventForceDeleteSuccessMessage,
  adminEventListOffsetAfterDeletion,
  adminTeachingEventSourceLabel,
  canCloseAdminEventDetail,
  isAdminEventForceDeleteConfirmationValid,
} from './adminSecretaryEventsPageLogic.ts'
import { resolveAdminSecretaryEventSourceType } from '../../api/adminSecretaryEventSource.ts'

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

const assertOrdered = (source: string, snippets: string[], label: string) => {
  let previousIndex = -1
  for (const snippet of snippets) {
    const index = source.indexOf(snippet)
    if (index === -1) {
      throw new Error(`${label}: missing ${snippet}`)
    }
    if (index <= previousIndex) {
      throw new Error(`${label}: ${snippet} is out of order`)
    }
    previousIndex = index
  }
}

assertEqual(adminTeachingEventSourceLabel('secretary'), 'Secretary', 'Secretary source badge label')
assertEqual(
  adminTeachingEventSourceLabel('programme_pc'),
  'Programme PC',
  'Programme PC source badge label',
)
assertEqual(
  isAdminEventForceDeleteConfirmationValid('Operational duplicate', 'DELETE'),
  true,
  'non-blank reason and exact confirmation enable force deletion',
)
assertEqual(
  isAdminEventForceDeleteConfirmationValid('   ', 'DELETE'),
  false,
  'blank reason cannot enable force deletion',
)
assertEqual(
  isAdminEventForceDeleteConfirmationValid('Operational duplicate', 'delete'),
  false,
  'confirmation is case-sensitive',
)
assertEqual(
  isAdminEventForceDeleteConfirmationValid('Operational duplicate', ' DELETE '),
  false,
  'confirmation must not accept surrounding whitespace',
)
assertEqual(
  canCloseAdminEventDetail(false),
  true,
  'detail drawer may close when no force deletion is pending',
)
assertEqual(
  canCloseAdminEventDetail(true),
  false,
  'Escape, backdrop, close button, and event switching stay blocked while deletion is pending',
)
assertEqual(
  adminEventListOffsetAfterDeletion(25, 1, 25),
  0,
  'deleting the only row on a later page returns to the preceding page',
)
assertEqual(
  adminEventListOffsetAfterDeletion(25, 2, 25),
  25,
  'deleting a row from a non-empty later page preserves its offset',
)
assertEqual(
  resolveAdminSecretaryEventSourceType('programme_pc'),
  'programme_pc',
  'valid Programme PC source is preserved',
)
assertEqual(
  resolveAdminSecretaryEventSourceType(undefined, { createdForProgrammeCode: 'DR' }),
  'programme_pc',
  'missing legacy source uses the authoritative owner marker',
)
assertEqual(
  resolveAdminSecretaryEventSourceType(undefined, { createdForProgrammeCode: null }),
  'secretary',
  'missing legacy source without an owner is Secretary',
)
let invalidSourceRejected = false
try {
  resolveAdminSecretaryEventSourceType('resident')
} catch {
  invalidSourceRejected = true
}
assert(invalidSourceRejected, 'unknown source values fail closed instead of becoming Secretary')
assertEqual(
  adminEventForceDeleteSuccessMessage({
    eventId: 'event-1',
    deleted: true,
    sourceType: 'programme_pc',
    nativeAttendanceDeleted: 2,
    externalAttendanceDeleted: 1,
    totalAttendanceDeleted: 3,
  }),
  'Deleted event and 3 attendance submissions (2 NHG Resident, 1 Non-NHG Resident).',
  'success message reports all deleted attendance counts',
)

const pageSource = readFileSync(
  fileURLToPath(new URL('./AdminSecretaryEventsPage.tsx', import.meta.url)),
  'utf8',
)
const apiSource = readFileSync(
  fileURLToPath(new URL('../../api/adminSecretaryEvents.ts', import.meta.url)),
  'utf8',
)
const navigationSource = readFileSync(
  fileURLToPath(new URL('../../config/navigation.ts', import.meta.url)),
  'utf8',
)
const homeSource = readFileSync(
  fileURLToPath(new URL('./AdminHomePage.tsx', import.meta.url)),
  'utf8',
)
const stylesheetSource = readFileSync(
  fileURLToPath(new URL('../../index.css', import.meta.url)),
  'utf8',
)

assert(
  navigationSource.includes("label: 'Secretary/PC Events'") &&
    navigationSource.includes("'/admin/secretary-events': ['Master Admin', 'Secretary/PC Events']"),
  'Master Admin navigation and breadcrumb use Secretary/PC Events',
)
assert(
  homeSource.includes("title: 'Secretary/PC Events'") &&
    homeSource.includes('Review scheduled Secretary and Programme PC teaching events.'),
  'Admin Home workspace tile uses the renamed surface and inclusive helper copy',
)
assert(
  pageSource.includes('title="Secretary/PC Events"') &&
    pageSource.includes('Loading Secretary/PC events...') &&
    pageSource.includes('Secretary/PC events could not be loaded.') &&
    pageSource.includes('No Secretary/PC events yet') &&
    pageSource.includes('Secretary/PC scheduled events'),
  'page heading, loading, error, empty, and helper copy describe Secretary/PC Events',
)

assert(
  pageSource.includes('<option value="all">All sources</option>') &&
    pageSource.includes('<option value="secretary">Secretary</option>') &&
    pageSource.includes('<option value="programme_pc">Programme PC</option>') &&
    pageSource.includes('sourceType: filters.sourceType'),
  'source filter exposes all, Secretary, and Programme PC choices and reaches the list client',
)
assert(
  apiSource.includes('resolveAdminSecretaryEventSourceType') &&
    apiSource.includes("addStringParam(queryParams, 'source_type', params.sourceType)"),
  'API client models the authoritative source type and sends the source filter',
)
assert(
    apiSource.includes('createdForProgrammeCode: optionalString(value.created_for_programme_code)') &&
    apiSource.includes('isAdhoc: toBoolean(value.is_adhoc)') &&
    apiSource.includes('value.native_attendance_count') &&
    apiSource.includes('value.non_nhg_attendance_count') &&
    apiSource.includes('value.total_attendance_count') &&
    apiSource.includes('forceDeleteAllowed: toBoolean(value.force_delete_allowed)'),
  'API client exposes owner, ad-hoc, split/total attendance, and force-delete eligibility fields',
)

assert(
  pageSource.includes('label={adminTeachingEventSourceLabel(event.sourceType)}') &&
    pageSource.includes('label={adminTeachingEventSourceLabel(activeDetail.sourceType)}'),
  'desktop/mobile rows and detail drawer use clear authoritative source badges',
)
assert(
  pageSource.includes("event.sourceType === 'programme_pc' && event.createdForProgrammeCode") &&
    pageSource.includes('Owner programme: {event.createdForProgrammeCode}') &&
    pageSource.includes("activeDetail.sourceType === 'programme_pc' && activeDetail.createdForProgrammeCode") &&
    pageSource.includes('<DetailField label="Owner programme" value={activeDetail.createdForProgrammeCode} />'),
  'Programme PC owner renders conditionally in list/card and detail without inventing Secretary ownership',
)
assert(
    pageSource.includes('NHG {event.nativeAttendanceCount}') &&
    pageSource.includes('Non-NHG {event.externalAttendanceCount}') &&
    pageSource.includes('Total {event.totalAttendanceCount}') &&
    pageSource.includes('label="Total attendance"'),
  'cards and detail expose native, Non-NHG, and total attendance counts',
)

assert(
  apiSource.includes('/force-delete`') &&
    apiSource.includes('expected_native_attendance_count: expectedNativeAttendanceCount') &&
    apiSource.includes('expected_external_attendance_count: expectedExternalAttendanceCount') &&
    !apiSource.includes('httpClient.delete(`/admin/secretary-events'),
  'Master Admin API client uses only the dedicated force-delete action endpoint',
)
assert(
  !pageSource.includes('deleteSecretaryTeachingEvent') &&
    !pageSource.includes('deleteProgrammeTeachingEvent') &&
    !pageSource.includes('/secretary/teaching-events') &&
    !pageSource.includes('/admin/programme-teaching-events'),
  'Master Admin page never calls Secretary or Programme PC mutation endpoints',
)
assert(
  pageSource.includes("role === 'master_admin'") &&
    pageSource.includes('currentDetail?.forceDeleteAllowed') &&
    pageSource.includes('!currentDetail.isAdhoc') &&
    pageSource.includes('Delete event'),
  'Delete event action is limited in the UI to eligible scheduled Master Admin detail',
)
assert(
  pageSource.includes(
    'This permanently deletes the event and all linked attendance submissions. This action cannot be undone.',
  ) &&
    pageSource.includes('NHG Resident attendance submissions') &&
    pageSource.includes('Non-NHG Resident attendance submissions') &&
    pageSource.includes('total attendance submissions'),
  'confirmation state gives the irreversible warning and exact attendance impact',
)
assert(
  pageSource.includes('disabled={!deleteConfirmationValid || deletePending}') &&
    pageSource.includes('reason: deleteReason.trim()') &&
    pageSource.includes('confirmation: deleteConfirmation') &&
    pageSource.includes('expectedNativeAttendanceCount: currentDetail.attendanceCounts.native') &&
    pageSource.includes('expectedExternalAttendanceCount: currentDetail.attendanceCounts.external') &&
    pageSource.includes("deletePending ? 'Deleting event...'"),
  'confirmation requires reason, exact DELETE, bound impact counts, and prevents duplicate submission',
)

const forceDeleteStart = pageSource.indexOf('const submitForceDelete = async () =>')
const forceDeleteBlock = pageSource.slice(
  forceDeleteStart,
  pageSource.indexOf('\n  if (authenticationResetPending)', forceDeleteStart),
)
assertOrdered(
  forceDeleteBlock,
  [
    'setDeleteSuccess(adminEventForceDeleteSuccessMessage(result))',
    'closeDetail()',
    'await fetchEvents(false)',
  ],
  'successful force deletion closes detail and then refreshes rows and metrics',
)
assert(
  forceDeleteBlock.includes('requestController.runMutationRequest') &&
    forceDeleteBlock.includes('setDeleteError(formatUserFacingApiError(mutationResult.error') &&
    forceDeleteBlock.includes("if (errorStatus === 409)") &&
    forceDeleteBlock.includes("setDeleteConfirmation('')") &&
    !forceDeleteBlock.includes("setDeleteReason('')") &&
    !forceDeleteBlock.includes('setEvents('),
  'failed force deletion preserves reason/event, refreshes changed impact, and shows a safe error',
)
assert(
  pageSource.includes('admin-secretary-events-mobile-card') &&
    pageSource.includes('aria-label={`Open Secretary/PC event detail') &&
    pageSource.includes('footer={currentDetail && canForceDelete') &&
    stylesheetSource.includes('.admin-event-delete-footer-actions') &&
    stylesheetSource.includes('.admin-event-delete-impact'),
  'mobile/card rendering retains source access and a responsive destructive drawer action',
)
assert(
  pageSource.includes('onClose={requestCloseDetail}') &&
    pageSource.includes('closeDisabled={deletePending}') &&
    pageSource.includes('busy={deletePending}') &&
    pageSource.includes("deleteReasonInputRef.current?.focus()") &&
    pageSource.includes('if (canCloseAdminEventDetail(deletePending))') &&
    pageSource.includes('if (!canCloseAdminEventDetail(deletePending))'),
  'pending close paths are disabled and confirmation focus is managed',
)
assert(
  stylesheetSource.includes('repeat(6, minmax(118px, 1fr))') &&
    stylesheetSource.includes('@media (max-width: 1480px)') &&
    stylesheetSource.includes('@media (max-width: 720px)') &&
    stylesheetSource.includes('.admin-event-delete-confirmation input') &&
    stylesheetSource.includes('.admin-event-delete-impact {\n    grid-template-columns: 1fr;'),
  'source filter and confirmation impact remain responsive without page-level overflow',
)
