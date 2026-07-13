/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
  formatProgrammePcConfigEmptyState,
  formatProgrammePcConfigSubtitle,
  formatProgrammePcSidebarTitle,
} from './utils/programmePcLabels.ts'

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

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

assertEqual(formatProgrammePcSidebarTitle(['GERI']), 'GERI PC', 'GERI PC sidebar title uses code-first wording')
assertEqual(formatProgrammePcConfigSubtitle(['GERI']), 'PC - GERI', 'GERI PC config subtitle uses single scope')

assertEqual(formatProgrammePcSidebarTitle(['DR']), 'DR PC', 'DR PC sidebar title uses code-first wording')
assertEqual(formatProgrammePcConfigSubtitle(['DR']), 'PC - DR', 'DR PC config subtitle uses single scope')

const drMainPostingEmptyState = formatProgrammePcConfigEmptyState(['DR'], 'main')
assertEqual(
  drMainPostingEmptyState.title,
  'No main posting rules for your programme',
  'DR PC empty-state title uses singular programme wording',
)
assertEqual(
  drMainPostingEmptyState.body,
  'Rules for DR will appear here once created.',
  'DR PC empty-state copy names only the authenticated scope',
)

const geriMainPostingEmptyState = formatProgrammePcConfigEmptyState(['GERI'], 'main')
assertEqual(
  geriMainPostingEmptyState.body,
  'Rules for GERI will appear here once created.',
  'GERI PC empty-state copy names only the authenticated scope',
)

const missingScopeEmptyState = formatProgrammePcConfigEmptyState([], 'main')
assertEqual(
  missingScopeEmptyState.body,
  'Rules for your programme will appear here once created.',
  'missing PC scope uses the safe generic empty-state copy',
)

const unexpectedMultiScopeTitle = formatProgrammePcSidebarTitle(['DR', 'GERI'])
const unexpectedMultiScopeSubtitle = formatProgrammePcConfigSubtitle(['DR', 'GERI'])
assertEqual(unexpectedMultiScopeTitle, 'DR PC', 'unexpected multi-scope PC sidebar title chooses one effective scope')
assertEqual(unexpectedMultiScopeSubtitle, 'PC - DR', 'unexpected multi-scope PC config subtitle chooses one effective scope')
assert(!unexpectedMultiScopeTitle.includes(','), 'unexpected multi-scope PC sidebar title is not comma-separated')
assert(!unexpectedMultiScopeSubtitle.includes(','), 'unexpected multi-scope PC config subtitle is not comma-separated')

const unexpectedMultiScopeEmptyState = formatProgrammePcConfigEmptyState(['DR', 'GERI'], 'main')
assertEqual(
  unexpectedMultiScopeEmptyState.body,
  'Rules for DR will appear here once created.',
  'unexpected multi-scope PC empty-state copy chooses one effective scope',
)
for (const text of [
  drMainPostingEmptyState.title,
  drMainPostingEmptyState.body,
  geriMainPostingEmptyState.title,
  geriMainPostingEmptyState.body,
  missingScopeEmptyState.title,
  missingScopeEmptyState.body,
  unexpectedMultiScopeEmptyState.title,
  unexpectedMultiScopeEmptyState.body,
]) {
  assert(!text.includes('DR and GERI'), 'PC empty-state copy never includes multiple programme names')
  assert(!text.toLowerCase().includes('all programmes'), 'PC empty-state copy never claims all-programme scope')
}

const shellSource = read('./components/AppShell.tsx')
const adminConfigPageSource = read('./pages/admin/AdminConfigPage.tsx')
const adminMultiPostingPageSource = read('./pages/admin/AdminMultiPostingPage.tsx')
const navigationSource = read('./config/navigation.ts')

assert(
  shellSource.includes('formatProgrammePcSidebarTitle(identity.programmeScope)'),
  'AppShell sidebar title uses authenticated PC programme scope helper',
)
assert(
  !shellSource.includes('identity.programmeScope.join'),
  'AppShell does not join Programme PC scopes for user-facing labels',
)
assert(
  adminConfigPageSource.includes('formatProgrammePcConfigSubtitle(identity.programmeScope)'),
  'PC Configuration subtitle uses authenticated PC programme scope helper',
)
assert(
  !adminConfigPageSource.includes("`PC - ${demoAdminProgrammes.join(', ')}`"),
  'PC Configuration subtitle does not use demo/global programme scope list',
)
assert(
  adminMultiPostingPageSource.includes('formatProgrammePcConfigEmptyState(programmeScope, emptyStateRuleLabel[activeTab])'),
  'PC Configuration empty-state copy uses the shared authenticated scope helper',
)
assert(
  adminMultiPostingPageSource.includes("identity?.role === 'programme_pc' ? identity.programmeScope : []"),
  'PC Configuration empty-state copy reads authenticated PC programme scope',
)
assert(
  !adminMultiPostingPageSource.includes('<ProgrammeScopeText'),
  'PC Configuration empty-state copy does not join programme scope labels',
)
assert(navigationSource.includes("label: 'Master Admin'"), 'Master Admin role label remains unchanged')
assert(navigationSource.includes("label: 'Secretary'"), 'Secretary role label remains unchanged')
assert(navigationSource.includes("label: 'NHG Resident'"), 'Resident role label remains unchanged')
