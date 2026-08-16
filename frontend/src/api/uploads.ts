import type { UploadType } from '../types/app'
import { httpClient, toApiRequestError } from './http'
import { buildAdminDemoHeaders, type AdminDemoLevel } from './authHeaders'

export interface UploadRequest {
  uploadType: UploadType
  file: File
  reportingPeriodId?: string
  programmeCode?: string
  adminProgrammes: string[]
  adminId: string
  adminLevel?: AdminDemoLevel
  actorName?: string
}

const uploadPathByType: Record<UploadType, string> = {
  public_holidays: '/admin/upload/public-holidays',
  rdb: '/admin/upload/rdb',
  ttf: '/admin/upload/ttf',
  form_f1: '/admin/upload/form-f1',
}

// Full-snapshot workbook parsing can legitimately outlast the shared API
// client's one-minute timeout, especially for an RDB replacement.
export const WORKBOOK_UPLOAD_TIMEOUT_MS = 5 * 60 * 1000

export const uploadWorkbook = async (
  payload: UploadRequest,
): Promise<Record<string, unknown>> => {
  const reportingPeriodId = payload.reportingPeriodId?.trim()
  const programmeCode = payload.programmeCode?.trim()

  const formData = new FormData()
  formData.append('file', payload.file)

  if (payload.uploadType === 'rdb' || payload.uploadType === 'ttf' || payload.uploadType === 'form_f1') {
    formData.append('reporting_period_id', reportingPeriodId ?? '')
  }
  if (payload.uploadType === 'ttf') {
    formData.append('programme_code', programmeCode ?? '')
  }

  try {
    const response = await httpClient.post(uploadPathByType[payload.uploadType], formData, {
      headers: buildAdminDemoHeaders(
        payload.adminId,
        payload.adminProgrammes,
        payload.adminLevel,
        payload.actorName,
      ),
      skipMemoryCacheClear: true,
      timeout: WORKBOOK_UPLOAD_TIMEOUT_MS,
    })

    if (typeof response.data === 'object' && response.data !== null) {
      return response.data as Record<string, unknown>
    }
    return { result: response.data }
  } catch (error) {
    throw toApiRequestError(error)
  }
}
