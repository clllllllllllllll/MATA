import { Fragment, type FormEvent, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  createReportingPeriod,
  deleteReportingPeriod,
  updateReportingPeriod,
} from '../../api/reportingPeriods'
import { ApiRequestError } from '../../api/http'
import { DetailDrawer } from '../../components/DetailDrawer'
import { StatusBadge } from '../../components/StatusBadge'
import { IconChevRight, IconPlus, IconRefresh, NamedIcon } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { useAppState } from '../../context/useAppState'
import type { ReportingPeriodOption } from '../../types/upload'

type ConfigSectionKey =
  | 'reporting-periods'
  | 'public-holidays'
  | 'programmes'
  | 'loa-types'
  | 'multi-posting-rules'
  | 'posting-groups'
  | 'weekend-exceptions'
  | 'global-session-types'

interface ConfigSection {
  key: ConfigSectionKey
  label: string
  icon: string
  status: string
  title: string
  description: string
  stateLabel: string
  nextStep: string
  rows: Array<{
    field: string
    current: string
    next: string
    mono?: boolean
  }>
  actionLabel?: string
  actionPath?: string
}

interface ReportingPeriodFormState {
  label: string
  startDate: string
  endDate: string
  status: 'open' | 'closed'
}

type Feedback = {
  tone: 'success' | 'error'
  message: string
  description?: string
  detailsLabel?: string
  dependencyDetails?: Array<{
    label: string
    count: number
  }>
  rawMessage?: string
} | null

const emptyReportingPeriodForm: ReportingPeriodFormState = {
  label: '',
  startDate: '',
  endDate: '',
  status: 'open',
}

const configSections: ConfigSection[] = [
  {
    key: 'reporting-periods',
    label: 'Reporting Periods',
    icon: 'calendar',
    status: 'Live',
    title: 'Reporting Periods',
    description: 'Reporting periods are required before RDB, TTF, and FormF1 uploads can be safely scoped.',
    stateLabel: 'Live CRUD',
    nextStep:
      'Create and maintain reporting periods here. Delete is blocked when period-dependent records exist.',
    rows: [],
  },
  {
    key: 'public-holidays',
    label: 'Public Holidays',
    icon: 'calendar',
    status: 'Upload',
    title: 'Public Holidays',
    description: 'Holiday and AY boundary data is currently upload-driven from the Academic Calendar / Public Holiday workbook.',
    stateLabel: 'Upload-driven data; manual CRUD pending',
    nextStep:
      'Manual CRUD can be added later. MOM/public holiday sync is intentionally not implemented in this task.',
    rows: [
      {
        field: 'Source',
        current: 'Academic Calendar / Public Holiday workbook upload.',
        next: 'Keep manual edits behind a future CRUD task.',
      },
      {
        field: 'Runtime use',
        current: 'Public holidays block secretary and resident ad-hoc event creation server-side.',
        next: 'Expose read/edit controls only after endpoint scope is confirmed.',
      },
      {
        field: 'External sync',
        current: 'No MOM sync in this shell.',
        next: 'Do not add sync behavior here.',
      },
    ],
  },
  {
    key: 'programmes',
    label: 'Programmes',
    icon: 'database',
    status: 'Seeded',
    title: 'Programmes',
    description: 'Programme definitions are seeded in the database and later CRUD-manageable.',
    stateLabel: 'Read-only preview pending',
    nextStep: 'Future CRUD should preserve programme scope and source-of-truth rules before edits are enabled.',
    rows: [
      {
        field: 'Seed source',
        current: 'Programme catalogue is database-seeded.',
        next: 'Add safe edit controls for aliases, r-year behavior, and AY categories later.',
      },
      {
        field: 'Scope',
        current: 'Admin accounts are programme-scoped.',
        next: 'Server-side scope checks must remain authoritative.',
      },
      {
        field: 'Current mode',
        current: 'No programme rows are displayed here yet.',
        next: 'Read-only preview pending.',
      },
    ],
  },
  {
    key: 'loa-types',
    label: 'LOA Types',
    icon: 'file',
    status: 'Seeded',
    title: 'LOA Types',
    description: 'LOA types are seeded and later CRUD-manageable.',
    stateLabel: 'CRUD wiring pending',
    nextStep: 'Expose maintenance controls only after validation and audit rules are confirmed.',
    rows: [
      {
        field: 'Seeded list',
        current: 'Confirmed LOA types are seeded for parser/audit display.',
        next: 'Manual CRUD pending.',
      },
      {
        field: 'Parser behavior',
        current: 'Unknown LOA values should warn rather than reject uploads.',
        next: 'Keep parser behavior unchanged in this UI task.',
      },
      {
        field: 'Compliance',
        current: 'Compliance denominator remains governed by FormF1 active/inactive status.',
        next: 'Do not add compliance logic here.',
      },
    ],
  },
  {
    key: 'multi-posting-rules',
    label: 'Multi-Posting Rules',
    icon: 'settings',
    status: 'Linked',
    title: 'Multi-Posting Rules',
    description: 'Rules are seeded and managed through the dedicated Multi-Posting Rules page.',
    stateLabel: 'Manage via dedicated Multi-Posting Rules page',
    nextStep:
      'Warning re-evaluation is a future backend task and is not implemented in this shell.',
    actionLabel: 'Open Multi-Posting Rules',
    actionPath: '/admin/config/multi',
    rows: [
      {
        field: 'Dedicated page',
        current: '/admin/config/multi',
        next: 'Open the existing deep-link page for the current multi-posting workflow.',
        mono: true,
      },
      {
        field: 'Parser impact',
        current: 'Rules apply when RDB parsing resolves combined or split posting cells.',
        next: 'Changes should apply on next RDB re-upload.',
      },
      {
        field: 'Warning handling',
        current: 'This shell does not re-evaluate existing warnings.',
        next: 'Backend warning re-evaluation remains future work.',
      },
    ],
  },
  {
    key: 'posting-groups',
    label: 'Posting Groups',
    icon: 'grid',
    status: 'Pending',
    title: 'Posting Groups',
    description: 'Posting groups pool related posting codes for compliance aggregation and are separate from multi-posting rules.',
    stateLabel: 'Manual CRUD wiring pending',
    nextStep:
      'Groups are seeded from TTF Column E. Manual CRUD should keep grouped posting aggregation distinct from multi-posting parse rules.',
    rows: [
      {
        field: 'Use case',
        current: 'Pool related posting codes so compliance can aggregate across a group.',
        next: 'Expose group maintenance after CRUD endpoints and validation are ready.',
      },
      {
        field: 'Seed source',
        current: 'Seeded from non-empty TTF Column E values.',
        next: 'Keep upload seeding behavior unchanged.',
      },
      {
        field: 'Not the same as',
        current: 'Multi-posting rules.',
        next: 'Use multi-posting rules for RDB cell collapse/split behavior, not group aggregation.',
      },
    ],
  },
  {
    key: 'weekend-exceptions',
    label: 'Weekend Exceptions',
    icon: 'calendar',
    status: 'Seeded',
    title: 'Weekend Exceptions',
    description: 'Weekend exceptions are seeded and later CRUD-manageable.',
    stateLabel: 'CRUD wiring pending',
    nextStep: 'Future edits should preserve read-time exception behavior and confirmed programme-specific rules.',
    rows: [
      {
        field: 'Current source',
        current: 'Seeded weekend exception configuration.',
        next: 'Manual CRUD pending.',
      },
      {
        field: 'Compliance use',
        current: 'Exceptions decide whether weekend sessions count, including read-time ORTHO mutation.',
        next: 'Do not mutate raw attendance records.',
      },
      {
        field: 'Current mode',
        current: 'No editable rows exposed here.',
        next: 'CRUD wiring pending.',
      },
    ],
  },
  {
    key: 'global-session-types',
    label: 'Global Session Types',
    icon: 'settings',
    status: 'Pending',
    title: 'Global Session Types',
    description: 'Global session types are compliance-exempt teaching names and later CRUD-manageable.',
    stateLabel: 'CRUD wiring pending',
    nextStep:
      'Future CRUD should keep active global names available to secretary/resident dropdowns while excluding them from compliance.',
    rows: [
      {
        field: 'Compliance effect',
        current: 'Matching global session types are excluded from both numerator and denominator.',
        next: 'Keep this exclusion server-side.',
      },
      {
        field: 'Dropdown use',
        current: 'Secretary and resident ad-hoc flows can include global teaching names when wired.',
        next: 'Manual CRUD pending.',
      },
      {
        field: 'Current mode',
        current: 'Read-only placeholder.',
        next: 'CRUD wiring pending.',
      },
    ],
  },
]

const formatDate = (value?: string) => {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat('en-SG', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(parsed)
}

const dependencyLabels: Record<string, string> = {
  upload_logs: 'upload logs',
  resident_postings: 'resident postings',
  teaching_targets: 'teaching targets',
  teaching_name_catalogue: 'teaching name catalogue',
  form_f1_records: 'FormF1 records',
  academic_month_boundaries: 'academic month boundaries',
  period_snapshots: 'period snapshots',
  clawback_records: 'clawback records',
  surplus_ledger: 'surplus ledger rows',
}

const dependencyLabelPatterns = Object.values(dependencyLabels).map((label) => ({
  label,
  pattern: new RegExp(`${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}:\\s*(\\d+)`, 'i'),
}))

const toDependencyDetails = (dependencies?: Record<string, number>) =>
  dependencies
    ? Object.entries(dependencies).map(([key, count]) => ({
        label: dependencyLabels[key] ?? key,
        count,
      }))
    : []

const parseDependencyDetailsFromMessage = (message: string) =>
  dependencyLabelPatterns
    .map(({ label, pattern }) => {
      const match = message.match(pattern)
      return match ? { label, count: Number(match[1]) } : null
    })
    .filter((detail): detail is { label: string; count: number } => detail !== null)

const describeDeleteError = (error: unknown): NonNullable<Feedback> => {
  if (!(error instanceof ApiRequestError)) {
    return {
      tone: 'error',
      message: 'Unable to delete reporting period.',
    }
  }
  const metadata = (error.details as { metadata?: { dependencies?: Record<string, number> } } | undefined)
    ?.metadata
  const dependencyDetails = toDependencyDetails(metadata?.dependencies)
  const parsedDetails =
    dependencyDetails.length > 0 ? dependencyDetails : parseDependencyDetailsFromMessage(error.message)
  const isBlockedDelete =
    error.status === 409 ||
    error.message.toLowerCase().includes('reporting period is in use') ||
    parsedDetails.length > 0

  if (isBlockedDelete) {
    return {
      tone: 'error',
      message: 'This reporting period is already in use and cannot be deleted.',
      description:
        'It has linked uploads and parsed records. Keep it for audit history, or create a new reporting period instead.',
      detailsLabel: 'View linked record details',
      dependencyDetails: parsedDetails,
      rawMessage: parsedDetails.length > 0 ? undefined : error.message,
    }
  }
  return {
    tone: 'error',
    message: error.message,
  }
}

const periodStatusTone = (status: string): 'success' | 'neutral' =>
  status.toLowerCase() === 'open' ? 'success' : 'neutral'

const toFormState = (period: ReportingPeriodOption): ReportingPeriodFormState => ({
  label: period.label,
  startDate: period.startDate,
  endDate: period.endDate,
  status: period.status.toLowerCase() === 'closed' ? 'closed' : 'open',
})

const ReportingPeriodsSection = () => {
  const {
    reportingPeriods,
    reportingPeriodsLoading,
    reportingPeriodsError,
    reloadReportingPeriods,
    demoAdminId,
    demoAdminProgrammes,
  } = useAppState()
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit'>('create')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedPeriod, setSelectedPeriod] = useState<ReportingPeriodOption | null>(null)
  const [formState, setFormState] = useState<ReportingPeriodFormState>(emptyReportingPeriodForm)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmingDeletePeriod, setConfirmingDeletePeriod] =
    useState<ReportingPeriodOption | null>(null)
  const [feedbackDetailsOpen, setFeedbackDetailsOpen] = useState(false)

  const sortedPeriods = useMemo(
    () =>
      [...reportingPeriods].sort((left, right) => {
        const leftStart = new Date(left.startDate).getTime()
        const rightStart = new Date(right.startDate).getTime()
        return rightStart - leftStart
      }),
    [reportingPeriods],
  )

  const openCreateDrawer = () => {
    setDrawerMode('create')
    setSelectedPeriod(null)
    setFormState(emptyReportingPeriodForm)
    setSubmitState('idle')
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    setConfirmingDeletePeriod(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (period: ReportingPeriodOption) => {
    setDrawerMode('edit')
    setSelectedPeriod(period)
    setFormState(toFormState(period))
    setSubmitState('idle')
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    setConfirmingDeletePeriod(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (submitState === 'submitting') {
      return
    }
    setDrawerOpen(false)
    setSelectedPeriod(null)
    setFormState(emptyReportingPeriodForm)
    setSubmitState('idle')
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitState('submitting')
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    try {
      if (drawerMode === 'edit' && selectedPeriod) {
        await updateReportingPeriod({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          id: selectedPeriod.id,
          payload: formState,
        })
        setFeedback({ tone: 'success', message: 'Reporting period updated.' })
      } else {
        await createReportingPeriod({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          payload: {
            label: formState.label,
            startDate: formState.startDate,
            endDate: formState.endDate,
          },
        })
        setFeedback({ tone: 'success', message: 'Reporting period created.' })
      }
      await reloadReportingPeriods()
      setDrawerOpen(false)
      setSelectedPeriod(null)
      setFormState(emptyReportingPeriodForm)
      setSubmitState('idle')
    } catch (error) {
      setSubmitState('error')
      setFeedback({
        tone: 'error',
        message: error instanceof ApiRequestError ? error.message : 'Unable to save reporting period.',
      })
    }
  }

  const requestDelete = (period: ReportingPeriodOption) => {
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    setConfirmingDeletePeriod(period)
  }

  const dismissFeedback = () => {
    setFeedback(null)
    setFeedbackDetailsOpen(false)
  }

  const handleDelete = async (period: ReportingPeriodOption) => {
    setDeletingId(period.id)
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    try {
      await deleteReportingPeriod({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        id: period.id,
      })
      setFeedback({ tone: 'success', message: 'Reporting period deleted.' })
      await reloadReportingPeriods()
      setConfirmingDeletePeriod(null)
    } catch (error) {
      setConfirmingDeletePeriod(null)
      setFeedback(describeDeleteError(error))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <header className="admin-config-content-header">
        <div>
          <div className="admin-config-title-row">
            <h2>Reporting Periods</h2>
          </div>
          <p>Six-month windows used by uploads, attendance bucketing, snapshots, and surplus resets.</p>
        </div>
        <div className="admin-config-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reloadReportingPeriods()}
            disabled={reportingPeriodsLoading}
          >
            <IconRefresh size={14} />
            Retry
          </button>
          <button type="button" className="button button-primary" onClick={openCreateDrawer}>
            <IconPlus size={14} />
            New Period
          </button>
        </div>
      </header>

      {feedback ? (
        <div
          className={`inline-callout ${feedback.tone === 'error' ? 'callout-error' : 'callout-success'} admin-config-feedback`}
          role="status"
        >
          <div className="admin-config-feedback-content">
            <strong>{feedback.message}</strong>
            {feedback.description ? <p>{feedback.description}</p> : null}
            {feedback.detailsLabel && (feedback.dependencyDetails?.length || feedback.rawMessage) ? (
              <>
                <button
                  type="button"
                  className="admin-config-details-toggle"
                  onClick={() => setFeedbackDetailsOpen((open) => !open)}
                  aria-expanded={feedbackDetailsOpen}
                >
                  {feedbackDetailsOpen ? 'Hide linked record details' : feedback.detailsLabel}
                </button>
                {feedbackDetailsOpen ? (
                  <div className="admin-config-feedback-details">
                    {feedback.dependencyDetails?.length ? (
                      <dl className="admin-config-dependency-list">
                        {feedback.dependencyDetails.map((detail) => (
                          <Fragment key={detail.label}>
                            <dt>{detail.label}</dt>
                            <dd>{detail.count.toLocaleString('en-SG')}</dd>
                          </Fragment>
                        ))}
                      </dl>
                    ) : null}
                    {feedback.rawMessage ? (
                      <p className="admin-config-raw-error">{feedback.rawMessage}</p>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
          <button
            type="button"
            className="admin-config-feedback-dismiss"
            onClick={dismissFeedback}
            aria-label="Dismiss feedback"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {reportingPeriodsLoading ? (
        <div className="configuration-empty-note">Loading reporting periods...</div>
      ) : reportingPeriodsError ? (
        <div className="configuration-empty-note">
          <div>
            <h3>Unable to load reporting periods</h3>
            <p>{reportingPeriodsError}</p>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void reloadReportingPeriods()}
            >
              <IconRefresh size={14} />
              Retry
            </button>
          </div>
        </div>
      ) : sortedPeriods.length === 0 ? (
        <div className="configuration-empty-note">
          <div>
            <h3>No reporting periods yet</h3>
            <p>Create the first period before upload workflows are used.</p>
          </div>
        </div>
      ) : (
        <div className="admin-config-table-wrap">
          <table className="admin-config-table reporting-periods-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Start Date</th>
                <th>End Date</th>
                <th>Status</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedPeriods.map((period) => (
                <Fragment key={period.id}>
                  <tr>
                    <td>{period.label}</td>
                    <td>{formatDate(period.startDate)}</td>
                    <td>{formatDate(period.endDate)}</td>
                    <td>
                      <StatusBadge label={period.status} tone={periodStatusTone(period.status)} />
                    </td>
                    <td>{formatDate(period.updatedAt)}</td>
                    <td>
                      <div className="admin-config-row-actions">
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => openEditDrawer(period)}
                          disabled={deletingId === period.id}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="button button-ghost danger"
                          onClick={() => requestDelete(period)}
                          disabled={deletingId === period.id}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                  {confirmingDeletePeriod?.id === period.id ? (
                    <tr className="admin-config-confirm-row">
                      <td colSpan={6}>
                        <div
                          className="admin-config-inline-confirm"
                          role="group"
                          aria-label={`Delete reporting period ${period.label}`}
                        >
                          <div>
                            <strong>{`Delete reporting period "${period.label}"?`}</strong>
                            <p>
                              This only succeeds if the period has no linked uploads or parsed
                              records.
                            </p>
                          </div>
                          <div className="admin-config-confirm-actions">
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => setConfirmingDeletePeriod(null)}
                              disabled={deletingId === period.id}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="button button-ghost danger"
                              onClick={() => void handleDelete(period)}
                              disabled={deletingId === period.id}
                            >
                              {deletingId === period.id ? 'Deleting...' : 'Delete period'}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <DetailDrawer
        title={drawerMode === 'edit' ? 'Edit Reporting Period' : 'New Reporting Period'}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-secondary" onClick={closeDrawer}>
              Cancel
            </button>
            <button
              type="submit"
              form="reporting-period-form"
              className="button button-primary"
              disabled={submitState === 'submitting'}
            >
              {submitState === 'submitting' ? 'Saving...' : 'Save'}
            </button>
          </>
        }
      >
        <form id="reporting-period-form" className="secretary-form-grid" onSubmit={handleSubmit}>
          <label>
            Label
            <input
              type="text"
              value={formState.label}
              onChange={(event) => setFormState((prev) => ({ ...prev, label: event.target.value }))}
              required
              maxLength={30}
            />
          </label>
          <div className="secretary-form-row">
            <label>
              Start date
              <input
                type="date"
                value={formState.startDate}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, startDate: event.target.value }))
                }
                required
              />
            </label>
            <label>
              End date
              <input
                type="date"
                value={formState.endDate}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, endDate: event.target.value }))
                }
                required
              />
            </label>
          </div>
          {drawerMode === 'edit' ? (
            <label>
              Status
              <select
                value={formState.status}
                onChange={(event) =>
                  setFormState((prev) => ({
                    ...prev,
                    status: event.target.value === 'closed' ? 'closed' : 'open',
                  }))
                }
              >
                <option value="open">Open</option>
                <option value="closed">Closed</option>
              </select>
            </label>
          ) : null}
          {submitState === 'error' && feedback ? (
            <div className="inline-callout callout-error">{feedback.message}</div>
          ) : null}
        </form>
      </DetailDrawer>
    </>
  )
}

const PlaceholderConfigSection = ({
  activeSection,
  onNavigate,
}: {
  activeSection: ConfigSection
  onNavigate: (path: string) => void
}) => (
  <>
    <header className="admin-config-content-header">
      <div>
        <div className="admin-config-title-row">
          <h2>{activeSection.title}</h2>
          <span className="admin-config-status-chip">{activeSection.stateLabel}</span>
        </div>
        <p>{activeSection.description}</p>
      </div>
      {activeSection.actionLabel && activeSection.actionPath ? (
        <button
          type="button"
          className="button button-primary"
          onClick={() => onNavigate(activeSection.actionPath ?? '/admin/config/multi')}
        >
          {activeSection.actionLabel}
          <IconChevRight size={14} />
        </button>
      ) : null}
    </header>

    <div className="admin-config-callout">
      <strong>Next step</strong>
      <span>{activeSection.nextStep}</span>
    </div>

    <div className="admin-config-table-wrap">
      <table className="admin-config-table">
        <thead>
          <tr>
            <th>Area</th>
            <th>Current treatment</th>
            <th>Planned follow-up</th>
          </tr>
        </thead>
        <tbody>
          {activeSection.rows.map((row) => (
            <tr key={row.field}>
              <td className={row.mono ? 'mono' : undefined}>{row.field}</td>
              <td className={row.mono ? 'mono' : undefined}>{row.current}</td>
              <td>{row.next}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </>
)

export const AdminConfigPage = () => {
  const navigate = useNavigate()
  const [activeSectionKey, setActiveSectionKey] = useState<ConfigSectionKey>('reporting-periods')
  const activeSection =
    configSections.find((section) => section.key === activeSectionKey) ?? configSections[0]

  return (
    <div className="page admin-config-page">
      <PageHero title="Configuration" subtitle="Master Admin - All programmes" />

      <section className="admin-config-shell" aria-label="Configuration sections">
        <nav className="admin-config-nav-card" aria-label="Configuration navigation">
          {configSections.map((section) => {
            const isActive = section.key === activeSection.key
            return (
              <button
                key={section.key}
                type="button"
                className={`admin-config-nav-item ${isActive ? 'is-active' : ''}`}
                onClick={() => setActiveSectionKey(section.key)}
                aria-current={isActive ? 'page' : undefined}
              >
                <span className="admin-config-nav-main">
                  <NamedIcon name={section.icon} size={14} />
                  <span>{section.label}</span>
                </span>
                <span className="admin-config-nav-chip">{section.status}</span>
              </button>
            )
          })}
        </nav>

        <article className="card admin-config-content-card">
          {activeSection.key === 'reporting-periods' ? (
            <ReportingPeriodsSection />
          ) : (
            <PlaceholderConfigSection
              activeSection={activeSection}
              onNavigate={(path) => navigate(path)}
            />
          )}
        </article>
      </section>
    </div>
  )
}
