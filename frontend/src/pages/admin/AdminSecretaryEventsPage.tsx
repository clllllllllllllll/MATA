import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  getAdminSecretaryEvent,
  listAdminSecretaryEvents,
  type AdminSecretaryEventDetail,
  type AdminSecretaryEventListItem,
  type AdminSecretaryEventListSummary,
} from '../../api/adminSecretaryEvents'
import { listPostingCodes, type PostingCodeOption } from '../../api/postingCodes'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'

type AttendanceFilter = 'all' | 'with' | 'without'

interface FilterState {
  reportingPeriodId: string
  postingCode: string
  dateFrom: string
  dateTo: string
  search: string
  hasAttendance: AttendanceFilter
}

const pageSize = 25
const searchDebounceMs = 300

const emptySummary: AdminSecretaryEventListSummary = {
  totalEvents: 0,
  withAttendance: 0,
  withoutAttendance: 0,
  totalAttendanceCount: 0,
  totalExternalAttendanceCount: 0,
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

const compactParts = (parts: Array<string | number | null | undefined>) => {
  const values = parts
    .map((part) => (part === null || part === undefined ? '' : String(part).trim()))
    .filter((part) => part && part !== '-')
  return values.length > 0 ? values.join(' - ') : '-'
}

const fieldValue = (value?: string | number | null) => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  return String(value)
}

const sourceLabel = (event?: Pick<AdminSecretaryEventListItem, 'createdByRole'> | null) =>
  event?.createdByRole ? 'Secretary-created scheduled event' : 'Legacy scheduled secretary event'

const compactSourceLabel = (event: Pick<AdminSecretaryEventListItem, 'createdByRole'>) =>
  event.createdByRole ? 'Secretary-created' : 'Legacy scheduled'

const toAttendanceParam = (value: AttendanceFilter): boolean | null => {
  if (value === 'with') {
    return true
  }
  if (value === 'without') {
    return false
  }
  return null
}

const DetailField = ({
  label,
  value,
}: {
  label: string
  value?: string | number | null
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

export const AdminSecretaryEventsPage = () => {
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
  const [filters, setFilters] = useState<FilterState>({
    reportingPeriodId: reportingPeriodId || '',
    postingCode: 'all',
    dateFrom: '',
    dateTo: '',
    search: '',
    hasAttendance: 'all',
  })
  const [debouncedSearch, setDebouncedSearch] = useState(filters.search)
  const [events, setEvents] = useState<AdminSecretaryEventListItem[]>([])
  const [summary, setSummary] = useState<AdminSecretaryEventListSummary>(emptySummary)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [eventsLoading, setEventsLoading] = useState(true)
  const [isRefetching, setIsRefetching] = useState(false)
  const [isManualRefreshing, setIsManualRefreshing] = useState(false)
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [postingOptions, setPostingOptions] = useState<PostingCodeOption[]>([])
  const [postingError, setPostingError] = useState<string | null>(null)
  const [selectedEvent, setSelectedEvent] = useState<AdminSecretaryEventListItem | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<AdminSecretaryEventDetail | null>(null)
  const [detailError, setDetailError] = useState<{ eventId: string; message: string } | null>(null)
  const hasLoadedRef = useRef(false)
  const periodSeededRef = useRef(Boolean(reportingPeriodId))
  const detailRequestRef = useRef(0)
  const selectedEventId = searchParams.get('event_id')?.trim() ?? ''

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

  const loadEvents = useCallback(async () => {
    return listAdminSecretaryEvents({
      adminId: demoAdminId,
      adminProgrammes: demoAdminProgrammes,
      adminLevel,
      reportingPeriodId: filters.reportingPeriodId,
      postingCode: filters.postingCode === 'all' ? undefined : filters.postingCode,
      dateFrom: filters.dateFrom,
      dateTo: filters.dateTo,
      search: debouncedSearch,
      hasAttendance: toAttendanceParam(filters.hasAttendance),
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
    filters.hasAttendance,
    filters.postingCode,
    filters.reportingPeriodId,
    offset,
  ])

  const fetchEvents = useCallback(async (manual = false) => {
    if (manual) {
      setIsManualRefreshing(true)
    } else if (hasLoadedRef.current) {
      setIsRefetching(true)
    } else {
      setEventsLoading(true)
    }
    setEventsError(null)
    try {
      const response = await loadEvents()
      setEvents(response.items)
      setSummary(response.summary)
      setTotal(response.total)
      hasLoadedRef.current = true
    } catch (error) {
      setEvents([])
      setSummary(emptySummary)
      setTotal(0)
      hasLoadedRef.current = true
      setEventsError(error instanceof Error ? error.message : 'Unable to load secretary events.')
    } finally {
      setEventsLoading(false)
      setIsRefetching(false)
      setIsManualRefreshing(false)
    }
  }, [loadEvents])

  useEffect(() => {
    let active = true
    ;(async () => {
      if (!active) {
        return
      }
      await fetchEvents(false)
    })()
    return () => {
      active = false
    }
  }, [fetchEvents])

  const openDetail = (event: AdminSecretaryEventListItem) => {
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('event_id', event.id)
    setSearchParams(nextParams, { replace: true })
    setSelectedEvent(event)
  }

  const closeDetail = () => {
    detailRequestRef.current += 1
    const nextParams = new URLSearchParams(searchParams)
    nextParams.delete('event_id')
    setSearchParams(nextParams, { replace: true })
    setSelectedEvent(null)
    setSelectedDetail(null)
    setDetailError(null)
  }

  useEffect(() => {
    if (!selectedEventId) {
      return
    }

    const requestId = detailRequestRef.current + 1
    detailRequestRef.current = requestId

    ;(async () => {
      try {
        const detail = await getAdminSecretaryEvent({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          eventId: selectedEventId,
        })
        if (detailRequestRef.current === requestId) {
          setSelectedDetail(detail)
          setSelectedEvent(detail)
        }
      } catch (error) {
        if (detailRequestRef.current === requestId) {
          setDetailError({
            eventId: selectedEventId,
            message: error instanceof Error ? error.message : 'Unable to load event detail.',
          })
        }
      }
    })()
  }, [adminLevel, demoAdminId, demoAdminProgrammes, selectedEventId])

  const clearFilters = () => {
    setFilters({
      reportingPeriodId: '',
      postingCode: 'all',
      dateFrom: '',
      dateTo: '',
      search: '',
      hasAttendance: 'all',
    })
    setDebouncedSearch('')
    setOffset(0)
  }

  const hasFilters =
    filters.reportingPeriodId ||
    filters.postingCode !== 'all' ||
    filters.dateFrom ||
    filters.dateTo ||
    filters.search ||
    filters.hasAttendance !== 'all'

  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + events.length, total)
  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < total
  const currentDetail = selectedDetail?.id === selectedEventId ? selectedDetail : null
  const currentDetailError = detailError?.eventId === selectedEventId ? detailError.message : null
  const activeDetail =
    currentDetail ?? (selectedEvent?.id === selectedEventId ? selectedEvent : null)
  const detailLoading = Boolean(selectedEventId) && !currentDetail && !currentDetailError
  const selectedPeriod = useMemo(
    () => reportingPeriods.find((period) => period.id === filters.reportingPeriodId),
    [filters.reportingPeriodId, reportingPeriods],
  )

  return (
    <div className="page admin-secretary-events-page">
      <PageHero
        title="Secretary Events"
        subtitle="Master Admin - teaching schedule visibility"
        actions={
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void fetchEvents(true)}
            disabled={isManualRefreshing || eventsLoading}
          >
            <IconRefresh size={14} />
            {isManualRefreshing ? 'Refreshing' : 'Refresh'}
          </button>
        }
      />

      <section className="card filter-bar admin-secretary-events-filters">
        <div className="admin-filter-summary">
          <span>Filters</span>
          <strong>{hasFilters ? 'Active filters applied' : 'All secretary events'}</strong>
        </div>
        <label className="admin-secretary-events-search">
          Search
          <input
            type="search"
            value={filters.search}
            onChange={(event) => updateFilter('search', event.target.value)}
            placeholder="Teaching, posting, SMC code..."
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
          Attendance
          <select
            value={filters.hasAttendance}
            onChange={(event) => updateFilter('hasAttendance', event.target.value as AttendanceFilter)}
          >
            <option value="all">All events</option>
            <option value="with">With attendance</option>
            <option value="without">Without attendance</option>
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
      {postingError ? (
        <section className="inline-callout callout-warning">
          <span>{postingError}</span>
        </section>
      ) : null}

      <section className="secretary-event-metrics" aria-label="Secretary event counts">
        <MetricTile label="Events" value={summary.totalEvents} />
        <MetricTile label="With attendance" value={summary.withAttendance} />
        <MetricTile label="NHG attendances" value={summary.totalAttendanceCount} />
        <MetricTile label="Non-NHG attendances" value={summary.totalExternalAttendanceCount} />
      </section>

      {eventsError && events.length > 0 ? (
        <section className="inline-callout callout-warning">
          <span>{eventsError}</span>
        </section>
      ) : null}

      {eventsLoading ? (
        <section className="card warning-state-card">Loading secretary events...</section>
      ) : eventsError && events.length === 0 ? (
        <section className="card warning-state-card">
          <strong>Secretary events could not be loaded.</strong>
          <p>{eventsError}</p>
          <button type="button" className="button button-secondary" onClick={() => void fetchEvents(true)}>
            Retry
          </button>
        </section>
      ) : events.length === 0 ? (
        <section className="card warning-state-card">
          <strong>{hasFilters ? 'No secretary events match these filters' : 'No secretary events yet'}</strong>
          <p>
            {selectedPeriod
              ? `No scheduled secretary-created events are visible for ${selectedPeriod.label}.`
              : 'Scheduled secretary-created events will appear here after secretaries create them.'}
          </p>
        </section>
      ) : (
        <section className={`warning-group-card admin-secretary-events-table-card ${isRefetching ? 'is-refetching' : ''}`}>
          <div className="warning-group-header">
            <div>
              <span className="warning-group-kicker">Teaching schedule</span>
              <h2>Secretary-created scheduled events</h2>
            </div>
            <div className="parsed-data-count-status">
              {isRefetching ? <span className="parsed-data-updating">Refreshing...</span> : null}
              <span className="warning-count-pill">
                {firstItem}-{lastItem} of {total}
              </span>
            </div>
          </div>
          <div className="table-scroll">
            <table className="table admin-secretary-events-table">
              <thead>
                <tr>
                  <th>Teaching</th>
                  <th>Posting</th>
                  <th>Date + time</th>
                  <th>Duration</th>
                  <th>Attendance</th>
                  <th>CME / SMC</th>
                  <th>Session type display</th>
                  <th>Source</th>
                  <th aria-label="Open detail" />
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr
                    key={event.id}
                    className="table-clickable-row"
                    tabIndex={0}
                    onClick={() => openDetail(event)}
                    onKeyDown={(keyboardEvent) => {
                      if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') {
                        keyboardEvent.preventDefault()
                        openDetail(event)
                      }
                    }}
                  >
                    <td>
                      <div className="secretary-event-title-cell">
                        <strong>{event.teachingName}</strong>
                        {event.isRecurring ? <span>Recurring series</span> : null}
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack">
                        <strong>{event.postingCode}</strong>
                        <span>{event.postingDisplayName ?? '-'}</span>
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack">
                        <strong>{formatDate(event.eventDate)}</strong>
                        <span>
                          {formatTime(event.startTime)}-{formatTime(event.endTime)}
                        </span>
                      </div>
                    </td>
                    <td>{formatDuration(event.durationHours)}</td>
                    <td>
                      <div className="secretary-event-stack">
                        <strong>{event.attendanceCount + event.externalAttendanceCount}</strong>
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-badge-stack">
                        <StatusBadge
                          label={event.cmePointsAwarded ? 'CME awarded' : 'No CME'}
                          tone={event.cmePointsAwarded ? 'success' : 'neutral'}
                        />
                        {event.smcEventCode ? (
                          <span className="mono admin-log-compact-text">{event.smcEventCode}</span>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack">
                        <strong>{event.sessionTypeName ?? '-'}</strong>
                      </div>
                    </td>
                    <td className="secretary-event-source-cell">
                      <StatusBadge label={sourceLabel(event)} tone={event.createdByRole ? 'info' : 'warning'} />
                    </td>
                    <td className="cell-chevron">
                      <IconChevRight size={14} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="responsive-card-list admin-mobile-record-list admin-secretary-events-mobile-card-list" aria-label="Secretary event cards">
            {events.map((event) => (
              <button
                key={`${event.id}-mobile`}
                type="button"
                className="mobile-record-card admin-mobile-record-card admin-secretary-events-mobile-card"
                onClick={() => openDetail(event)}
                aria-label={`Open secretary event detail for ${event.teachingName}`}
              >
                <span className="admin-mobile-card-header">
                  <span className="admin-mobile-card-title safe-wrap">{event.teachingName}</span>
                  <StatusBadge
                    label={event.cmePointsAwarded ? 'CME Yes' : 'No CME'}
                    tone={event.cmePointsAwarded ? 'success' : 'neutral'}
                  />
                </span>
                <span className="admin-mobile-card-meta">
                  <span>
                    {compactParts([
                      formatDate(event.eventDate),
                      formatTime(event.startTime),
                      formatDuration(event.durationHours),
                    ])}
                  </span>
                  <span className="admin-mobile-card-source safe-wrap">
                    {compactParts([event.postingCode, compactSourceLabel(event)])}
                  </span>
                  {event.sessionTypeName ? (
                    <span className="safe-wrap">{event.sessionTypeName}</span>
                  ) : null}
                  <span>
                    NHG {event.attendanceCount} - Non-NHG {event.externalAttendanceCount}
                  </span>
                  {event.smcEventCode || event.isRecurring ? (
                    <span className="admin-mobile-card-source safe-wrap">
                      {compactParts([
                        event.smcEventCode ? `SMC ${event.smcEventCode}` : null,
                        event.isRecurring ? 'Recurring series' : null,
                      ])}
                    </span>
                  ) : null}
                </span>
              </button>
            ))}
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
        title={activeDetail?.teachingName ?? 'Secretary event detail'}
        open={Boolean(selectedEventId)}
        onClose={closeDetail}
      >
        {detailLoading ? (
          <div className="warning-detail">
            <div className="detail-block">
              <h3>Event metadata</h3>
              <p>Loading bounded event detail...</p>
            </div>
          </div>
        ) : null}
        {currentDetailError ? (
          <div className="warning-detail">
            <div className="detail-block">
              <h3>Event metadata</h3>
              <p className="inline-muted">{currentDetailError}</p>
            </div>
          </div>
        ) : null}
        {activeDetail && !currentDetailError ? (
          <div className="warning-detail secretary-event-detail">
            <div className="detail-block">
              <div className="admin-log-detail-heading">
                <StatusBadge label={sourceLabel(activeDetail)} tone={activeDetail.createdByRole ? 'info' : 'warning'} />
                <StatusBadge
                  label={activeDetail.hasAttendance ? 'Attendance submitted' : 'No attendance'}
                  tone={activeDetail.hasAttendance ? 'success' : 'neutral'}
                />
                {activeDetail.isRecurring ? <StatusBadge label="Recurring" tone="info" /> : null}
              </div>
              <p>
                {activeDetail.postingCode} / {formatDate(activeDetail.eventDate)} / {formatTime(activeDetail.startTime)}
              </p>
            </div>

            <div className="detail-block">
              <h3>Event metadata</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="Event ID" value={activeDetail.id} />
                <DetailField label="Teaching name" value={activeDetail.teachingName} />
                <DetailField label="Date" value={formatDate(activeDetail.eventDate)} />
                <DetailField label="Start time" value={formatTime(activeDetail.startTime)} />
                <DetailField label="End time" value={formatTime(activeDetail.endTime)} />
                <DetailField label="Duration" value={formatDuration(activeDetail.durationHours)} />
                <DetailField label="Created by role" value={activeDetail.createdByRole ?? 'legacy secretary'} />
                <DetailField label="Created at" value={formatDate(activeDetail.createdAt)} />
              </div>
            </div>

            <div className="detail-block">
              <h3>Posting context</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="Posting code" value={currentDetail?.posting.code ?? activeDetail.postingCode} />
                <DetailField label="Display name" value={currentDetail?.posting.displayName ?? activeDetail.postingDisplayName} />
                <DetailField label="Institution" value={currentDetail?.posting.institution} />
                <DetailField label="Department" value={currentDetail?.posting.department} />
              </div>
            </div>

            <div className="detail-block">
              <h3>Attendance counts</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="NHG attendance" value={currentDetail?.attendanceCounts.native ?? activeDetail.attendanceCount} />
                <DetailField label="Non-NHG attendance" value={currentDetail?.attendanceCounts.external ?? activeDetail.externalAttendanceCount} />
                <DetailField
                  label="Total attendance"
                  value={
                    currentDetail?.attendanceCounts.total ??
                    activeDetail.attendanceCount + activeDetail.externalAttendanceCount
                  }
                />
              </div>
            </div>

            <div className="detail-block">
              <h3>CME and display session type</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="CME points awarded" value={activeDetail.cmePointsAwarded ? 'Yes' : 'No'} />
                <DetailField label="SMC event code" value={activeDetail.smcEventCode} />
                <DetailField label="Session type display" value={activeDetail.sessionTypeName} />
                <DetailField label="Session type id" value={activeDetail.sessionTypeId} />
                <DetailField label="Compliance authority" value="TTF catalogue read-time resolution" />
              </div>
            </div>

            <div className="detail-block">
              <h3>Recurrence</h3>
              {currentDetail?.recurrence ? (
                <div className="parsed-data-detail-grid">
                  <DetailField label="Series ID" value={currentDetail.recurrence.seriesId} />
                  <DetailField label="Pattern" value={currentDetail.recurrence.recurrencePattern} />
                  <DetailField label="Interval" value={currentDetail.recurrence.recurrenceInterval} />
                  <DetailField label="Days" value={currentDetail.recurrence.daysOfWeek.join(', ')} />
                  <DetailField label="End type" value={currentDetail.recurrence.endType} />
                  <DetailField label="End date" value={formatDate(currentDetail.recurrence.endDate)} />
                  <DetailField label="End after count" value={currentDetail.recurrence.endAfterCount} />
                </div>
              ) : (
                <p className="inline-muted">This event is not attached to a recurrence series.</p>
              )}
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
