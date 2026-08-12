import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const apiSource = readFileSync(
  fileURLToPath(new URL('../../api/secretaryEvents.ts', import.meta.url)),
  'utf8',
)
const pageSource = readFileSync(
  fileURLToPath(new URL('./SecretaryTeachingSchedulePage.tsx', import.meta.url)),
  'utf8',
)

assert(
  apiSource.includes('teaching_name_id: payload.teachingNameId'),
  'Secretary event API sends explicit Teaching Name IDs',
)
assert(
  apiSource.includes('global_session_type_id: payload.globalSessionTypeId'),
  'Secretary event API sends explicit global-session IDs',
)
assert(
  !apiSource.includes('teaching_name: payload.'),
  'Secretary event API never posts display text as an event source',
)
assert(
  pageSource.includes('value={formState.sourceKey}'),
  'Secretary form selects an immutable source key rather than display text',
)
assert(
  apiSource.includes('durationIsMapped')
    && pageSource.includes('temporary one-hour duration')
    && pageSource.includes('automatically update its duration and end time'),
  'Secretary form hides unmapped timing fields behind the automatic-update notice',
)
assert(
  pageSource.includes('selectedSourceOption.durationIsMapped')
    && pageSource.includes('(TTF mapping)'),
  'Secretary form displays mapped posting-specific duration and end time',
)
assert(
  apiSource.includes('rYearDurations')
    && pageSource.includes('Duration varies by R-year')
    && pageSource.includes('End time by R-year')
    && pageSource.includes('Staff scheduling uses the longest duration'),
  'Secretary form displays R-year timings and the longest staff envelope',
)
assert(
  pageSource.includes('sourceKeyForSecretaryTeachingEvent'),
  'Secretary edits and duplicates preserve the existing event source identity',
)
assert(
  pageSource.includes('const retainedInactiveGlobalOption')
    && pageSource.includes("drawerMode !== 'edit'")
    && pageSource.includes('sourceEvent?.globalSessionTypeId'),
  'Secretary edit mode retains only the current inactive global source',
)
assert(
  pageSource.includes('drawerSourceOptions.map')
    && pageSource.includes('current inactive global source')
    && pageSource.includes('canSubmitTeaching'),
  'Secretary retained inactive global source is selectable and saveable only in edit mode',
)
assert(
  !pageSource.includes('teachingTypeByName.get(event.teachingName)'),
  'Secretary event rendering does not classify session types from display text',
)
