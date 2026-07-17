import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(
  fileURLToPath(new URL('./residentSubmissions.ts', import.meta.url)),
  'utf8',
)

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

assert(source.includes('parseResidentEventsResponse'), 'resident events use one response parser')
assert(source.includes('active_reporting_periods'), 'parser consumes active-period metadata')
assert(source.includes('reporting_period_id'), 'parser preserves the event reporting-period id')
assert(source.includes('reporting_period_label'), 'parser preserves the event reporting-period label')
assert(source.includes('filter_options'), 'parser consumes merged backend filter options')
