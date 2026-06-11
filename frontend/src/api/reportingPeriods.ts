import { httpClient, toApiRequestError } from './http'
import type { ReportingPeriodOption } from '../types/upload'
import { buildAdminDemoHeaders } from './authHeaders'

const toReportingPeriod = (value: Record<string, unknown>): ReportingPeriodOption => ({
  id: String(value.id ?? ''),
  label: String(value.label ?? ''),
  startDate: String(value.start_date ?? ''),
  endDate: String(value.end_date ?? ''),
  status: String(value.status ?? ''),
  createdAt: value.created_at ? String(value.created_at) : undefined,
  updatedAt: value.updated_at ? String(value.updated_at) : undefined,
})

interface ReportingPeriodRequestContext {
  adminId: string
  adminProgrammes: string[]
  actorName?: string
}

export interface ReportingPeriodMutationPayload {
  label?: string
  startDate?: string
  endDate?: string
  status?: 'open' | 'closed'
}

const toApiPayload = (payload: ReportingPeriodMutationPayload): Record<string, unknown> => {
  const body: Record<string, unknown> = {}
  if (payload.label !== undefined) {
    body.label = payload.label
  }
  if (payload.startDate !== undefined) {
    body.start_date = payload.startDate
  }
  if (payload.endDate !== undefined) {
    body.end_date = payload.endDate
  }
  if (payload.status !== undefined) {
    body.status = payload.status
  }
  return body
}

export const listReportingPeriods = async (
  params: ReportingPeriodRequestContext,
): Promise<ReportingPeriodOption[]> => {
  try {
    const response = await httpClient.get('/admin/reporting-periods', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes),
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toReportingPeriod)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createReportingPeriod = async (
  params: ReportingPeriodRequestContext & {
    payload: Required<Pick<ReportingPeriodMutationPayload, 'label' | 'startDate' | 'endDate'>>
  },
): Promise<ReportingPeriodOption> => {
  try {
    const response = await httpClient.post('/admin/reporting-periods', toApiPayload(params.payload), {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, undefined, params.actorName),
    })
    return toReportingPeriod(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updateReportingPeriod = async (
  params: ReportingPeriodRequestContext & {
    id: string
    payload: ReportingPeriodMutationPayload
  },
): Promise<ReportingPeriodOption> => {
  try {
    const response = await httpClient.put(
      `/admin/reporting-periods/${params.id}`,
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, undefined, params.actorName),
      },
    )
    return toReportingPeriod(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deleteReportingPeriod = async (
  params: ReportingPeriodRequestContext & { id: string },
): Promise<void> => {
  try {
    await httpClient.delete(`/admin/reporting-periods/${params.id}`, {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, undefined, params.actorName),
    })
  } catch (error) {
    throw toApiRequestError(error)
  }
}
