import type { StoredAuthSession } from '../../types/auth.ts'
import {
  createResidentLoginPayload,
  type ResidentLoginPayload,
} from '../../api/loginPayloads.ts'
import { defaultPathForGuardRole } from '../../routeGuards.ts'

type AuthenticatedResidentRole = 'resident' | 'external_resident'

const isAuthenticatedResidentRole = (role: string): role is AuthenticatedResidentRole =>
  role === 'resident' || role === 'external_resident'

export const resolveResidentLoginRedirect = (role: AuthenticatedResidentRole): string =>
  defaultPathForGuardRole(role)

interface SubmitResidentLoginOptions {
  rawMcr: string
  authenticate: (payload: ResidentLoginPayload) => Promise<StoredAuthSession>
}

export interface ResidentLoginResult {
  session: StoredAuthSession
  redirectPath: string
}

export const submitSharedResidentLogin = async ({
  rawMcr,
  authenticate,
}: SubmitResidentLoginOptions): Promise<ResidentLoginResult> => {
  const payload = createResidentLoginPayload(rawMcr)
  const session = await authenticate(payload)
  const authenticatedRole = session.identity.role

  if (!isAuthenticatedResidentRole(authenticatedRole)) {
    throw new Error('Resident login response returned an invalid role.')
  }

  return {
    session,
    redirectPath: resolveResidentLoginRedirect(authenticatedRole),
  }
}
