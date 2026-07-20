import type {
  AdminSecretaryEventSourceType,
  ForceDeleteAdminSecretaryEventResponse,
} from '../../api/adminSecretaryEvents'

export const adminTeachingEventSourceLabel = (
  sourceType: AdminSecretaryEventSourceType,
): string => sourceType === 'programme_pc' ? 'Programme PC' : 'Secretary'

export const isAdminEventForceDeleteConfirmationValid = (
  reason: string,
  confirmation: string,
): boolean => reason.trim().length > 0 && confirmation === 'DELETE'

export const canCloseAdminEventDetail = (deletePending: boolean): boolean => !deletePending

export const adminEventListOffsetAfterDeletion = (
  offset: number,
  visibleRowCount: number,
  pageSize: number,
): number => visibleRowCount <= 1 && offset > 0
  ? Math.max(0, offset - pageSize)
  : offset

export const adminEventForceDeleteSuccessMessage = (
  result: ForceDeleteAdminSecretaryEventResponse,
): string => {
  const submissionLabel = result.totalAttendanceDeleted === 1 ? 'submission' : 'submissions'
  return `Deleted event and ${result.totalAttendanceDeleted} attendance ${submissionLabel} (${result.nativeAttendanceDeleted} NHG Resident, ${result.externalAttendanceDeleted} Non-NHG Resident).`
}
