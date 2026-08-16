import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const source = readFileSync(
  fileURLToPath(new URL('./uploads.ts', import.meta.url)),
  'utf8',
)

assert.match(
  source,
  /export const WORKBOOK_UPLOAD_TIMEOUT_MS = 5 \* 60 \* 1000/,
  'workbook uploads allow five minutes for synchronous parsing and replacement',
)
assert.match(
  source,
  /timeout: WORKBOOK_UPLOAD_TIMEOUT_MS/,
  'every workbook upload overrides the shared one-minute API timeout',
)
