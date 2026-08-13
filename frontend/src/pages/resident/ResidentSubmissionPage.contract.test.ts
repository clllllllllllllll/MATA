import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

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

const pageSource = readFileSync(
  fileURLToPath(new URL('./ResidentSubmissionPage.tsx', import.meta.url)),
  'utf8',
)
const apiSource = readFileSync(
  fileURLToPath(new URL('../../api/residentSubmissions.ts', import.meta.url)),
  'utf8',
)

assert(pageSource.includes('During LOA'), 'recent submissions display the durable LOA classification')
const appSource = readFileSync(fileURLToPath(new URL('../../App.tsx', import.meta.url)), 'utf8')
const navigationSource = readFileSync(
  fileURLToPath(new URL('../../config/navigation.ts', import.meta.url)),
  'utf8',
)
const stylesheetSource = readFileSync(fileURLToPath(new URL('../../index.css', import.meta.url)), 'utf8')
const adhocSectionSource = pageSource.slice(pageSource.indexOf('Ad-hoc Teaching Submission'))
const adhocSubmitSource = apiSource.slice(
  apiSource.indexOf('export const submitResidentAdhocTeaching'),
  apiSource.indexOf('export const listResidentAttendance'),
)

assert(
  pageSource.includes('Please ensure your current submission is not an already scheduled event. There are no CME Pts tagged to adhoc teachings.'),
  'ad-hoc helper copy appears exactly',
)
assertOrdered(
  adhocSectionSource,
  ['Teaching date', 'Derived posting', 'Fixed teaching type', 'Start time', 'Details of session'],
  'ad-hoc flow is date-first with only server-derived attribution',
)
assert(pageSource.includes('loadAdhocOptions'), 'ad-hoc options load after date selection')
assert(pageSource.includes('readOnly'), 'derived posting display is read-only')
assert(
  pageSource.includes('value="Department/Programme Teaching [1h]"'),
  'ad-hoc teaching type is fixed by the server contract',
)
assert(!pageSource.includes('selectedAttendedPostingCode'), 'ad-hoc flow does not choose an attended posting')
assert(!pageSource.includes('attendedPostingOptions'), 'ad-hoc flow does not render attended posting options')
assert(!pageSource.includes('adhocOptions.options.map'), 'ad-hoc flow does not select a teaching type from client options')
assert(!pageSource.includes('placeholder="e.g. Journal Club"'), 'ad-hoc teaching no longer uses free text teaching input')
assert(pageSource.includes('detailsOfSession'), 'details_of_session is represented as optional free text state')
assert(apiSource.includes('/resident/adhoc-teaching-options'), 'API loads canonical ad-hoc options endpoint')
assert(apiSource.includes('/resident/adhoc-teaching/options'), 'API retains compatibility alias path constant or fallback')
assert(adhocSubmitSource.includes('teaching_date'), 'ad-hoc submit payload is date-first')
assert(adhocSubmitSource.includes('details_of_session'), 'ad-hoc submit payload includes optional details_of_session')
assert(!adhocSubmitSource.includes('teaching_name'), 'ad-hoc API does not send display teaching text')
assert(!adhocSubmitSource.includes('attended_posting_code'), 'ad-hoc API does not send an attended posting choice')
assert(!adhocSubmitSource.includes('posting_code: payload.'), 'ad-hoc submit API does not send trusted posting_code')
assert(
  pageSource.includes("isExternalResident ? 'Non-NHG Resident' : 'NHG Resident'"),
  'scope chip uses role-specific NHG/Non-NHG labels',
)
assert(
  pageSource.includes("Submissions are recorded for home-cluster's records only"),
  'Non-NHG ad-hoc helper copy is forwarding-only and compliance-excluded',
)
assert(
  !pageSource.includes('<span>Counts as Department/Programme Teaching [1h] for NHG</span>'),
  'NHG compliance attribution summary is not rendered unconditionally for Non-NHG residents',
)

assert(!pageSource.includes('resident-filter-title'), 'scheduled filters subheading is removed')
assert(!pageSource.includes('Scheduled filters</div>'), 'scheduled filters heading text is not rendered')
assert(pageSource.includes('resident-events-header'), 'available events header owns scheduled filter actions')
assert(pageSource.indexOf('resident-events-header') < pageSource.indexOf('resident-filter-card'), 'scheduled filter actions are above filter controls')
assert(pageSource.includes('Start date'), 'scheduled filters include start date')
assert(pageSource.includes('End date'), 'scheduled filters include end date')
assert(pageSource.includes('Teaching/session name'), 'scheduled filters include teaching/session name')
assert(pageSource.includes('Posting'), 'scheduled filters include posting')
const scheduledEventsSource = pageSource.slice(
  pageSource.indexOf('Available Scheduled Events'),
  pageSource.indexOf('Ad-hoc Teaching Submission'),
)
assert(!scheduledEventsSource.includes('<th>Status</th>'), 'scheduled events table omits redundant status column')
assert(
  !scheduledEventsSource.includes("submitted ? 'Submitted' : 'Pending'"),
  'scheduled event cards omit redundant submitted/pending badge text',
)
assert(apiSource.includes('date_from'), 'scheduled events API sends date_from filter')
assert(apiSource.includes('date_to'), 'scheduled events API sends date_to filter')
assert(apiSource.includes('teaching_name'), 'scheduled events API sends teaching_name filter')
assert(apiSource.includes('posting_code'), 'scheduled events API sends posting_code filter')
assert(
  apiSource.includes('/resident/submission-periods'),
  'resident portal loads effectively active submission periods without a selector',
)
assert(
  pageSource.includes('getResidentPortalIdentitySubtitle(identity)'),
  'resident header renders the authenticated identity',
)
assert(!pageSource.includes('demoResidentMcr'), 'resident header does not render demo MCR configuration')
assert(!pageSource.includes('M00001A'), 'resident portal has no placeholder resident MCR')
assert(!pageSource.includes('Reporting period'), 'resident portal does not render a reporting-period selector')
assert(
  pageSource.includes('Loading active submission periods...'),
  'resident portal has a distinct period-loading state',
)
assert(
  pageSource.includes('Loading available scheduled events...'),
  'resident portal has a distinct event-loading state',
)
assert(
  pageSource.includes('No active submission period is currently available.'),
  'resident portal has a controlled no-active-period state',
)
assert(
  pageSource.includes('No scheduled teaching events are currently available for your postings.'),
  'resident portal distinguishes active periods with no eligible events',
)
assert(
  pageSource.includes("scheduledEventsState === 'ready'"),
  'eligible historical events render independently of current-posting sidebar text',
)
assert(
  !pageSource.includes('currentPosting'),
  'current-posting display state does not gate resident scheduled events',
)

assert(pageSource.includes('View all past submissions'), 'recent widget links to all past submissions')
assert(
  pageSource.includes("'/resident/attendance'") && pageSource.includes("'/external/attendance'"),
  'recent widget link targets the correct past submissions route for NHG and Non-NHG residents',
)
assert(pageSource.includes('resident-history-card-header'), 'recent submissions header has dedicated spacing class')
assert(
  stylesheetSource.includes(`.resident-history-card-header {
    flex-direction: column;
    align-items: stretch;
  }`) &&
    stylesheetSource.includes(`.resident-history-card-header .button {
    width: 100%;
    white-space: normal;
  }`),
  'recent submissions header stacks its action at narrow widths without page-level overflow',
)
assert(appSource.includes("path=\"/resident/attendance\""), '/resident/attendance route is registered')
assert(navigationSource.includes("label: 'Past Submissions'"), 'Past Submissions appears in resident navigation')
assert(pageSource.includes('handleDeleteAttendance'), 'recent widget supports delete submission action')
assert(pageSource.includes("row.status.toLowerCase() === 'submitted'"), 'delete action is conditional on submitted rows')
assertOrdered(
  pageSource.slice(pageSource.indexOf('const handleDeleteAttendance')),
  ['await removeResidentAttendance(row.attendanceId)', 'await loadResidentEvents()', 'await loadHistory()'],
  'delete flow refreshes available scheduled events and recent submissions',
)
assert(!pageSource.includes('formatAttendanceStatus(row.status)'), 'recent widget does not render visible status values')
assert(!pageSource.includes('resident-history-status'), 'recent widget omits status badge styling')
assert(pageSource.includes('resident-history-side'), 'recent delete action stays grouped in the side action area')
assert(pageSource.includes('button-danger resident-delete-button'), 'recent delete action uses danger styling')
assert(pageSource.includes('resident-adhoc-actions'), 'ad-hoc message and submit action use contained form-width wrapper')
assert(pageSource.includes("reason === 'public_holiday'"), 'PH blocked ad-hoc state disables submit through unavailable options')
assert(!pageSource.includes('Created By'), 'resident submission page does not show Created By')
assert(!pageSource.includes('Created by'), 'resident submission page does not show Created by')
assert(apiSource.includes('event_ids: eventIds'), 'scheduled event submission sends event ids only')
assertOrdered(
  pageSource.slice(pageSource.indexOf('const handleSubmitAttendance')),
  ['await loadResidentEvents()', 'await loadHistory()'],
  'scheduled attendance success refreshes available scheduled events and recent submissions',
)
