/// <reference types="node" />

import assert from 'node:assert/strict'
import test from 'node:test'
import { parseNonNhgRegistrationOptions } from './nonNhgRegistrationOptions.ts'

const programmeRows = Array.from({ length: 28 }, (_, index) => ({
  programme_code: ` P${String(index + 1).padStart(2, '0')} `,
  programme_name: ` Programme ${index + 1} `,
  institutions: [
    {
      institution_code: index === 27 ? ' FUTURE-HOSPITAL ' : ' NHG ',
      available: index % 2 === 0,
      status: 'active',
    },
    {
      institution_code: ' PENDING-HOSPITAL ',
      available: false,
      status: 'pending',
    },
  ],
}))

test('registration options preserve all programmes and normalize future institutions', () => {
  const parsed = parseNonNhgRegistrationOptions({
    institutions: [
      { code: ' NHG ', name: ' National Healthcare Group ' },
      { code: ' FUTURE-HOSPITAL ', name: ' Future Hospital ' },
    ],
    programmes: programmeRows,
  })

  assert.equal(parsed.programmes.length, 28)
  assert.equal(parsed.programmes[0]?.programmeCode, 'P01')
  assert.equal(parsed.programmes[27]?.programmeCode, 'P28')
  assert.equal(
    parsed.programmes[27]?.institutions[0]?.institutionCode,
    'FUTURE-HOSPITAL',
  )
  assert.deepEqual(parsed.programmes[0]?.institutions[1], {
    institutionCode: 'PENDING-HOSPITAL',
    available: false,
    status: 'pending',
  })
})

test('pending mappings cannot be advertised as available', () => {
  assert.throws(() =>
    parseNonNhgRegistrationOptions({
      institutions: [{ code: 'NHG', name: 'NHG' }],
      programmes: [
        {
          programme_code: 'DR',
          programme_name: 'Diagnostic Radiology',
          institutions: [
            {
              institution_code: 'NHG',
              available: true,
              status: 'pending',
            },
          ],
        },
      ],
    }),
  )
})

test('malformed registration option arrays and rows fail closed', () => {
  for (const malformed of [
    null,
    {},
    { institutions: {}, programmes: [] },
    { institutions: [], programmes: {} },
    { institutions: [{}], programmes: [] },
    {
      institutions: [{ code: 'NHG', name: 'NHG' }],
      programmes: [{ programme_code: '', programme_name: 'Missing code', institutions: [] }],
    },
    {
      institutions: [{ code: 'NHG', name: 'NHG' }],
      programmes: [
        {
          programme_code: 'DR',
          programme_name: 'Diagnostic Radiology',
          institutions: [{ institution_code: 'NHG', available: 'yes', status: 'active' }],
        },
      ],
    },
  ]) {
    assert.throws(() => parseNonNhgRegistrationOptions(malformed))
  }
})
