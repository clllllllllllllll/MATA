import type {
  DataRevalidationImpact,
  DataRevalidationWarningSummary,
} from '../types/dataRevalidation'

const optionalString = (value: unknown): string | null => {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || null
}

const optionalNumber = (value: unknown): number | null => {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

const toStringArray = (value: unknown): string[] => {
  if (!Array.isArray(value)) {
    return []
  }
  return value.map((item) => String(item ?? '').trim()).filter(Boolean)
}

const toRecord = (value: unknown): Record<string, unknown> => {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : {}
}

const toWarningSummaries = (value: unknown): DataRevalidationWarningSummary[] => {
  if (!Array.isArray(value)) {
    return []
  }
  return value
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item) => ({
      ...item,
      warning_issue_id: optionalString(item.warning_issue_id),
      latest_upload_warning_id: optionalString(item.latest_upload_warning_id),
      warning_type: optionalString(item.warning_type),
      status: optionalString(item.status),
      programme_code: optionalString(item.programme_code),
      reporting_period_id: optionalString(item.reporting_period_id),
      message: optionalString(item.message),
    }))
}

export const toDataRevalidationImpact = (value: unknown): DataRevalidationImpact | null => {
  if (typeof value !== 'object' || value === null) {
    return null
  }

  const payload = value as Record<string, unknown>
  const summary = optionalString(payload.summary) ?? optionalString(payload.reason) ?? 'Data revalidation impact recorded.'

  return {
    outcome: optionalString(payload.outcome) ?? 'no_op',
    triggerSource: optionalString(payload.trigger_source),
    changedEntity: optionalString(payload.changed_entity),
    action: optionalString(payload.action),
    scope: optionalString(payload.scope),
    summary,
    reason: optionalString(payload.reason),
    rowsExamined: optionalNumber(payload.rows_examined) ?? 0,
    rowsUpdated: optionalNumber(payload.rows_updated) ?? 0,
    warningsCreated: optionalNumber(payload.warnings_created) ?? 0,
    warningsUpdated: optionalNumber(payload.warnings_updated) ?? 0,
    warningsResolved: optionalNumber(payload.warnings_resolved) ?? 0,
    warningsRemaining: optionalNumber(payload.warnings_remaining) ?? 0,
    affectedModels: toStringArray(payload.affected_models),
    affectedWarningIds: toStringArray(payload.affected_warning_ids),
    affectedScope: typeof payload.affected_scope === 'object' && payload.affected_scope !== null
      ? payload.affected_scope as Record<string, unknown>
      : null,
    affectedWarningCount: optionalNumber(payload.affected_warning_count),
    affectedWarningIssueIds: toStringArray(payload.affected_warning_issue_ids),
    affectedWarningSummaries: toWarningSummaries(payload.affected_warning_summaries),
    affectedWarningCountIsPartial:
      typeof payload.affected_warning_count_is_partial === 'boolean'
        ? payload.affected_warning_count_is_partial
        : null,
    affectedWarningDetailsArePartial:
      typeof payload.affected_warning_details_are_partial === 'boolean'
        ? payload.affected_warning_details_are_partial
        : null,
    warningCandidateLimit: optionalNumber(payload.warning_candidate_limit),
    warningCandidateLimitReached:
      typeof payload.warning_candidate_limit_reached === 'boolean'
        ? payload.warning_candidate_limit_reached
        : null,
    affectedEntityCounts: toRecord(payload.affected_entity_counts),
    nextActions: toStringArray(payload.next_actions),
    enrichmentVersion: optionalString(payload.enrichment_version),
    details: toRecord(payload.details),
  }
}

export interface ConfigDeleteResult {
  entityType: string
  entityId: string
  deleted: boolean
  dataRevalidation?: DataRevalidationImpact | null
}

export const toConfigDeleteResult = (value: unknown): ConfigDeleteResult => {
  const payload = toRecord(value)
  return {
    entityType: optionalString(payload.entity_type) ?? '',
    entityId: optionalString(payload.entity_id) ?? '',
    deleted: payload.deleted !== false,
    dataRevalidation: toDataRevalidationImpact(payload.data_revalidation),
  }
}

