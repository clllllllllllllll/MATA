export type DataRevalidationOutcome =
  | 'no_op'
  | 'warning_only'
  | 'targeted_revalidation'
  | 'future_compliance_impact'
  | 'manual_revalidation_required'
  | string

export interface DataRevalidationWarningSummary {
  warning_issue_id?: string | null
  latest_upload_warning_id?: string | null
  warning_type?: string | null
  status?: string | null
  programme_code?: string | null
  reporting_period_id?: string | null
  message?: string | null
  [key: string]: unknown
}

export interface DataRevalidationImpact {
  outcome: DataRevalidationOutcome
  triggerSource?: string | null
  changedEntity?: string | null
  action?: string | null
  scope?: string | null
  summary: string
  reason?: string | null
  rowsExamined?: number
  rowsUpdated?: number
  warningsCreated?: number
  warningsUpdated?: number
  warningsResolved?: number
  warningsRemaining?: number
  affectedModels: string[]
  affectedWarningIds: string[]
  affectedScope?: Record<string, unknown> | null
  affectedWarningCount?: number | null
  affectedWarningIssueIds: string[]
  affectedWarningSummaries: DataRevalidationWarningSummary[]
  affectedWarningCountIsPartial?: boolean | null
  affectedWarningDetailsArePartial?: boolean | null
  warningCandidateLimit?: number | null
  warningCandidateLimitReached?: boolean | null
  affectedEntityCounts: Record<string, unknown>
  nextActions: string[]
  enrichmentVersion?: string | null
  details: Record<string, unknown>
}

