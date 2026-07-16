import type { StoredAuthSession } from '../../types/auth.ts'
import {
  createResidentLoginPayload,
  type ResidentLoginPayload,
  type ResidentLoginRole,
} from '../../api/loginPayloads.ts'
import { defaultPathForGuardRole } from '../../routeGuards.ts'

export interface ResidentLoginState {
  role: ResidentLoginRole
}

export const createInitialResidentLoginState = (): ResidentLoginState => ({
  role: 'resident',
})

export const selectResidentLoginRole = (role: ResidentLoginRole): ResidentLoginState => ({
  role,
})

export const resolveResidentLoginRedirect = (role: ResidentLoginRole): string =>
  defaultPathForGuardRole(role)

interface SubmitSelectedResidentLoginOptions {
  rawMcr: string
  role: ResidentLoginRole
  authenticate: (payload: ResidentLoginPayload) => Promise<StoredAuthSession>
}

export interface ResidentLoginResult {
  session: StoredAuthSession
  redirectPath: string
}

export const submitSelectedResidentLogin = async ({
  rawMcr,
  role,
  authenticate,
}: SubmitSelectedResidentLoginOptions): Promise<ResidentLoginResult> => {
  const payload = createResidentLoginPayload(rawMcr, role)
  const session = await authenticate(payload)

  if (session.identity.role !== payload.role) {
    throw new Error('Resident login response did not match the selected identity path.')
  }

  return {
    session,
    redirectPath: resolveResidentLoginRedirect(payload.role),
  }
}
