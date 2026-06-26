import type { Programme } from '../../api/programmes'
import { buildMasterAdminTtfProgrammeOptions } from './adminUploadPageLogic.ts'

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const programmes = [
  {
    id: '1',
    code: 'DR',
    name: 'Diagnostic Radiology',
    ayDateCategory: 'non_im_subspec',
    rYearRequired: true,
    isSubspecialty: false,
  },
  {
    id: '2',
    code: 'GRM',
    name: 'Geriatric Medicine',
    ayDateCategory: 'non_im_subspec',
    rYearRequired: true,
    isSubspecialty: false,
  },
  {
    id: '3',
    code: 'ORTHO',
    name: 'Orthopaedic Surgery',
    ayDateCategory: 'non_im_subspec',
    rYearRequired: true,
    isSubspecialty: false,
  },
] satisfies Programme[]

const masterOptions = buildMasterAdminTtfProgrammeOptions(programmes, ['DR'])
assertEqual(masterOptions.length, 3, 'master admin TTF selector uses canonical programme list')
assertEqual(masterOptions[2]?.code, 'ORTHO', 'master admin TTF selector includes programmes outside demo scope')
assertEqual(
  masterOptions[0]?.label,
  'DR - Diagnostic Radiology',
  'master admin TTF selector labels include programme names when available',
)

const fallbackOptions = buildMasterAdminTtfProgrammeOptions([], ['DR', 'DR', ' GERI '])
assertEqual(fallbackOptions.length, 2, 'fallback selector options are deduped')
assertEqual(fallbackOptions[1]?.code, 'GERI', 'fallback selector trims configured scope values')
