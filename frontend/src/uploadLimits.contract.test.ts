/// <reference types="node" />

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  MAX_REQUEST_BODY_SIZE_MIB,
  MAX_UPLOAD_FILE_SIZE_BYTES,
  MAX_UPLOAD_FILE_SIZE_MIB,
  MAX_UPLOAD_REQUEST_SIZE_MIB,
  UPLOAD_FILE_SIZE_ERROR_MESSAGE,
  UPLOAD_FILE_SIZE_HELP_TEXT,
  UPLOAD_REQUEST_SIZE_ERROR_MESSAGE,
  validateUploadFile,
} from './config/uploadLimits.ts'

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

const readPythonIntegerDefault = (source: string, settingName: string): number => {
  const match = source.match(
    new RegExp(`^\\s*${settingName}: int = (\\d+)\\s*$`, 'm'),
  )
  assert.ok(match, `Backend setting ${settingName} must have an integer default`)
  return Number(match[1])
}

const readEnvironmentInteger = (source: string, settingName: string): number => {
  const match = source.match(new RegExp(`^${settingName}=(\\d+)\\s*$`, 'm'))
  assert.ok(match, `Environment example must define ${settingName}`)
  return Number(match[1])
}

test('frontend upload limits use the approved 3 MiB file and 4 MiB request contract', () => {
  assert.equal(MAX_UPLOAD_FILE_SIZE_MIB, 3)
  assert.equal(MAX_UPLOAD_REQUEST_SIZE_MIB, 4)
  assert.equal(MAX_REQUEST_BODY_SIZE_MIB, 4)
  assert.ok(MAX_UPLOAD_FILE_SIZE_MIB < MAX_UPLOAD_REQUEST_SIZE_MIB)
  assert.ok(MAX_UPLOAD_REQUEST_SIZE_MIB <= MAX_REQUEST_BODY_SIZE_MIB)
  assert.equal(UPLOAD_FILE_SIZE_HELP_TEXT, 'Maximum file size: 3 MiB.')
  assert.equal(
    UPLOAD_REQUEST_SIZE_ERROR_MESSAGE,
    'Upload request is too large. The complete request is limited to 4 MiB, including a file no larger than 3 MiB.',
  )
})

test('frontend file validation accepts the exact boundary and rejects boundary plus one', () => {
  assert.equal(
    validateUploadFile(
      { name: 'workbook.XLSX', size: MAX_UPLOAD_FILE_SIZE_BYTES },
      '.xlsx,.csv',
    ),
    null,
  )
  assert.equal(
    validateUploadFile(
      { name: 'workbook.xlsx', size: MAX_UPLOAD_FILE_SIZE_BYTES + 1 },
      '.xlsx,.csv',
    ),
    UPLOAD_FILE_SIZE_ERROR_MESSAGE,
  )
  assert.equal(
    validateUploadFile(
      { name: 'workbook.txt', size: 1 },
      '.xlsx,.csv',
    ),
    'Invalid file type. Allowed: .xlsx, .csv',
  )
})

test('the shared upload card applies and displays the file-size contract', () => {
  const uploadCard = read('./components/UploadCard.tsx')

  assert.match(uploadCard, /validateUploadFile\(selected, accept\)/)
  assert.match(uploadCard, /\{UPLOAD_FILE_SIZE_HELP_TEXT\}/)
})

test('frontend limits agree with backend defaults and the environment example', () => {
  const backendConfig = read('../../backend/app/config.py')
  const environmentExample = read('../../.env.example')

  assert.equal(
    readPythonIntegerDefault(backendConfig, 'max_upload_size_mb'),
    MAX_UPLOAD_FILE_SIZE_MIB,
  )
  assert.equal(
    readPythonIntegerDefault(backendConfig, 'max_upload_request_size_mb'),
    MAX_UPLOAD_REQUEST_SIZE_MIB,
  )
  assert.equal(
    readPythonIntegerDefault(backendConfig, 'max_request_body_size_mb'),
    MAX_REQUEST_BODY_SIZE_MIB,
  )
  assert.equal(
    readEnvironmentInteger(environmentExample, 'MAX_UPLOAD_SIZE_MB'),
    MAX_UPLOAD_FILE_SIZE_MIB,
  )
  assert.equal(
    readEnvironmentInteger(environmentExample, 'MAX_UPLOAD_REQUEST_SIZE_MB'),
    MAX_UPLOAD_REQUEST_SIZE_MIB,
  )
  assert.equal(
    readEnvironmentInteger(environmentExample, 'MAX_REQUEST_BODY_SIZE_MB'),
    MAX_REQUEST_BODY_SIZE_MIB,
  )
})

test('active upload documentation agrees with the approved limits', () => {
  const documentedContracts = [
    read('../../README.md'),
    read('../../docs/api.md'),
    read('../../docs/parsing.md'),
    read('../../docs/00_project_context.md'),
    read('../../docs/5b_h_d_production_security_implementation.md'),
    read('../../docs/5b_h_uat_security_audit.md'),
    read('../../docs/5b_h_m05_upload_preparser_limits.md'),
  ]

  for (const document of documentedContracts) {
    assert.match(document, /3 MiB/)
    assert.match(document, /4 MiB/)
  }

  const activeStaleClaims = [
    /Defaults are 12 MiB/,
    /12 MiB global body/,
    /11 MiB aggregate upload-request cap/,
    /Files remain capped at 10 MiB/,
    /10 MiB per-file cap/,
    /client_max_body_size 12m/,
    /client_max_body_size 11m/,
  ]
  const combinedDocumentation = documentedContracts.join('\n')
  for (const staleClaim of activeStaleClaims) {
    assert.doesNotMatch(combinedDocumentation, staleClaim)
  }
})
