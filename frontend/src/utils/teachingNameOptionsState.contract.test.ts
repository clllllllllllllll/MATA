import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  canAddTeachingFromOptions,
  resolveTeachingNameOptionsState,
} from './teachingNameOptionsState.ts'

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const state = (
  overrides: Partial<Parameters<typeof resolveTeachingNameOptionsState>[0]> = {},
) => resolveTeachingNameOptionsState({
  hasContext: true,
  isLoading: false,
  isLoaded: true,
  error: null,
  optionCount: 1,
  ...overrides,
})

assert(state({ hasContext: false }) === 'unavailable', 'missing period context is unavailable, not empty')
assert(state({ isLoading: true, isLoaded: false }) === 'loading', 'in-flight options remain loading')
assert(state({ isLoaded: false, optionCount: 0 }) === 'loading', 'unresolved options are not reported as empty')
assert(state({ error: 'Network failure', optionCount: 0 }) === 'error', 'failed options retain a distinct error state')
assert(state({ optionCount: 0 }) === 'empty', 'successful zero-option response is an empty state')
assert(state({ optionCount: 2 }) === 'ready', 'successful non-empty response is ready')
assert(canAddTeachingFromOptions('ready'), 'Add Teaching enables after a non-empty options response')
assert(!canAddTeachingFromOptions('loading'), 'Add Teaching stays disabled while options load')
assert(!canAddTeachingFromOptions('empty'), 'Add Teaching stays disabled for a successful empty response')
assert(!canAddTeachingFromOptions('error'), 'Add Teaching stays disabled after an options error')
assert(!canAddTeachingFromOptions('unavailable'), 'Add Teaching stays disabled without period context')

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const pcPage = read('../pages/pc/PcTeachingEventsPage.tsx')
const secretaryPage = read('../pages/secretary/SecretaryTeachingSchedulePage.tsx')
const pcApi = read('../api/programmeTeachingEvents.ts')
const secretaryApi = read('../api/secretaryEvents.ts')

assert(
  pcPage.includes('disabled={programmeScope.mode === \'none\' || !canAddTeaching}'),
  'PC Add Teaching uses resolved option readiness',
)
assert(
  secretaryPage.includes('disabled={!canAddTeaching}'),
  'Secretary Add Teaching uses resolved option readiness',
)
assert(
  pcPage.includes("nameOptionsState === 'loading'")
    && pcPage.includes("nameOptionsState === 'unavailable'")
    && pcPage.includes("nameOptionsState === 'error'")
    && pcPage.includes("nameOptionsState === 'empty'"),
  'PC page keeps loading, unavailable, error, and empty states distinct',
)
assert(
  secretaryPage.includes("nameOptionsState === 'ready'")
    && secretaryPage.includes("nameOptionsState === 'empty'"),
  'Secretary page renders catalogue options only after a ready response',
)
assert(
  !secretaryPage.includes('You can type a teaching name manually')
    && !secretaryPage.includes('Use manual name entry'),
  'Secretary workflow has no arbitrary free-text teaching-name fallback',
)
assert(
  pcApi.includes('(response.data as { options?: unknown })?.options')
    && secretaryApi.includes('(response.data as { options?: unknown })?.options'),
  'Both frontends parse the backend options envelope',
)
