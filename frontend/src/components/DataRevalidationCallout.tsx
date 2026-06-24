import type { DataRevalidationImpact } from '../types/dataRevalidation'

const outcomeLabel: Record<string, string> = {
  no_op: 'No data revalidation needed',
  warning_only: 'Warning review only',
  targeted_revalidation: 'Targeted revalidation',
  future_compliance_impact: 'Future compliance impact',
  manual_revalidation_required: 'Manual revalidation required',
}

const outcomeTone = (outcome: string): 'info' | 'success' | 'warning' =>
  outcome === 'no_op' || outcome === 'targeted_revalidation'
    ? 'success'
    : outcome === 'future_compliance_impact' || outcome === 'warning_only'
      ? 'info'
      : 'warning'

const formatKey = (value: string) =>
  value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())

const hasRecordEntries = (value?: Record<string, unknown> | null) =>
  Boolean(value && Object.keys(value).length > 0)

const hasDetails = (impact: DataRevalidationImpact) =>
  hasRecordEntries(impact.affectedScope) ||
  impact.affectedWarningSummaries.length > 0 ||
  impact.affectedWarningIssueIds.length > 0 ||
  Object.keys(impact.affectedEntityCounts).length > 0 ||
  Object.keys(impact.details).length > 0 ||
  Boolean(impact.warningCandidateLimit)

const formatPrimitive = (value: unknown): string => {
  if (value === null || value === undefined || value === '') {
    return 'None'
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No'
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value.toLocaleString('en-SG') : 'None'
  }
  if (typeof value === 'string') {
    return value
  }
  return JSON.stringify(value)
}

const JsonPreview = ({
  value,
  emptyLabel = 'None',
}: {
  value?: Record<string, unknown> | unknown[] | null
  emptyLabel?: string
}) => {
  const isEmpty =
    value === null ||
    value === undefined ||
    (Array.isArray(value) && value.length === 0) ||
    (typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length === 0)

  if (isEmpty) {
    return <p>{emptyLabel}</p>
  }

  return <pre className="raw-json">{JSON.stringify(value, null, 2)}</pre>
}

interface DataRevalidationCalloutProps {
  impact?: DataRevalidationImpact | null
  compact?: boolean
}

export const DataRevalidationCallout = ({
  impact,
}: DataRevalidationCalloutProps) => {
  if (!impact) {
    return null
  }

  const tone = outcomeTone(impact.outcome)
  const label = outcomeLabel[impact.outcome] ?? formatKey(impact.outcome)
  const warningCount = impact.affectedWarningCount ?? impact.affectedWarningIssueIds.length
  const detailsPartial = impact.affectedWarningDetailsArePartial === true
  const countPartial = impact.affectedWarningCountIsPartial === true
  const capReached = impact.warningCandidateLimitReached === true

  return (
    <div className={`data-revalidation-callout inline-callout callout-${tone}`}>
      <div className="data-revalidation-content">
        <div className="data-revalidation-heading">
          <strong>{label}</strong>
          {impact.enrichmentVersion ? <span>{impact.enrichmentVersion}</span> : null}
        </div>
        <p>{impact.summary}</p>
        <div className="data-revalidation-meta">
          {impact.changedEntity ? <span>{formatKey(impact.changedEntity)}</span> : null}
          {impact.scope ? <span>{formatKey(impact.scope)}</span> : null}
          {warningCount > 0 ? (
            <span>
              {countPartial ? 'At least ' : ''}
              {warningCount} affected warning{warningCount === 1 ? '' : 's'}
            </span>
          ) : null}
          {capReached && impact.warningCandidateLimit ? (
            <span>Details capped at {impact.warningCandidateLimit}</span>
          ) : null}
        </div>
        {capReached || detailsPartial || countPartial ? (
          <p className="data-revalidation-partial-note">
            Showing a capped summary. More warnings may be affected.
          </p>
        ) : null}
        {impact.nextActions.length > 0 ? (
          <ul className="data-revalidation-next-actions">
            {impact.nextActions.map((action) => (
              <li key={action}>{action}</li>
            ))}
          </ul>
        ) : null}
        {hasDetails(impact) ? (
          <details className="data-revalidation-details">
            <summary>Impact details</summary>

            <div className="data-revalidation-detail-section">
              <strong>Affected scope</strong>
              <JsonPreview value={impact.affectedScope} />
            </div>

            <div className="data-revalidation-detail-section">
              <strong>Affected warning issue IDs</strong>
              {impact.affectedWarningIssueIds.length > 0 ? (
                <ul>
                  {impact.affectedWarningIssueIds.map((warningIssueId) => (
                    <li key={warningIssueId}>{warningIssueId}</li>
                  ))}
                </ul>
              ) : (
                <p>None</p>
              )}
            </div>

            <div className="data-revalidation-detail-section">
              <strong>Affected warning summaries</strong>
              {impact.affectedWarningSummaries.length > 0 ? (
                <div className="data-revalidation-warning-list">
                  {impact.affectedWarningSummaries.map((warning, index) => (
                    <div key={warning.warning_issue_id ?? `${warning.warning_type ?? 'warning'}-${index}`}>
                      <div className="data-revalidation-warning-heading">
                        <strong>{warning.warning_type ?? 'warning'}</strong>
                        {warning.status ? <span>{warning.status}</span> : null}
                      </div>
                      <span>{warning.message ?? warning.warning_issue_id ?? 'No message recorded.'}</span>
                      {warning.warning_issue_id ? <small>{warning.warning_issue_id}</small> : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p>None</p>
              )}
            </div>

            <div className="data-revalidation-detail-section">
              <strong>Affected entity counts</strong>
              {hasRecordEntries(impact.affectedEntityCounts) ? (
                <dl className="data-revalidation-count-list">
                  {Object.entries(impact.affectedEntityCounts).map(([key, value]) => (
                    <div key={key}>
                      <dt>{formatKey(key)}</dt>
                      <dd>{formatPrimitive(value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p>None</p>
              )}
            </div>

            <div className="data-revalidation-detail-section">
              <strong>Raw details</strong>
              <JsonPreview value={impact.details} />
            </div>

            {impact.warningCandidateLimit ? (
              <div className="data-revalidation-detail-section">
                <strong>Warning candidate cap</strong>
                <dl className="data-revalidation-count-list">
                  <div>
                    <dt>Limit</dt>
                    <dd>{impact.warningCandidateLimit}</dd>
                  </div>
                  <div>
                    <dt>Limit reached</dt>
                    <dd>{impact.warningCandidateLimitReached ? 'Yes' : 'No'}</dd>
                  </div>
                  <div>
                    <dt>Count partial</dt>
                    <dd>{impact.affectedWarningCountIsPartial ? 'Yes' : 'No'}</dd>
                  </div>
                  <div>
                    <dt>Details partial</dt>
                    <dd>{impact.affectedWarningDetailsArePartial ? 'Yes' : 'No'}</dd>
                  </div>
                </dl>
              </div>
            ) : null}
          </details>
        ) : null}
      </div>
    </div>
  )
}
