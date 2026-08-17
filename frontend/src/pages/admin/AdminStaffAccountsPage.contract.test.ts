import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const pageSource = readFileSync(
  fileURLToPath(new URL('./AdminStaffAccountsPage.tsx', import.meta.url)),
  'utf8',
)

const refreshSource = pageSource.slice(
  pageSource.indexOf('const refresh = useCallback'),
  pageSource.indexOf('const loadFormOptions = useCallback'),
)
const formOptionsSource = pageSource.slice(
  pageSource.indexOf('const loadFormOptions = useCallback'),
  pageSource.indexOf('useEffect(() =>'),
)

if (!refreshSource.includes('await listStaffAccounts(requestContext)')) {
  throw new Error('staff-account table loads its rows directly')
}
if (refreshSource.includes('listProgrammes') || refreshSource.includes('listPostingCodes')) {
  throw new Error('staff-account table does not wait for form-only reference data')
}
if (!formOptionsSource.includes('listProgrammes') || !formOptionsSource.includes('listPostingCodes')) {
  throw new Error('staff-account form still loads programme and posting options')
}
if (!pageSource.includes('void loadFormOptions()')) {
  throw new Error('opening a staff-account drawer loads its form options')
}
