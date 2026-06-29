import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import {
  buildProgrammeTeachingEventPayload,
  canMutateProgrammeTeachingEvent,
  createdByRoleLabel,
  postingOptionsForTeachingName,
} from './pcTeachingEventsPageLogic.ts'
import { resolvePcProgrammeScope } from './pcUploadTtfPageLogic.ts'
import type { Programme } from '../../api/programmes'

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

const scope = resolvePcProgrammeScope(['DR', 'GERI'], 'GERI')
assertEqual(scope.mode, 'select', 'multi-programme PC keeps programme selector mode')
assertEqual(scope.selectedProgrammeCode, 'GERI', 'PC selected programme remains raw code')

const programmeCatalogue = [
  {
    id: '1',
    code: 'DR',
    name: 'Diagnostic Radiology',
    ayDateCategory: 'non_im_subspec',
    rYearRequired: true,
    isSubspecialty: false,
  },
  {
    id: '2',
    code: 'GERI',
    name: 'Geriatric Medicine',
    ayDateCategory: 'im_subspec',
    rYearRequired: false,
    isSubspecialty: false,
  },
  {
    id: '3',
    code: 'ORTHO',
    name: 'Orthopaedic Surgery',
    ayDateCategory: 'non_im_subspec',
    rYearRequired: false,
    isSubspecialty: false,
  },
] satisfies Programme[]

const singleProgrammeScope = resolvePcProgrammeScope(['DR'], 'GERI', programmeCatalogue)
assertEqual(singleProgrammeScope.mode, 'locked', 'single-programme PC uses read-only programme mode')
assertEqual(
  singleProgrammeScope.selectedProgrammeLabel,
  'DR - Diagnostic Radiology',
  'single-programme PC display includes the canonical full programme name',
)

const namedScope = resolvePcProgrammeScope(['DR', 'GERI'], 'GERI', programmeCatalogue)
assertEqual(namedScope.mode, 'select', 'multi-programme PC keeps dropdown mode with catalogue labels')
assertEqual(namedScope.programmeOptions[0]?.code, 'DR', 'multi-programme dropdown value remains raw DR code')
assertEqual(
  namedScope.programmeOptions[0]?.label,
  'DR - Diagnostic Radiology',
  'multi-programme dropdown displays DR full programme label',
)
assertEqual(namedScope.programmeOptions[1]?.code, 'GERI', 'multi-programme dropdown value remains raw GERI code')
assertEqual(
  namedScope.programmeOptions[1]?.label,
  'GERI - Geriatric Medicine',
  'multi-programme dropdown displays GERI full programme label',
)
assertEqual(
  namedScope.programmeOptions.some((programme) => programme.code === 'ORTHO'),
  false,
  'multi-programme dropdown excludes out-of-scope programme names',
)

const payload = buildProgrammeTeachingEventPayload({
  programmeCode: 'GERI',
  postingCode: 'TTSHGerMed',
  teachingName: ' Journal Club ',
  eventDate: '2026-05-20',
  startTime: '10:00',
  cmePointsAwarded: true,
  smcEventCode: ' SMC-1 ',
})
assertEqual(payload.programmeCode, 'GERI', 'PC payload sends raw programme code')
assertEqual(payload.teachingName, 'Journal Club', 'PC payload trims catalogue teaching name')
assertEqual(payload.smcEventCode, 'SMC-1', 'PC payload trims optional SMC code')

const postingOptions = postingOptionsForTeachingName(
  [
    {
      keyword: 'Journal Club',
      sessionType: 'Department Teaching [1h]',
      isGlobal: false,
      postingCodes: ['TTSHDr', 'NUHDr'],
    },
    {
      keyword: 'Grand Round',
      sessionType: 'Grand Round [1h]',
      isGlobal: false,
      postingCodes: ['TTSHGerMed'],
    },
  ],
  ' Journal Club ',
)
assertEqual(postingOptions.join(','), 'TTSHDr,NUHDr', 'posting dropdown options are filtered by selected teaching name')
assertEqual(
  buildProgrammeTeachingEventPayload({
    programmeCode: 'DR',
    postingCode: postingOptions[0] ?? '',
    teachingName: 'Journal Club',
    eventDate: '2026-05-20',
    startTime: '10:00',
    cmePointsAwarded: false,
    smcEventCode: '',
  }).postingCode,
  'TTSHDr',
  'PC event payload sends the raw selected posting code',
)

assertEqual(createdByRoleLabel('secretary'), 'Created by: Secretary', 'secretary source label is role-only')
assertEqual(createdByRoleLabel('programme_pc'), 'Created by: PC', 'PC source label is role-only')
assertEqual(createdByRoleLabel(undefined), 'Created by: Legacy', 'legacy source label is explicit')

assertEqual(canMutateProgrammeTeachingEvent({ hasAttendance: false }), true, 'events without attendance can be mutated')
assertEqual(canMutateProgrammeTeachingEvent({ hasAttendance: true }), false, 'events with attendance cannot be mutated')

const navigationSource = readFileSync(
  fileURLToPath(new URL('../../config/navigation.ts', import.meta.url)),
  'utf8',
)
assert(navigationSource.includes("path: '/pc/teaching-events'"), 'PC Teaching Events nav item exists')
assert(
  navigationSource.includes("roles: ['programme_pc']"),
  'PC Teaching Events nav is not exposed to master admin',
)

const apiSource = readFileSync(
  fileURLToPath(new URL('../../api/programmeTeachingEvents.ts', import.meta.url)),
  'utf8',
)
assert(!apiSource.includes('X-Actor-Name'), 'PC teaching events API does not send actor-name headers')
assert(!apiSource.includes('created_by_name'), 'PC teaching events API does not map created-by names')

const pageSource = readFileSync(
  fileURLToPath(new URL('./PcTeachingEventsPage.tsx', import.meta.url)),
  'utf8',
)
const stylesheetSource = readFileSync(
  fileURLToPath(new URL('../../index.css', import.meta.url)),
  'utf8',
)
const pcSessionCellRule = stylesheetSource.match(/\.pc-teaching-events-session-cell\s*\{[^}]+\}/)?.[0] ?? ''
const pcSessionPillRule =
  stylesheetSource.match(/\.pc-teaching-events-session-cell \.secretary-type-pill\s*\{[^}]+\}/)?.[0] ?? ''
const pcActionsRules = stylesheetSource.match(/\.pc-teaching-events-actions\s*\{[^}]+\}/g) ?? []
const pcActionsButtonRule = stylesheetSource.match(/\.pc-teaching-events-actions \.button\s*\{[^}]+\}/)?.[0] ?? ''
assert(
  pageSource.includes('pc-programme-readonly-field'),
  'single-scope PC teaching-events programme display uses read-only field styling',
)
assert(pageSource.includes('readOnly'), 'single-scope PC teaching-events programme display is read-only')
assert(
  !pageSource.includes('pc-programme-lock-chip'),
  'single-scope PC teaching-events programme display does not render the old blue chip class',
)
assert(
  !pageSource.includes('Assigned programme:'),
  'single-scope PC teaching-events programme display does not use assigned-programme chip wording',
)
assert(pageSource.includes('Created By'), 'PC teaching-events table still renders Created By')
assert(pageSource.includes('<h2>Teaching schedule</h2>'), 'PC teaching-events table uses Secretary-style title')
assert(pageSource.includes('Add Teaching'), 'PC teaching-events primary action follows Secretary wording')
assertOrdered(
  pageSource,
  ['className="button button-secondary"', '<IconRefresh size={14} />', 'className="button button-primary"', '<IconPlus size={14} />'],
  'PC teaching-events hero actions keep Add Teaching to the right of Refresh',
)
assert(
  pcActionsRules.some((rule) => rule.includes('flex-wrap: nowrap') && rule.includes('width: 100%')),
  'PC teaching-events mobile actions stay side by side across the full row',
)
assert(
  pcActionsButtonRule.includes('flex: 1 1 100%') && pcActionsButtonRule.includes('width: 100%'),
  'PC teaching-events mobile action buttons match Secretary row sizing above the programme controls',
)
assertOrdered(
  pageSource,
  [
    '<th className="col-check" />',
    '<th>Session Type</th>',
    '<th>Name of Teaching</th>',
    '<th>Posting</th>',
    '<th>Date</th>',
    '<th>Start Time</th>',
    '<th>Duration</th>',
    '<th>CME Pts</th>',
    '<th>SMC Event</th>',
    '<th>Created By</th>',
    '<th>Created</th>',
  ],
  'PC desktop table headers match the Secretary-like order',
)
assert(!pageSource.includes('<th>Programme</th>'), 'PC table does not repeat Programme as a column')
assert(!pageSource.includes('pc-teaching-events-row-actions'), 'PC rows do not expose always-visible inline actions')
assert(pageSource.includes('selectedIds'), 'PC teaching-events page tracks row selection state')
assert(pageSource.includes('secretary-selection-toolbar'), 'PC selected-row actions use Secretary-style toolbar')
assert(pageSource.includes('toggleSelected(event.id)'), 'PC rows and cards can toggle selection')
assert(pageSource.includes('aria-label={`Select ${event.teachingName}`}'), 'PC desktop rows expose checkbox selection')
assert(pageSource.includes('showEditButton'), 'PC selected eligible row exposes edit action')
assert(pageSource.includes('showDeleteButton'), 'PC selected eligible rows expose delete action')
assert(pageSource.includes('showDuplicateButton'), 'PC selected row exposes duplicate action')
assert(
  pageSource.includes('Editing and deleting are disabled because attendance has been submitted'),
  'PC attended-row selection blocks edit/delete with Secretary-style messaging',
)
assert(pageSource.includes('secretary-event-card-list'), 'PC mobile layout renders Secretary-style event cards')
assert(pageSource.includes('secretary-event-card-line">Posting'), 'PC mobile card includes posting metadata')
assert(pageSource.includes('createdByRoleLabel(event.createdByRole)'), 'PC mobile card includes Created By metadata')
assert(!pageSource.includes('Programme</span>'), 'PC mobile card does not repeat Programme metadata')
assert(pageSource.includes('secretary-form-grid'), 'PC drawer uses Secretary drawer grid styling')
assert(pageSource.includes('secretary-form-row'), 'PC drawer uses Secretary drawer row grouping')
assert(pageSource.includes('secretary-toggle-block'), 'PC drawer uses Secretary yes/no CME styling')
assert(pageSource.includes('pc-drawer-programme-field'), 'PC drawer includes a scoped programme field at the top')
assert(pageSource.includes('pc-drawer-posting-select'), 'PC drawer uses a posting dropdown when options exist')
assert(
  pageSource.includes('disabled={!formState.teachingName || selectedOptionPostingCodes.length === 0}'),
  'PC drawer does not allow arbitrary posting entry when catalogue posting options are required',
)
assert(
  pageSource.includes('pc-teaching-events-posting-cell pc-teaching-events-nowrap'),
  'PC table keeps Posting cells on one line',
)
assert(
  pageSource.includes('pc-teaching-events-date-cell pc-teaching-events-nowrap mono'),
  'PC table keeps Date cells on one line',
)
assert(
  pageSource.includes('pc-teaching-events-time-cell pc-teaching-events-nowrap mono'),
  'PC table keeps Start Time cells on one line',
)
assert(
  pageSource.includes('pc-teaching-events-created-by-cell pc-teaching-events-nowrap'),
  'PC table keeps Created By cells on one line',
)
assert(
  pageSource.includes('pc-teaching-events-created-cell pc-teaching-events-nowrap'),
  'PC table keeps Created cells on one line',
)
assert(
  stylesheetSource.includes('.pc-teaching-events-nowrap') &&
    stylesheetSource.includes('white-space: nowrap'),
  'PC table nowrap helper prevents desktop body-cell wrapping',
)
assert(
  stylesheetSource.includes('.pc-teaching-events-table th,') &&
    stylesheetSource.includes('.pc-teaching-events-table td'),
  'PC table uses compact table padding without changing global table density',
)
assert(
  pcSessionCellRule.includes('min-width: 300px'),
  'PC Session Type column is wide enough for normal session type labels',
)
assert(
  pcSessionPillRule.includes('max-width: none'),
  'PC Session Type pill is not capped to the old compact width',
)
assert(
  !pcSessionPillRule.includes('overflow: hidden') && !pcSessionPillRule.includes('text-overflow: ellipsis'),
  'PC Session Type pill is not aggressively truncated',
)
