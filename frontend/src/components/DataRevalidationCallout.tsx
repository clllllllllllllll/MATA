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

interface DataRevalidationCalloutProps {
  impact?: DataRevalidationImpact | null
  compact?: boolean
}

const warningCountForImpact = (impact: DataRevalidationImpact) =>
  impact.affectedWarningCount ?? impact.affectedWarningIssueIds.length

const warningReviewMessage = (impact: DataRevalidationImpact) => {
  const warningCount = warningCountForImpact(impact)
  const isPartial =
    impact.affectedWarningCountIsPartial === true ||
    impact.affectedWarningDetailsArePartial === true ||
    impact.warningCandidateLimitReached === true

  if (warningCount > 0) {
    const prefix = isPartial ? 'up to ' : ''
    return `This change may affect ${prefix}${warningCount.toLocaleString('en-SG')} warning${
      warningCount === 1 ? '' : 's'
    }. Open Warnings to review the latest list.`
  }

  if (impact.outcome === 'no_op') {
    return 'No additional warning review is needed.'
  }

  return 'This change may affect existing warnings or workflow checks. Open Warnings to review the latest list.'
}

export const DataRevalidationCallout = ({
  impact,
}: DataRevalidationCalloutProps) => {
  if (!impact) {
    return null
  }

  const tone = outcomeTone(impact.outcome)
  const label = outcomeLabel[impact.outcome] ?? 'Data review updated'

  return (
    <div className={`data-revalidation-callout inline-callout callout-${tone}`}>
      <div className="data-revalidation-content">
        <div className="data-revalidation-heading">
          <strong>{label}</strong>
        </div>
        <p>{warningReviewMessage(impact)}</p>
      </div>
    </div>
  )
}
