/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const pageSource = read('./AdminWarningsPage.tsx')
const stylesSource = read('../../index.css').replace(/\r\n/g, '\n')

assert(
  pageSource.includes('className="warning-type-cell-content"'),
  'persisted warning type cell uses an inner wrapper for inline badge alignment',
)

assert(
  !/\.grouped-warnings-table\s+\.cell-type\s*\{[^}]*display:\s*flex/s.test(stylesSource),
  'persisted warning type table cell remains a table cell, not a flex container',
)

assert(
  /\.grouped-warnings-table\s+\.warning-type-cell-content\s*\{[^}]*display:\s*inline-flex[^}]*align-items:\s*center[^}]*gap:\s*10px/s.test(stylesSource),
  'persisted warning type badge wrapper handles inline alignment inside the table cell',
)
