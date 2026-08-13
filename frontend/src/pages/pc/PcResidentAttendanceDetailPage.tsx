import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import { Link, useParams } from 'react-router'
import {
  getPcResidentAttendance,
  type PcResidentAttendanceHistoryFilters,
  type PcResidentAttendanceHistoryItem,
  type PcResidentAttendanceSourceFilter,
  type PcResidentAttendanceStatus,
  type PcResidentAttendanceSummary,
} from '../../api/pcResidentAttendance'
import { ApiRequestError } from '../../api/http'
import { IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAuth } from '../../context/useAuth'
import { useAppState } from '../../context/useAppState'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'
import {
  attendanceSourceFilterLabel,
  attendanceSourceLabel,
  attendanceSourceTone,
  attendanceStatusFilterLabel,
  attendanceStatusLabel,
  attendanceStatusTone,
  displayAttendancePosting,
  displayCurrentPosting,
  formatAttendanceDate,
  formatAttendanceTimeRange,
  pageRangeLabel,
  pcResidentAttendanceOverviewPath,
} from './pcResidentAttendancePageLogic'

const pageSize = 25

interface HistoryFilterState {
  reportingPeriodId: string
  postingCode: string
  dateFrom: string
  dateTo: string
  source: '' | PcResidentAttendanceSourceFilter
  status: '' | PcResidentAttendanceStatus
}

const emptyFilters: HistoryFilterState = {
  reportingPeriodId: '',
  postingCode: '',
  dateFrom: '',
  dateTo: '',
  source: '',
  status: '',
}

const sourceFilters: PcResidentAttendanceSourceFilter[] = [
  'department_secretary',
  'programme_pc',
  'adhoc',
]

const statusFilters: PcResidentAttendanceStatus[] = ['submitted', 'flagged', 'removed']

const detailErrorMessage = (error: unknown): string => {
  if (error instanceof ApiRequestError && (error.status === 403 || error.status === 404)) {
    return 'This resident attendance history is unavailable or outside your programme scope.'
  }
  return formatUserFacingApiError(error, {
    fallbackMessage: 'Unable to load resident attendance history.',
    authMessage: 'This resident attendance history is unavailable for this account.',
  })
}

export const PcResidentAttendanceDetailPage = () => {
  const { residentId = '' } = useParams<{ residentId: string }>()
  const { identity } = useAuth()
  const {
    demoAdminId,
    reportingPeriodAuthenticationContextVersion,
    reportingPeriods,
    reportingPeriodsLoading,
    reportingPeriodsError,
  } = useAppState()
  const [resident, setResident] = useState<PcResidentAttendanceSummary | null>(null)
  const [attendance, setAttendance] = useState<PcResidentAttendanceHistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [draftFilters, setDraftFilters] = useState<HistoryFilterState>(emptyFilters)
  const [appliedFilters, setAppliedFilters] = useState<HistoryFilterState>(emptyFilters)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loadedViewContextKey, setLoadedViewContextKey] = useState('')
  const requestVersionRef = useRef(0)

  const pcAdminId = identity?.role === 'programme_pc' ? identity.subjectId : demoAdminId
  const programmeScope = useMemo(
    () => identity?.role === 'programme_pc'
      ? [...new Set(identity.programmeScope.map((code) => code.trim()).filter(Boolean))]
      : [],
    [identity],
  )
  const viewContextKey = useMemo(
    () => JSON.stringify([
      reportingPeriodAuthenticationContextVersion,
      identity?.role ?? null,
      identity?.subjectId ?? null,
      programmeScope,
      residentId,
    ]),
    [
      identity,
      programmeScope,
      reportingPeriodAuthenticationContextVersion,
      residentId,
    ],
  )
  const viewContextKeyRef = useRef(viewContextKey)
  useLayoutEffect(() => {
    viewContextKeyRef.current = viewContextKey
  }, [viewContextKey])
  const previousViewContextKeyRef = useRef(viewContextKey)
  const [filtersViewContextKey, setFiltersViewContextKey] = useState(viewContextKey)
  const filtersMatchViewContext = filtersViewContextKey === viewContextKey
  const visibleDraftFilters = filtersMatchViewContext ? draftFilters : emptyFilters
  const effectiveAppliedFilters = filtersMatchViewContext ? appliedFilters : emptyFilters
  const visibleReportingPeriods = filtersMatchViewContext ? reportingPeriods : []
  const contextMatchesLoadedData = loadedViewContextKey === viewContextKey
  const visibleResident = contextMatchesLoadedData ? resident : null
  const visibleAttendance = contextMatchesLoadedData ? attendance : []
  const visibleTotal = contextMatchesLoadedData ? total : 0
  const visibleLoading = loading || !contextMatchesLoadedData

  useEffect(() => {
    if (previousViewContextKeyRef.current === viewContextKey) {
      return
    }
    previousViewContextKeyRef.current = viewContextKey
    requestVersionRef.current += 1
    setLoadedViewContextKey('')
    setFiltersViewContextKey(viewContextKey)
    setResident(null)
    setAttendance([])
    setTotal(0)
    setOffset(0)
    setDraftFilters(emptyFilters)
    setAppliedFilters(emptyFilters)
    setError(null)
    setLoading(true)
  }, [viewContextKey])

  const loadAttendance = useCallback(async () => {
    const requestVersion = requestVersionRef.current + 1
    requestVersionRef.current = requestVersion

    if (!residentId || programmeScope.length === 0) {
      setResident(null)
      setAttendance([])
      setTotal(0)
      setLoadedViewContextKey(viewContextKey)
      setLoading(false)
      setError('This resident attendance history is unavailable for this account.')
      return
    }

    setLoading(true)
    setError(null)
    const filters: PcResidentAttendanceHistoryFilters = {
      reportingPeriodId: effectiveAppliedFilters.reportingPeriodId || undefined,
      postingCode: effectiveAppliedFilters.postingCode || undefined,
      dateFrom: effectiveAppliedFilters.dateFrom || undefined,
      dateTo: effectiveAppliedFilters.dateTo || undefined,
      source: effectiveAppliedFilters.source || undefined,
      status: effectiveAppliedFilters.status || undefined,
      limit: pageSize,
      offset,
    }

    try {
      const response = await getPcResidentAttendance(
        { adminId: pcAdminId, programmeScope },
        residentId,
        filters,
      )
      if (
        requestVersion !== requestVersionRef.current
        || viewContextKey !== viewContextKeyRef.current
      ) {
        return
      }
      setResident(response.resident)
      setAttendance(response.items)
      setTotal(response.total)
      setLoadedViewContextKey(viewContextKey)
    } catch (loadError) {
      if (
        requestVersion !== requestVersionRef.current
        || viewContextKey !== viewContextKeyRef.current
      ) {
        return
      }
      setResident(null)
      setAttendance([])
      setTotal(0)
      setLoadedViewContextKey(viewContextKey)
      setError(detailErrorMessage(loadError))
    } finally {
      if (
        requestVersion === requestVersionRef.current
        && viewContextKey === viewContextKeyRef.current
      ) {
        setLoading(false)
      }
    }
  }, [
    effectiveAppliedFilters,
    offset,
    pcAdminId,
    programmeScope,
    residentId,
    viewContextKey,
  ])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadAttendance()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadAttendance])

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setOffset(0)
    setAppliedFilters({
      ...visibleDraftFilters,
      postingCode: visibleDraftFilters.postingCode.trim(),
    })
  }

  const clearFilters = () => {
    setDraftFilters(emptyFilters)
    setAppliedFilters(emptyFilters)
    setOffset(0)
  }

  const hasAppliedFilters = Object.values(effectiveAppliedFilters).some(Boolean)
  const hasDraftFilters = Object.values(visibleDraftFilters).some(Boolean)
  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < visibleTotal
  const rangeLabel = pageRangeLabel(visibleTotal, offset, visibleAttendance.length)
  const residentSubtitle = visibleResident
    ? `${visibleResident.mcr} / ${visibleResident.programmeCode} / ${visibleResident.rYear ?? 'R year unavailable'} / ${displayCurrentPosting(visibleResident)}`
    : 'Read-only NHG Resident attendance history'

  return (
    <div className="page pc-attendance-page pc-resident-attendance-detail-page">
      <PageHero
        title={visibleResident?.name ?? 'Resident attendance'}
        subtitle={residentSubtitle}
        actions={
          <div className="pc-attendance-hero-actions pc-resident-attendance-hero-actions">
            <Link className="button button-secondary" to={pcResidentAttendanceOverviewPath}>
              Back to NHG Resident Attendance
            </Link>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void loadAttendance()}
              disabled={visibleLoading}
            >
              <IconRefresh size={14} />
              Refresh
            </button>
          </div>
        }
      />

      {visibleLoading && !visibleResident ? (
        <section className="card warning-state-card" aria-live="polite">
          Loading resident attendance history...
        </section>
      ) : null}

      {!visibleLoading && error ? (
        <section className="card warning-state-card" role="alert">
          <strong>Resident attendance history could not be loaded.</strong>
          <p>{error}</p>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void loadAttendance()}
          >
            Retry
          </button>
        </section>
      ) : null}

      {!error && visibleResident ? (
        <>
          <section className="card pc-resident-attendance-summary" aria-label="Resident summary">
            <dl>
              <div><dt>Resident name</dt><dd>{visibleResident.name}</dd></div>
              <div><dt>MCR</dt><dd className="mono">{visibleResident.mcr}</dd></div>
              <div><dt>Programme</dt><dd>{visibleResident.programmeCode}</dd></div>
              <div><dt>R year</dt><dd>{visibleResident.rYear ?? '-'}</dd></div>
              <div><dt>Current posting</dt><dd>{displayCurrentPosting(visibleResident)}</dd></div>
            </dl>
          </section>

          <form className="card filter-bar pc-attendance-filter-card pc-resident-attendance-history-filters" onSubmit={applyFilters}>
            <label>
              Reporting period
              <select
                value={visibleDraftFilters.reportingPeriodId}
                onChange={(event) => setDraftFilters((current) => ({
                  ...current,
                  reportingPeriodId: event.target.value,
                }))}
                disabled={!filtersMatchViewContext || reportingPeriodsLoading}
              >
                <option value="">
                  {reportingPeriodsLoading ? 'Loading reporting periods...' : 'All reporting periods'}
                </option>
                {visibleReportingPeriods.map((period) => (
                  <option key={period.id} value={period.id}>{period.label}</option>
                ))}
              </select>
              {filtersMatchViewContext && reportingPeriodsError ? <small>{reportingPeriodsError}</small> : null}
            </label>
            <label>
              Posting
              <input
                value={visibleDraftFilters.postingCode}
                onChange={(event) => setDraftFilters((current) => ({
                  ...current,
                  postingCode: event.target.value,
                }))}
                placeholder="Posting code"
                disabled={!filtersMatchViewContext}
              />
            </label>
            <label>
              Date from
              <input
                type="date"
                value={visibleDraftFilters.dateFrom}
                onChange={(event) => setDraftFilters((current) => ({
                  ...current,
                  dateFrom: event.target.value,
                }))}
                disabled={!filtersMatchViewContext}
              />
            </label>
            <label>
              Date to
              <input
                type="date"
                value={visibleDraftFilters.dateTo}
                onChange={(event) => setDraftFilters((current) => ({
                  ...current,
                  dateTo: event.target.value,
                }))}
                disabled={!filtersMatchViewContext}
              />
            </label>
            <label>
              Source
              <select
                value={visibleDraftFilters.source}
                onChange={(event) => setDraftFilters((current) => ({
                  ...current,
                  source: event.target.value as HistoryFilterState['source'],
                }))}
                disabled={!filtersMatchViewContext}
              >
                <option value="">All sources</option>
                {sourceFilters.map((source) => (
                  <option key={source} value={source}>{attendanceSourceFilterLabel(source)}</option>
                ))}
              </select>
            </label>
            <label>
              Status
              <select
                value={visibleDraftFilters.status}
                onChange={(event) => setDraftFilters((current) => ({
                  ...current,
                  status: event.target.value as HistoryFilterState['status'],
                }))}
                disabled={!filtersMatchViewContext}
              >
                <option value="">All statuses</option>
                {statusFilters.map((status) => (
                  <option key={status} value={status}>{attendanceStatusFilterLabel(status)}</option>
                ))}
              </select>
            </label>
            <div className="pc-resident-attendance-filter-actions">
              <button
                type="submit"
                className="button button-primary"
                disabled={!filtersMatchViewContext}
              >
                Apply filters
              </button>
              <button
                type="button"
                className="button button-secondary"
                onClick={clearFilters}
                disabled={
                  !filtersMatchViewContext || (!hasAppliedFilters && !hasDraftFilters)
                }
              >
                Clear filters
              </button>
            </div>
          </form>

          {!visibleLoading && visibleAttendance.length === 0 ? (
            <section className="card warning-state-card">
              <strong>No attendance submissions found for this resident.</strong>
            </section>
          ) : null}

          {visibleAttendance.length > 0 ? (
            <section className={`card pc-attendance-table-card pc-resident-attendance-table-card ${visibleLoading ? 'is-refetching' : ''}`}>
              <div className="section-header pc-attendance-list-header pc-resident-attendance-list-header">
                <div>
                  <h2>Attendance history</h2>
                  <p>Read-only native attendance submissions.</p>
                </div>
                <span className="inline-muted">{rangeLabel}</span>
              </div>

              <div className="table-scroll">
                <table className="table pc-resident-attendance-history-table">
                  <thead>
                    <tr>
                      <th>Teaching/session name</th>
                      <th>Date</th>
                      <th>Time</th>
                      <th>Posting</th>
                      <th>Source</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleAttendance.map((row) => (
                      <tr key={row.attendanceId} className={row.status.toLowerCase() === 'removed' ? 'is-removed' : ''}>
                        <td>
                          <strong>{row.teachingName}</strong>
                          {row.detailsOfSession ? <span className="pc-resident-attendance-cell-note">{row.detailsOfSession}</span> : null}
                          {row.submittedDuringLoa ? (
                            <span className="pc-resident-attendance-cell-note">During LOA{row.loaType ? ` - ${row.loaType}` : ''}</span>
                          ) : null}
                        </td>
                        <td className="mono">{formatAttendanceDate(row.eventDate)}</td>
                        <td className="mono">{formatAttendanceTimeRange(row.startTime, row.endTime)}</td>
                        <td>{displayAttendancePosting(row)}</td>
                        <td>
                          <StatusBadge
                            label={attendanceSourceLabel(row.source)}
                            tone={attendanceSourceTone(row.source)}
                          />
                        </td>
                        <td>
                          <StatusBadge
                            label={attendanceStatusLabel(row.status)}
                            tone={attendanceStatusTone(row.status)}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div
                className="responsive-card-list pc-attendance-mobile-list pc-resident-attendance-mobile-list"
                aria-label="Resident attendance history cards"
              >
                {visibleAttendance.map((row) => (
                  <article
                    className={`mobile-record-card pc-attendance-record-card pc-resident-attendance-card ${
                      row.status.toLowerCase() === 'removed' ? 'is-removed' : ''
                    }`}
                    key={row.attendanceId}
                  >
                    <div className="pc-attendance-card-header pc-resident-attendance-card-header">
                      <strong className="safe-wrap">{row.teachingName}</strong>
                      <StatusBadge
                        label={attendanceStatusLabel(row.status)}
                        tone={attendanceStatusTone(row.status)}
                      />
                    </div>
                    {row.detailsOfSession ? (
                      <p className="pc-resident-attendance-card-note">{row.detailsOfSession}</p>
                    ) : null}
                    {row.submittedDuringLoa ? (
                      <p className="pc-resident-attendance-card-note">During LOA{row.loaType ? ` - ${row.loaType}` : ''}</p>
                    ) : null}
                    <dl className="pc-attendance-card-details pc-resident-attendance-card-details">
                      <div><dt>Date</dt><dd>{formatAttendanceDate(row.eventDate)}</dd></div>
                      <div><dt>Time</dt><dd>{formatAttendanceTimeRange(row.startTime, row.endTime)}</dd></div>
                      <div><dt>Posting</dt><dd>{displayAttendancePosting(row)}</dd></div>
                      <div>
                        <dt>Source</dt>
                        <dd>
                          <StatusBadge
                            label={attendanceSourceLabel(row.source)}
                            tone={attendanceSourceTone(row.source)}
                          />
                        </dd>
                      </div>
                    </dl>
                  </article>
                ))}
              </div>

              <div className="upload-log-pagination pc-resident-attendance-pagination">
                <span>{rangeLabel}</span>
                <div>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => setOffset(Math.max(0, offset - pageSize))}
                    disabled={!canGoPrevious || visibleLoading}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => setOffset(offset + pageSize)}
                    disabled={!canGoNext || visibleLoading}
                  >
                    Next
                  </button>
                </div>
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
