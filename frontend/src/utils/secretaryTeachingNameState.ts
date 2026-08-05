import { ApiRequestError } from '../api/http'
import { formatUserFacingApiError } from './userFacingErrors'
import {
  resolveTeachingNameLifecycleConflict,
  type TeachingNameLifecycleError,
} from './secretaryTeachingNameLifecycle'

export type { TeachingNameLifecycleError } from './secretaryTeachingNameLifecycle'

export const resolveTeachingNameLifecycleError = (
  error: unknown,
  fallback: string,
): TeachingNameLifecycleError => {
  if (!(error instanceof ApiRequestError)) {
    return { message: fallback, needsRefresh: false }
  }
  const controlledConflict = resolveTeachingNameLifecycleConflict(error)
  if (controlledConflict) {
    return controlledConflict
  }
  return {
    message: formatUserFacingApiError(error, { fallbackMessage: fallback }),
    needsRefresh: error.status === 409,
  }
}
