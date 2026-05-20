import { httpClient, toApiRequestError } from './http'
import type { ReportingPeriodOption } from '../types/upload'
import { buildAdminDemoHeaders } from './authHeaders'

const toReportingPeriod = (value: Record<string, unknown>): ReportingPeriodOption => ({
  id: String(value.id ?? ''),
  label: String(value.label ?? ''),
  startDate: String(value.start_date ?? ''),
  endDate: String(value.end_date ?? ''),
  status: String(value.status ?? ''),
})

export const listReportingPeriods = async (params: {
  adminId: string
  adminProgrammes: string[]
}): Promise<ReportingPeriodOption[]> => {
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
