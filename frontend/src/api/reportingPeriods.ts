import { httpClient, toApiRequestError } from './http'
import type { ReportingPeriodOption } from '../types/upload'
import { buildAdminDemoHeaders } from './authHeaders'
import { toConfigDeleteResult, toDataRevalidationImpact, type ConfigDeleteResult } from './dataRevalidation'
import { type ReportingPeriodStatus } from '../utils/reportingPeriods'
import {
  parseReportingPeriodListResponse,
  parseReportingPeriodResponse,
} from '../utils/reportingPeriodResponse'

interface ReportingPeriodRequestContext {
  adminId: string
  adminProgrammes: string[]
  actorName?: string
}

export interface ReportingPeriodMutationPayload {
  label?: string
  startDate?: string
  endDate?: string
  status?: ReportingPeriodStatus
  activateOn?: string | null
  deactivateOn?: string | null
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
  if (payload.activateOn !== undefined) {
    body.activate_on = payload.activateOn
  }
  if (payload.deactivateOn !== undefined) {
    body.deactivate_on = payload.deactivateOn
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
    return parseReportingPeriodListResponse(response.data, toDataRevalidationImpact)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createReportingPeriod = async (
  params: ReportingPeriodRequestContext & {
    payload: ReportingPeriodMutationPayload
      & Required<Pick<ReportingPeriodMutationPayload, 'label' | 'startDate' | 'endDate'>>
  },
): Promise<ReportingPeriodOption> => {
  try {
    const response = await httpClient.post('/admin/reporting-periods', toApiPayload(params.payload), {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, undefined, params.actorName),
    })
    return parseReportingPeriodResponse(response.data, toDataRevalidationImpact)
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
    return parseReportingPeriodResponse(response.data, toDataRevalidationImpact)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deleteReportingPeriod = async (
  params: ReportingPeriodRequestContext & { id: string },
): Promise<ConfigDeleteResult> => {
  try {
    const response = await httpClient.delete(`/admin/reporting-periods/${params.id}`, {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes, undefined, params.actorName),
    })
    return toConfigDeleteResult(response.data)
  } catch (error) {
    throw toApiRequestError(error)
  }
}
