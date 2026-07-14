import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const source = readFileSync(
  fileURLToPath(new URL('./AdminParsedDataPage.tsx', import.meta.url)),
  'utf8',
)

assert(
  source.includes("{ value: '', label: 'Blank (Inactive)' }"),
  'FormF1 correction UI exposes the blank inactive status',
)
assert(
  source.includes("value === 'Inactive' || value === ''"),
  'FormF1 correction UI derives blank status as inactive',
)
assert(
  source.includes("min={field.key === 'monthly_target' ? '0' : undefined}"),
  'teaching target correction input permits zero',
)
assert(
  source.includes("field.key === 'monthly_target' ? '1' : undefined"),
  'teaching target correction input uses whole-number steps',
)
