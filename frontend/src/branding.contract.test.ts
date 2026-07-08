/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const BRAND_EXPANSION = 'Monitoring and Analysing of Teaching Attendances'
const LEGACY_EXPANSION = ['Medical Attendance', 'Tracking'].join(' ')

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const indexHtml = read('../index.html')
const loginPageSource = read('./pages/auth/LoginPage.tsx')
const registrationPageSource = read('./pages/auth/NonNhgRegistrationPage.tsx')

assert(indexHtml.includes('<title>MATA</title>'), 'browser tab title uses MATA')
assert(indexHtml.includes('href="/favicon.png"'), 'browser favicon references approved PNG asset')
assert(indexHtml.includes('type="image/png"'), 'browser favicon declares PNG type')

for (const [label, source] of [
  ['login page', loginPageSource],
  ['Non-NHG registration page', registrationPageSource],
] as const) {
  assert(source.includes('<strong>MATA</strong>'), `${label} keeps MATA as the app title`)
  assert(source.includes(BRAND_EXPANSION), `${label} uses the approved MATA expansion`)
  assert(!source.includes(LEGACY_EXPANSION), `${label} does not use the old MATA expansion`)
}
