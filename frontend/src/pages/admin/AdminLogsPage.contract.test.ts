/// <reference types="node" />

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const assert = (condition: boolean, label: string) => {
  if (!condition) {
    throw new Error(label)
  }
}

const pageSource = readFileSync(
  fileURLToPath(new URL('./AdminLogsPage.tsx', import.meta.url)),
  'utf8',
)
const locationStateSource = pageSource.slice(
  pageSource.indexOf('const initialFiltersFromParams'),
  pageSource.indexOf('const DetailField'),
)

assert(
  !locationStateSource.includes("params.get('actor_user_id')") &&
    !locationStateSource.includes("params.get('entity_id')") &&
    !locationStateSource.includes("params.get('search')"),
  'personal or record identifiers are never restored from the Admin Logs URL',
)
assert(
  !locationStateSource.includes("['actor_user_id'") &&
    !locationStateSource.includes("['entity_id'") &&
    !locationStateSource.includes("['search'") &&
    !locationStateSource.includes('searchTerm'),
  'personal or record identifiers are never serialized into the Admin Logs URL',
)
assert(
  pageSource.includes("const [searchTerm, setSearchTerm] = useState('')") &&
    pageSource.includes("const [debouncedSearchTerm, setDebouncedSearchTerm] = useState('')"),
  'free-text search starts in component memory rather than browser location state',
)
assert(
  pageSource.includes('search: querySearch'),
  'removing location persistence does not remove the existing Admin Logs API filter',
)
