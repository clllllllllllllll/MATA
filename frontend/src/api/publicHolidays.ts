import { httpClient, toApiRequestError } from './http'
import { buildAdminDemoHeaders } from './authHeaders'

export interface PublicHoliday {
  id: string
  holidayDate: string
  name: string
  dayOfWeek?: string
  year?: number
  createdAt?: string
  updatedAt?: string
}

interface PublicHolidayRequestContext {
  adminId: string
  adminProgrammes: string[]
}

export interface PublicHolidayMutationPayload {
  holidayDate: string
  name: string
}

const toPublicHoliday = (value: Record<string, unknown>): PublicHoliday => ({
  id: String(value.id ?? ''),
  holidayDate: String(value.holiday_date ?? ''),
  name: String(value.name ?? ''),
  dayOfWeek: value.day_of_week ? String(value.day_of_week) : undefined,
  year: typeof value.year === 'number' ? value.year : undefined,
  createdAt: value.created_at ? String(value.created_at) : undefined,
  updatedAt: value.updated_at ? String(value.updated_at) : undefined,
})

const toApiPayload = (payload: PublicHolidayMutationPayload): Record<string, unknown> => ({
  holiday_date: payload.holidayDate,
  name: payload.name,
})

export const listPublicHolidays = async (
  params: PublicHolidayRequestContext,
): Promise<PublicHoliday[]> => {
  try {
    const response = await httpClient.get('/admin/public-holidays', {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes),
    })
    const rows = Array.isArray(response.data) ? response.data : []
    return rows
      .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
      .map(toPublicHoliday)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createPublicHoliday = async (
  params: PublicHolidayRequestContext & { payload: PublicHolidayMutationPayload },
): Promise<PublicHoliday> => {
  try {
    const response = await httpClient.post('/admin/public-holidays', toApiPayload(params.payload), {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes),
    })
    return toPublicHoliday(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const updatePublicHoliday = async (
  params: PublicHolidayRequestContext & {
    id: string
    payload: PublicHolidayMutationPayload
  },
): Promise<PublicHoliday> => {
  try {
    const response = await httpClient.put(
      `/admin/public-holidays/${params.id}`,
      toApiPayload(params.payload),
      {
        headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes),
      },
    )
    return toPublicHoliday(response.data as Record<string, unknown>)
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deletePublicHoliday = async (
  params: PublicHolidayRequestContext & { id: string },
): Promise<void> => {
  try {
    await httpClient.delete(`/admin/public-holidays/${params.id}`, {
      headers: buildAdminDemoHeaders(params.adminId, params.adminProgrammes),
    })
  } catch (error) {
    throw toApiRequestError(error)
  }
}
