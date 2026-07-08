/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import {
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

const unexpectedMultiScopeTitle = formatProgrammePcSidebarTitle(['DR', 'GERI'])
const unexpectedMultiScopeSubtitle = formatProgrammePcConfigSubtitle(['DR', 'GERI'])
assertEqual(unexpectedMultiScopeTitle, 'DR PC', 'unexpected multi-scope PC sidebar title chooses one effective scope')
assertEqual(unexpectedMultiScopeSubtitle, 'PC - DR', 'unexpected multi-scope PC config subtitle chooses one effective scope')
assert(!unexpectedMultiScopeTitle.includes(','), 'unexpected multi-scope PC sidebar title is not comma-separated')
assert(!unexpectedMultiScopeSubtitle.includes(','), 'unexpected multi-scope PC config subtitle is not comma-separated')

const shellSource = read('./components/AppShell.tsx')
const adminConfigPageSource = read('./pages/admin/AdminConfigPage.tsx')
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
assert(navigationSource.includes("label: 'Master Admin'"), 'Master Admin role label remains unchanged')
assert(navigationSource.includes("label: 'Secretary'"), 'Secretary role label remains unchanged')
assert(navigationSource.includes("label: 'NHG Resident'"), 'Resident role label remains unchanged')
