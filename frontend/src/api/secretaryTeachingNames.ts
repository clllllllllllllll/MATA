import { buildSecretaryDemoHeaders } from './authHeaders'
import { httpClient, toApiRequestError } from './http'

export const secretaryTeachingNamesChangedEvent = 'mata:secretary-teaching-names-changed'

export interface SecretaryTeachingNameProgramme {
  programmeCode: string
}

export interface SecretaryTeachingName {
  id: string
  reportingPeriodId: string
  programmeCode: string
  teachingName: string
  isActive: boolean
  revision: number
  createdAt?: string
  updatedAt?: string
  deactivatedAt?: string
}

export interface SecretaryTeachingNameList {
  items: SecretaryTeachingName[]
  total: number
  limit: number
  offset: number
}

const optionalString = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0 ? value : undefined

const toNumber = (value: unknown, fallback = 0): number => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) {
      return parsed
    }
  }
  return fallback
}

const toTeachingName = (value: Record<string, unknown>): SecretaryTeachingName => ({
  id: String(value.id ?? ''),
  reportingPeriodId: String(value.reporting_period_id ?? ''),
  programmeCode: String(value.programme_code ?? ''),
  teachingName: String(value.teaching_name ?? ''),
  isActive: Boolean(value.is_active),
  revision: toNumber(value.revision, 1),
  createdAt: optionalString(value.created_at),
  updatedAt: optionalString(value.updated_at),
  deactivatedAt: optionalString(value.deactivated_at),
})

const toRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}

export const listSecretaryTeachingNameProgrammes = async (): Promise<SecretaryTeachingNameProgramme[]> => {
  try {
    const response = await httpClient.get('/secretary/teaching-name-programmes', {
      headers: buildSecretaryDemoHeaders(),
    })
    const rows = (response.data as { items?: unknown })?.items
    return Array.isArray(rows)
      ? rows
          .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
          .map((row) => ({ programmeCode: String(row.programme_code ?? '').trim() }))
          .filter((row) => row.programmeCode.length > 0)
      : []
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const listSecretaryTeachingNames = async (params: {
  reportingPeriodId: string
  programmeCode: string
  isActive?: boolean
  search?: string
  limit?: number
  offset?: number
}): Promise<SecretaryTeachingNameList> => {
  try {
    const response = await httpClient.get('/secretary/teaching-names', {
      params: {
        reporting_period_id: params.reportingPeriodId,
        programme_code: params.programmeCode,
        is_active: params.isActive,
        search: params.search?.trim() || undefined,
        limit: params.limit ?? 50,
        offset: params.offset ?? 0,
      },
      headers: buildSecretaryDemoHeaders(),
    })
    const payload = toRecord(response.data)
    const rows = Array.isArray(payload.items) ? payload.items : []
    const limit = toNumber(payload.limit, params.limit ?? 50)
    const offset = toNumber(payload.offset, params.offset ?? 0)
    return {
      items: rows
        .filter((row): row is Record<string, unknown> => typeof row === 'object' && row !== null)
        .map(toTeachingName),
      total: toNumber(payload.total),
      limit,
      offset,
    }
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const createSecretaryTeachingName = async (payload: {
  reportingPeriodId: string
  programmeCode: string
  teachingName: string
}): Promise<SecretaryTeachingName> => {
  try {
    const response = await httpClient.post('/secretary/teaching-names', {
      reporting_period_id: payload.reportingPeriodId,
      programme_code: payload.programmeCode,
      teaching_name: payload.teachingName,
    }, {
      headers: buildSecretaryDemoHeaders(),
    })
    return toTeachingName(toRecord(response.data))
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const renameSecretaryTeachingName = async (params: {
  teachingNameId: string
  teachingName: string
  expectedRevision: number
}): Promise<SecretaryTeachingName> => {
  try {
    const response = await httpClient.patch(`/secretary/teaching-names/${params.teachingNameId}`, {
      teaching_name: params.teachingName,
      expected_revision: params.expectedRevision,
    }, {
      headers: buildSecretaryDemoHeaders(),
    })
    return toTeachingName(toRecord(response.data))
  } catch (error) {
    throw toApiRequestError(error)
  }
}

const updateSecretaryTeachingNameStatus = async (params: {
  teachingNameId: string
  expectedRevision: number
  action: 'deactivate' | 'reactivate'
}): Promise<SecretaryTeachingName> => {
  try {
    const response = await httpClient.post(
      `/secretary/teaching-names/${params.teachingNameId}/${params.action}`,
      { expected_revision: params.expectedRevision },
      { headers: buildSecretaryDemoHeaders() },
    )
    return toTeachingName(toRecord(response.data))
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const deactivateSecretaryTeachingName = (params: {
  teachingNameId: string
  expectedRevision: number
}) => updateSecretaryTeachingNameStatus({ ...params, action: 'deactivate' })

export const reactivateSecretaryTeachingName = (params: {
  teachingNameId: string
  expectedRevision: number
}) => updateSecretaryTeachingNameStatus({ ...params, action: 'reactivate' })

export const deleteSecretaryTeachingName = async (params: {
  teachingNameId: string
  expectedRevision: number
}): Promise<void> => {
  try {
    await httpClient.delete(`/secretary/teaching-names/${params.teachingNameId}`, {
      data: { expected_revision: params.expectedRevision },
      headers: buildSecretaryDemoHeaders(),
    })
  } catch (error) {
    throw toApiRequestError(error)
  }
}

export const notifySecretaryTeachingNamesChanged = () => {
  window.dispatchEvent(new Event(secretaryTeachingNamesChangedEvent))
}
