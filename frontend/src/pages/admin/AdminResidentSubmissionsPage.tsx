import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  getAdminResidentSubmission,
  listAdminResidentSubmissions,
  type AdminResidentSubmissionDetail,
  type AdminResidentSubmissionListItem,
  type AdminResidentSubmissionListSummary,
  type AdminResidentSubmissionSource,
  type AdminResidentSubmissionStatus,
} from '../../api/adminResidentSubmissions'
import { listPostingCodes, type PostingCodeOption } from '../../api/postingCodes'
import { listProgrammes, type Programme } from '../../api/programmes'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'

type StatusFilter = 'all' | AdminResidentSubmissionStatus
type SourceFilter = 'all' | AdminResidentSubmissionSource

interface FilterState {
  reportingPeriodId: string
  programmeCode: string
  postingCode: string
  status: StatusFilter
  source: SourceFilter
  dateFrom: string
  dateTo: string
  search: string
}

const pageSize = 25
const searchDebounceMs = 300

const emptySummary: AdminResidentSubmissionListSummary = {
  totalSubmissions: 0,
  submittedCount: 0,
  flaggedCount: 0,
  removedCount: 0,
  secretaryEventCount: 0,
  adhocCount: 0,
}

const formatDate = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const formatDateTime = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

const formatTime = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  const parts = value.split(':')
  if (parts.length < 2) {
    return value
  }
  const hours = Number(parts[0])
  if (!Number.isFinite(hours)) {
    return value
  }
  const minutes = parts[1]
  const suffix = hours >= 12 ? 'pm' : 'am'
  const hour12 = hours % 12 || 12
  return `${hour12}:${minutes} ${suffix}`
}

const formatDuration = (value?: number | null) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '-'
  }
  const label = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return `${label}h`
}

const fieldValue = (value?: string | number | boolean | null) => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No'
  }
  return String(value)
}

const statusTone = (status?: string): 'success' | 'warning' | 'critical' | 'info' | 'neutral' => {
  if (status === 'submitted') {
    return 'success'
  }
  if (status === 'flagged') {
    return 'warning'
  }
  if (status === 'removed') {
    return 'critical'
  }
  return 'neutral'
}

const sourceTone = (source?: string): 'success' | 'warning' | 'critical' | 'info' | 'neutral' =>
  source === 'Ad-hoc' ? 'warning' : 'info'

const toSourceParam = (value: SourceFilter): AdminResidentSubmissionSource | undefined =>
  value === 'all' ? undefined : value

const toStatusParam = (value: StatusFilter): AdminResidentSubmissionStatus | undefined =>
  value === 'all' ? undefined : value

const DetailField = ({
  label,
  value,
}: {
  label: string
  value?: string | number | boolean | null
}) => (
  <div className="parsed-data-detail-item">
    <span>{label}</span>
    <strong>{fieldValue(value)}</strong>
  </div>
)

const MetricTile = ({
  label,
  value,
}: {
  label: string
  value: number
}) => (
  <div className="secretary-event-metric">
    <span>{label}</span>
    <strong>{value}</strong>
  </div>
)

export const AdminResidentSubmissionsPage = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const {
    role,
    demoAdminId,
    demoAdminProgrammes,
    reportingPeriodId,
    reportingPeriods,
    reportingPeriodsLoading,
    reportingPeriodsError,
  } = useAppState()
  const adminLevel = role === 'programme_pc' ? 'programme' : 'master'
  const roleLabel = role === 'programme_pc' ? 'Programme PC' : 'Master Admin'
  const [filters, setFilters] = useState<FilterState>({
    reportingPeriodId: reportingPeriodId || '',
    programmeCode: 'all',
    postingCode: 'all',
    status: 'all',
    source: 'all',
    dateFrom: '',
    dateTo: '',
    search: '',
  })
  const [debouncedSearch, setDebouncedSearch] = useState(filters.search)
  const [submissions, setSubmissions] = useState<AdminResidentSubmissionListItem[]>([])
  const [summary, setSummary] = useState<AdminResidentSubmissionListSummary>(emptySummary)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [submissionsLoading, setSubmissionsLoading] = useState(true)
  const [isRefetching, setIsRefetching] = useState(false)
  const [isManualRefreshing, setIsManualRefreshing] = useState(false)
  const [submissionsError, setSubmissionsError] = useState<string | null>(null)
  const [postingOptions, setPostingOptions] = useState<PostingCodeOption[]>([])
  const [postingError, setPostingError] = useState<string | null>(null)
  const [programmeOptions, setProgrammeOptions] = useState<Programme[]>([])
  const [programmeError, setProgrammeError] = useState<string | null>(null)
  const [selectedSubmission, setSelectedSubmission] = useState<AdminResidentSubmissionListItem | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<AdminResidentSubmissionDetail | null>(null)
  const [detailError, setDetailError] = useState<{ submissionId: string; message: string } | null>(null)
  const hasLoadedRef = useRef(false)
  const periodSeededRef = useRef(Boolean(reportingPeriodId))
  const detailRequestRef = useRef(0)
  const selectedSubmissionId = searchParams.get('submission_id')?.trim() ?? ''

  const updateFilter = <Key extends keyof FilterState>(
    key: Key,
    value: FilterState[Key],
  ) => {
    setFilters((previous) => ({
      ...previous,
      [key]: value,
    }))
    setOffset(0)
  }

  useEffect(() => {
    if (periodSeededRef.current || !reportingPeriodId) {
      return
    }
    periodSeededRef.current = true
    setFilters((previous) => ({
      ...previous,
      reportingPeriodId,
    }))
  }, [reportingPeriodId])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(filters.search)
    }, searchDebounceMs)
    return () => window.clearTimeout(timer)
  }, [filters.search])

  useEffect(() => {
    let active = true
    ;(async () => {
      setPostingError(null)
      try {
        const response = await listPostingCodes({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
        })
        if (active) {
          setPostingOptions(response)
        }
      } catch (error) {
        if (active) {
          setPostingOptions([])
          setPostingError(error instanceof Error ? error.message : 'Unable to load posting filter options.')
        }
      }
    })()
    return () => {
      active = false
    }
  }, [adminLevel, demoAdminId, demoAdminProgrammes])

  useEffect(() => {
    let active = true
    ;(async () => {
      setProgrammeError(null)
      try {
        const response = await listProgrammes({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
        })
        if (active) {
          setProgrammeOptions(response)
        }
      } catch (error) {
        if (active) {
          setProgrammeOptions([])
          setProgrammeError(error instanceof Error ? error.message : 'Unable to load programme filter options.')
        }
      }
    })()
    return () => {
      active = false
    }
  }, [adminLevel, demoAdminId, demoAdminProgrammes])

  const loadSubmissions = useCallback(async () => {
    return listAdminResidentSubmissions({
      adminId: demoAdminId,
      adminProgrammes: demoAdminProgrammes,
      adminLevel,
      reportingPeriodId: filters.reportingPeriodId,
      programmeCode: filters.programmeCode === 'all' ? undefined : filters.programmeCode,
      postingCode: filters.postingCode === 'all' ? undefined : filters.postingCode,
      status: toStatusParam(filters.status),
      source: toSourceParam(filters.source),
      dateFrom: filters.dateFrom,
      dateTo: filters.dateTo,
      search: debouncedSearch,
      limit: pageSize,
      offset,
    })
  }, [
    adminLevel,
    debouncedSearch,
    demoAdminId,
    demoAdminProgrammes,
    filters.dateFrom,
    filters.dateTo,
    filters.postingCode,
    filters.programmeCode,
    filters.reportingPeriodId,
    filters.source,
    filters.status,
    offset,
  ])

  const fetchSubmissions = useCallback(async (manual = false) => {
    if (manual) {
      setIsManualRefreshing(true)
    } else if (hasLoadedRef.current) {
      setIsRefetching(true)
    } else {
      setSubmissionsLoading(true)
    }
    setSubmissionsError(null)
    try {
      const response = await loadSubmissions()
      setSubmissions(response.items)
      setSummary(response.summary)
      setTotal(response.total)
      hasLoadedRef.current = true
    } catch (error) {
      setSubmissions([])
      setSummary(emptySummary)
      setTotal(0)
      hasLoadedRef.current = true
      setSubmissionsError(error instanceof Error ? error.message : 'Unable to load resident submissions.')
    } finally {
      setSubmissionsLoading(false)
      setIsRefetching(false)
      setIsManualRefreshing(false)
    }
  }, [loadSubmissions])

  useEffect(() => {
    let active = true
    ;(async () => {
      if (!active) {
        return
      }
      await fetchSubmissions(false)
    })()
    return () => {
      active = false
    }
  }, [fetchSubmissions])

  const openDetail = (submission: AdminResidentSubmissionListItem) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('submission_id', submission.id)
    setSearchParams(nextParams, { replace: true })
    setSelectedSubmission(submission)
  }

  const closeDetail = () => {
    detailRequestRef.current += 1
    const nextParams = new URLSearchParams(searchParams)
    nextParams.delete('submission_id')
    setSearchParams(nextParams, { replace: true })
    setSelectedSubmission(null)
    setSelectedDetail(null)
    setDetailError(null)
  }

  useEffect(() => {
    if (!selectedSubmissionId) {
      return
    }

    const requestId = detailRequestRef.current + 1
    detailRequestRef.current = requestId

    ;(async () => {
      try {
        const detail = await getAdminResidentSubmission({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          submissionId: selectedSubmissionId,
        })
        if (detailRequestRef.current === requestId) {
          setSelectedDetail(detail)
          setSelectedSubmission(detail)
        }
      } catch (error) {
        if (detailRequestRef.current === requestId) {
          setDetailError({
            submissionId: selectedSubmissionId,
            message: error instanceof Error ? error.message : 'Unable to load submission detail.',
          })
        }
      }
    })()
  }, [adminLevel, demoAdminId, demoAdminProgrammes, selectedSubmissionId])

  const clearFilters = () => {
    setFilters({
      reportingPeriodId: '',
      programmeCode: 'all',
      postingCode: 'all',
      status: 'all',
      source: 'all',
      dateFrom: '',
      dateTo: '',
      search: '',
    })
    setDebouncedSearch('')
    setOffset(0)
  }

  const hasFilters = Boolean(
    filters.reportingPeriodId ||
      filters.programmeCode !== 'all' ||
      filters.postingCode !== 'all' ||
      filters.status !== 'all' ||
      filters.source !== 'all' ||
      filters.dateFrom ||
      filters.dateTo ||
      filters.search,
  )

  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + submissions.length, total)
  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < total
  const currentDetail = selectedDetail?.id === selectedSubmissionId ? selectedDetail : null
  const currentDetailError =
    detailError?.submissionId === selectedSubmissionId ? detailError.message : null
  const activeDetail =
    currentDetail ?? (selectedSubmission?.id === selectedSubmissionId ? selectedSubmission : null)
  const detailLoading = Boolean(selectedSubmissionId) && !currentDetail && !currentDetailError
  const selectedPeriod = useMemo(
    () => reportingPeriods.find((period) => period.id === filters.reportingPeriodId),
    [filters.reportingPeriodId, reportingPeriods],
  )
  const pageSubtitle = submissionsLoading
    ? `${roleLabel} - NHG resident attendance visibility`
    : `${total} NHG resident submission${total === 1 ? '' : 's'}`

  return (
    <div className="page admin-resident-submissions-page">
      <PageHero
        title="NHG Resident Submissions"
        subtitle={`${roleLabel} - attendance submission visibility`}
        metaInline={[pageSubtitle]}
        actions={
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void fetchSubmissions(true)}
            disabled={isManualRefreshing || submissionsLoading}
          >
            <IconRefresh size={14} />
            {isManualRefreshing ? 'Refreshing' : 'Refresh'}
          </button>
        }
      />

      <section className="card filter-bar admin-resident-submissions-filters">
        <label className="admin-secretary-events-search">
          Search
          <input
            type="search"
            value={filters.search}
            onChange={(event) => updateFilter('search', event.target.value)}
            placeholder="NHG resident, MCR, teaching, posting..."
          />
        </label>
        <label>
          Reporting period
          <select
            value={filters.reportingPeriodId}
            onChange={(event) => updateFilter('reportingPeriodId', event.target.value)}
            disabled={reportingPeriodsLoading}
          >
            <option value="">All periods</option>
            {reportingPeriods.map((period) => (
              <option key={period.id} value={period.id}>
                {period.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Programme
          <select
            value={filters.programmeCode}
            onChange={(event) => updateFilter('programmeCode', event.target.value)}
          >
            <option value="all">All programmes</option>
            {programmeOptions.map((programme) => (
              <option key={programme.code} value={programme.code}>
                {programme.code} - {programme.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Posting
          <select
            value={filters.postingCode}
            onChange={(event) => updateFilter('postingCode', event.target.value)}
          >
            <option value="all">All postings</option>
            {postingOptions.map((posting) => (
              <option key={posting.code} value={posting.code}>
                {posting.displayName ? `${posting.code} - ${posting.displayName}` : posting.code}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={filters.status}
            onChange={(event) => updateFilter('status', event.target.value as StatusFilter)}
          >
            <option value="all">Active submissions</option>
            <option value="submitted">Submitted</option>
            <option value="flagged">Flagged</option>
            <option value="removed">Removed</option>
          </select>
        </label>
        <label>
          Source
          <select
            value={filters.source}
            onChange={(event) => updateFilter('source', event.target.value as SourceFilter)}
          >
            <option value="all">All sources</option>
            <option value="secretary_event">Secretary Event</option>
            <option value="adhoc">Ad-hoc</option>
          </select>
        </label>
        <label>
          Date from
          <input
            type="date"
            value={filters.dateFrom}
            onChange={(event) => updateFilter('dateFrom', event.target.value)}
          />
        </label>
        <label>
          Date to
          <input
            type="date"
            value={filters.dateTo}
            onChange={(event) => updateFilter('dateTo', event.target.value)}
          />
        </label>
        <div className="admin-secretary-events-filter-actions">
          <button type="button" className="button button-ghost" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      </section>

      {reportingPeriodsError ? (
        <section className="inline-callout callout-warning">
          <span>{reportingPeriodsError}</span>
        </section>
      ) : null}
      {programmeError ? (
        <section className="inline-callout callout-warning">
          <span>{programmeError}</span>
        </section>
      ) : null}
      {postingError ? (
        <section className="inline-callout callout-warning">
          <span>{postingError}</span>
        </section>
      ) : null}

      <section className="secretary-event-metrics" aria-label="Resident submission counts">
        <MetricTile label="Submissions" value={summary.totalSubmissions} />
        <MetricTile label="Submitted" value={summary.submittedCount} />
        <MetricTile label="Flagged" value={summary.flaggedCount} />
        <MetricTile label="Ad-hoc" value={summary.adhocCount} />
      </section>

      {submissionsError && submissions.length > 0 ? (
        <section className="inline-callout callout-warning">
          <span>{submissionsError}</span>
        </section>
      ) : null}

      {submissionsLoading ? (
        <section className="card warning-state-card">Loading NHG resident submissions...</section>
      ) : submissionsError && submissions.length === 0 ? (
        <section className="card warning-state-card">
          <strong>NHG resident submissions could not be loaded.</strong>
          <p>{submissionsError}</p>
          <button type="button" className="button button-secondary" onClick={() => void fetchSubmissions(true)}>
            Retry
          </button>
        </section>
      ) : submissions.length === 0 ? (
        <section className="card warning-state-card">
          <strong>{hasFilters ? 'No NHG resident submissions match these filters' : 'No NHG resident submissions yet'}</strong>
          <p>
            {selectedPeriod
              ? `No attendance submissions are visible for ${selectedPeriod.label}.`
              : 'Submitted attendance records will appear here after NHG residents submit attendance.'}
          </p>
        </section>
      ) : (
        <section className={`warning-group-card admin-resident-submissions-table-card ${isRefetching ? 'is-refetching' : ''}`}>
          <div className="warning-group-header">
            <div>
              <span className="warning-group-kicker">Attendance submissions</span>
              <h2>NHG resident attendance records</h2>
            </div>
            <div className="parsed-data-count-status">
              {isRefetching ? <span className="parsed-data-updating">Refreshing...</span> : null}
              <span className="warning-count-pill">
                {firstItem}-{lastItem} of {total}
              </span>
            </div>
          </div>
          <div className="table-scroll">
            <table className="table admin-resident-submissions-table">
              <thead>
                <tr>
                  <th>NHG Resident</th>
                  <th>Teaching</th>
                  <th>Posting</th>
                  <th>Date + time</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>CME / SMC</th>
                  <th>Session Type</th>
                  <th aria-label="Open detail" />
                </tr>
              </thead>
              <tbody>
                {submissions.map((submission) => (
                  <tr
                    key={submission.id}
                    className="table-clickable-row"
                    tabIndex={0}
                    onClick={() => openDetail(submission)}
                    onKeyDown={(keyboardEvent) => {
                      if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') {
                        keyboardEvent.preventDefault()
                        openDetail(submission)
                      }
                    }}
                  >
                    <td>
                      <div className="secretary-event-title-cell">
                        <strong>{submission.residentName}</strong>
                        <span>
                          {submission.mcr} / {submission.programmeCode ?? '-'}
                        </span>
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack">
                        <strong>{submission.teachingName}</strong>
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack admin-resident-submissions-posting">
                        <strong>{submission.postingCode}</strong>
                        <span>{submission.postingDisplayName ?? '-'}</span>
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack admin-resident-submissions-datetime">
                        <strong>{formatDate(submission.eventDate)}</strong>
                        <span>
                          {formatTime(submission.startTime)}–{formatTime(submission.endTime)}
                        </span>
                      </div>
                    </td>
                    <td className="secretary-event-source-cell">
                      <StatusBadge label={submission.source} tone={sourceTone(submission.source)} />
                    </td>
                    <td>
                      <StatusBadge label={submission.status} tone={statusTone(submission.status)} />
                    </td>
                    <td>
                      <div className="secretary-event-badge-stack">
                        <StatusBadge
                          label={submission.cmePointsAwarded ? 'CME awarded' : 'No CME'}
                          tone={submission.cmePointsAwarded ? 'success' : 'neutral'}
                        />
                        {submission.smcEventCode ? (
                          <span className="mono admin-log-compact-text">{submission.smcEventCode}</span>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack admin-resident-submissions-session-type">
                        <strong>{submission.sessionTypeName ?? '-'}</strong>
                        <span>{formatDuration(submission.durationHours)}</span>
                      </div>
                    </td>
                    <td className="cell-chevron">
                      <IconChevRight size={14} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="upload-log-pagination">
            <span>
              Showing {firstItem}-{lastItem} of {total}
            </span>
            <div>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
                disabled={!canGoPrevious}
              >
                Previous
              </button>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setOffset(offset + pageSize)}
                disabled={!canGoNext}
              >
                Next
              </button>
            </div>
          </div>
        </section>
      )}

      <DetailDrawer
        title={activeDetail?.residentName ?? 'Resident submission detail'}
        open={Boolean(selectedSubmissionId)}
        onClose={closeDetail}
      >
        {detailLoading ? (
          <div className="warning-detail">
            <div className="detail-block">
              <h3>Submission metadata</h3>
              <p>Loading bounded submission detail...</p>
            </div>
          </div>
        ) : null}
        {currentDetailError ? (
          <div className="warning-detail">
            <div className="detail-block">
              <h3>Submission metadata</h3>
              <p className="inline-muted">{currentDetailError}</p>
            </div>
          </div>
        ) : null}
        {activeDetail && !currentDetailError ? (
          <div className="warning-detail secretary-event-detail">
            <div className="detail-block">
              <div className="admin-log-detail-heading">
                <StatusBadge label="NHG Resident" tone="info" />
                <StatusBadge label={activeDetail.source} tone={sourceTone(activeDetail.source)} />
                <StatusBadge label={activeDetail.status} tone={statusTone(activeDetail.status)} />
              </div>
              <p>
                {activeDetail.mcr} / {activeDetail.programmeCode ?? '-'} / {formatDate(activeDetail.eventDate)}
              </p>
            </div>

            <div className="detail-block">
              <h3>Attendance record</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="Submission ID" value={activeDetail.id} />
                <DetailField label="Status" value={activeDetail.status} />
                <DetailField label="Submitted at" value={formatDateTime(activeDetail.submittedAt)} />
                <DetailField label="Audit posting copy" value={currentDetail?.attendanceRecord.attendancePostingCode ?? activeDetail.attendancePostingCode} />
                <DetailField label="Created at" value={formatDateTime(currentDetail?.attendanceRecord.createdAt)} />
                <DetailField label="Updated at" value={formatDateTime(currentDetail?.attendanceRecord.updatedAt)} />
              </div>
            </div>

            <div className="detail-block">
              <h3>NHG resident</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="Resident ID" value={currentDetail?.resident.id ?? activeDetail.residentId} />
                <DetailField label="Name" value={currentDetail?.resident.name ?? activeDetail.residentName} />
                <DetailField label="MCR" value={currentDetail?.resident.mcr ?? activeDetail.mcr} />
                <DetailField label="Programme" value={currentDetail?.resident.programmeCode ?? activeDetail.programmeCode} />
                <DetailField label="R year" value={currentDetail?.resident.rYear} />
                <DetailField label="Classification" value={currentDetail?.resident.classification} />
                <DetailField label="Resident status" value={currentDetail?.resident.status} />
              </div>
            </div>

            <div className="detail-block">
              <h3>Teaching event</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="Event ID" value={activeDetail.teachingEventId} />
                <DetailField label="Teaching name" value={activeDetail.teachingName} />
                <DetailField label="Date" value={formatDate(activeDetail.eventDate)} />
                <DetailField label="Start time" value={formatTime(activeDetail.startTime)} />
                <DetailField label="End time" value={formatTime(activeDetail.endTime)} />
                <DetailField label="Duration" value={formatDuration(activeDetail.durationHours)} />
                <DetailField label="Created by role" value={activeDetail.createdByRole} />
                <DetailField label="Source" value={activeDetail.source} />
              </div>
            </div>

            <div className="detail-block">
              <h3>Posting context</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="Event posting code" value={currentDetail?.posting.code ?? activeDetail.postingCode} />
                <DetailField label="Display name" value={currentDetail?.posting.displayName ?? activeDetail.postingDisplayName} />
                <DetailField label="Institution" value={currentDetail?.posting.institution} />
                <DetailField label="Department" value={currentDetail?.posting.department} />
              </div>
            </div>

            <div className="detail-block">
              <h3>CME and display session type</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="CME points awarded" value={activeDetail.cmePointsAwarded} />
                <DetailField label="SMC event code" value={activeDetail.smcEventCode} />
                <DetailField label="Session type display" value={activeDetail.sessionTypeName} />
                <DetailField label="Session type ID" value={activeDetail.sessionTypeId} />
                <DetailField label="Session type authority" value="Display only" />
                <DetailField label="Compliance metrics" value="Not shown in this view" />
              </div>
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
