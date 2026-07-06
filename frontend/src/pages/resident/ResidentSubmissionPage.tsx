import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiRequestError } from '../../api/http'
import {
  getResidentAdhocTeachingOptions,
  listResidentAttendance,
  listResidentEvents,
  removeResidentAttendance,
  submitResidentAdhocTeaching,
  submitResidentAttendance,
  type ResidentAdhocOptionsResponse,
  type ResidentAttendanceHistoryRow,
  type ResidentEventFilters,
  type ResidentEventsResponse,
} from '../../api/residentSubmissions'
import { PageHero } from '../../components/PageHero'
import { IconCalendar, IconRefresh, IconSend, IconX } from '../../components/icons'
import { frontendConfig } from '../../config/frontendConfig'
import { useAuth } from '../../context/useAuth'

const START_TIME_OPTIONS = Array.from({ length: 24 * 4 }, (_, index) => {
  const totalMinutes = index * 15
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
})

const EMPTY_ADHOC_OPTIONS: ResidentAdhocOptionsResponse = {
  date: '',
  teachingDate: '',
  available: false,
  reason: null,
  message: null,
  reportingPeriodId: null,
  postingCode: null,
  postingLabel: null,
  rYear: null,
  attendedPostingOptions: [],
  selectedAttendedPostingCode: null,
  selectedAttendedPostingLabel: null,
  options: [],
}

const formatDate = (value?: string) => {
  if (!value) {
    return '-'
  }
  const dateValue = new Date(value)
  if (!Number.isFinite(dateValue.getTime())) {
    return value
  }
  return dateValue.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const formatShortDate = (value?: string) => {
  if (!value) {
    return '-'
  }
  const dateValue = new Date(value)
  if (!Number.isFinite(dateValue.getTime())) {
    return value
  }
  return dateValue.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  })
}

const formatTime = (value?: string) => {
  if (!value) {
    return '-'
  }
  const parts = value.split(':')
  if (parts.length < 2) {
    return value
  }
  const hours = Number(parts[0])
  const minutes = parts[1]
  if (!Number.isFinite(hours)) {
    return value
  }
  const suffix = hours >= 12 ? 'pm' : 'am'
  const hour12 = hours % 12 || 12
  return `${String(hour12).padStart(2, '0')}:${minutes} ${suffix}`
}

const formatCompactTime = (value?: string) => formatTime(value).replace(/\s+/g, '')

const formatDuration = (value?: number) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '-'
  }
  return `${Number.isInteger(value) ? value : value.toFixed(1)}h`
}

const getEventSessionLabel = (event: ResidentEventsResponse['events'][number]) =>
  event.sessionTypeName ?? event.sessionType ?? '-'

const getEventSourceLabel = (event: ResidentEventsResponse['events'][number]) => {
  if (event.isGlobal) {
    return 'Global Type'
  }
  if (event.isAdhoc) {
    return 'Ad-hoc'
  }
  return 'Scheduled'
}

const normaliseResidentApiError = (error: ApiRequestError): string => {
  if (error.status === 401 || error.status === 403) {
    return 'Resident authentication is invalid. Check demo resident headers.'
  }
  if (error.status === 422) {
    return error.message || 'Validation failed. Please review your submission.'
  }
  if (error.status === 409) {
    return error.message || 'Duplicate submission detected.'
  }
  if (error.isNetworkError) {
    return 'Cannot reach backend API. Verify frontend proxy and backend server are running.'
  }
  return error.message || 'Unexpected API error occurred.'
}

export const ResidentSubmissionPage = () => {
  const { identity } = useAuth()
  const isExternalResident = identity?.role === 'external_resident'
  const [filters, setFilters] = useState<ResidentEventFilters>({})
  const [eventsResponse, setEventsResponse] = useState<ResidentEventsResponse>({
    events: [],
    reason: null,
    adHocAllowed: false,
    message: null,
    postingCapabilities: [],
    filterOptions: {
      postingOptions: [],
      teachingNameOptions: [],
    },
  })
  const [eventsLoading, setEventsLoading] = useState(true)
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [selectedEventIds, setSelectedEventIds] = useState<Set<string>>(new Set())

  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')
  const [submitMessage, setSubmitMessage] = useState<string | null>(null)
  const [complianceWarning, setComplianceWarning] = useState<string | null>(null)

  const [adhocDate, setAdhocDate] = useState('')
  const [adhocOptions, setAdhocOptions] = useState<ResidentAdhocOptionsResponse>(EMPTY_ADHOC_OPTIONS)
  const [adhocOptionsLoading, setAdhocOptionsLoading] = useState(false)
  const [adhocStartTime, setAdhocStartTime] = useState('')
  const [selectedAttendedPostingCode, setSelectedAttendedPostingCode] = useState('')
  const [adhocTeachingName, setAdhocTeachingName] = useState('')
  const [detailsOfSession, setDetailsOfSession] = useState('')
  const [adhocState, setAdhocState] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')
  const [adhocMessage, setAdhocMessage] = useState<string | null>(null)

  const [history, setHistory] = useState<ResidentAttendanceHistoryRow[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyUnavailable, setHistoryUnavailable] = useState(false)

  const loadResidentEvents = useCallback(async () => {
    setEventsLoading(true)
    setEventsError(null)
    try {
      const response = await listResidentEvents(filters)
      setEventsResponse(response)
      setSelectedEventIds(new Set())
    } catch (error) {
      const message =
        error instanceof ApiRequestError
          ? normaliseResidentApiError(error)
          : 'Unable to load resident events right now.'
      setEventsError(message)
      setEventsResponse({
        events: [],
        reason: null,
        adHocAllowed: false,
        message: null,
        postingCapabilities: [],
        filterOptions: {
          postingOptions: [],
          teachingNameOptions: [],
        },
      })
    } finally {
      setEventsLoading(false)
    }
  }, [filters])

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const rows = await listResidentAttendance({ limit: 6, offset: 0 })
      setHistory(rows)
      setHistoryUnavailable(false)
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 404) {
        setHistoryUnavailable(true)
        setHistory([])
      } else {
        setHistoryUnavailable(false)
        setHistory([])
      }
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const loadAdhocOptions = useCallback(async () => {
    if (!adhocDate) {
      setAdhocOptions(EMPTY_ADHOC_OPTIONS)
      setSelectedAttendedPostingCode('')
      setAdhocTeachingName('')
      setAdhocMessage(null)
      return
    }
    setAdhocOptionsLoading(true)
    setAdhocMessage(null)
    try {
      const response = await getResidentAdhocTeachingOptions(adhocDate, selectedAttendedPostingCode || undefined)
      setAdhocOptions(response)
      const responseSelected = response.selectedAttendedPostingCode ?? ''
      if (responseSelected !== selectedAttendedPostingCode) {
        setSelectedAttendedPostingCode(responseSelected)
      }
      setAdhocTeachingName('')
      if (!response.available) {
        setAdhocMessage(response.message ?? 'No ad-hoc teaching options are available for this date.')
      }
    } catch (error) {
      const message =
        error instanceof ApiRequestError
          ? normaliseResidentApiError(error)
          : 'Unable to load ad-hoc options for this date.'
      setAdhocOptions({
        ...EMPTY_ADHOC_OPTIONS,
        date: adhocDate,
        teachingDate: adhocDate,
        attendedPostingOptions: [],
        selectedAttendedPostingCode: null,
        selectedAttendedPostingLabel: null,
        reason:
          error instanceof ApiRequestError &&
          error.status === 422 &&
          String(error.message).toLowerCase().includes('public holiday')
            ? 'public_holiday'
            : null,
        message,
      })
      setAdhocTeachingName('')
      setAdhocState('error')
      setAdhocMessage(message)
    } finally {
      setAdhocOptionsLoading(false)
    }
  }, [adhocDate, selectedAttendedPostingCode])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadResidentEvents()
      void loadHistory()
    }, 0)
    return () => {
      window.clearTimeout(timer)
    }
  }, [loadResidentEvents, loadHistory])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadAdhocOptions()
    }, 0)
    return () => {
      window.clearTimeout(timer)
    }
  }, [loadAdhocOptions])

  const selectedCount = selectedEventIds.size
  const availableEvents = eventsResponse.events
  const filterOptions = eventsResponse.filterOptions
  const attendanceHistoryPath = isExternalResident ? '/external/attendance' : '/resident/attendance'
  const displayedDateFrom = filters.dateFrom ?? filterOptions.dateFrom ?? ''
  const displayedDateTo = filters.dateTo ?? filterOptions.dateTo ?? ''
  const attendedPostingOptions = adhocOptions.attendedPostingOptions
  const selectedAdhocOption = adhocOptions.options.find((option) => option.teachingName === adhocTeachingName)

  const toggleSelected = (eventId: string) => {
    const targetEvent = availableEvents.find((event) => event.id === eventId)
    if (targetEvent?.alreadySubmitted) {
      return
    }
    setSelectedEventIds((previous) => {
      const next = new Set(previous)
      if (next.has(eventId)) {
        next.delete(eventId)
      } else {
        next.add(eventId)
      }
      return next
    })
  }

  const handleSubmitAttendance = async () => {
    if (selectedCount === 0 || submitState === 'submitting') {
      return
    }
    setSubmitState('submitting')
    setSubmitMessage(null)
    try {
      const response = await submitResidentAttendance([...selectedEventIds])
      const submittedIds = new Set(response.submittedEvents.map((event) => event.id))
      setEventsResponse((previous) => ({
        ...previous,
        events: previous.events.filter((event) => !submittedIds.has(event.id)),
      }))
      setSelectedEventIds(new Set())
      setComplianceWarning(response.complianceWarning ?? null)
      setSubmitState('success')
      setSubmitMessage(`${response.submitted} attendance submission(s) recorded.`)
      await loadResidentEvents()
      await loadHistory()
    } catch (error) {
      const message =
        error instanceof ApiRequestError
          ? normaliseResidentApiError(error)
          : 'Unable to submit attendance right now.'
      setSubmitState('error')
      setSubmitMessage(message)
    }
  }

  const handleSubmitAdhoc = async () => {
    if (adhocState === 'submitting') {
      return
    }
    if (!adhocDate || !adhocStartTime || !selectedAttendedPostingCode || !adhocTeachingName || !selectedAdhocOption) {
      setAdhocState('error')
      setAdhocMessage('Date, attended department/programme, teaching/session, and start time are required.')
      return
    }
    setAdhocState('submitting')
    setAdhocMessage(null)
    try {
      const response = await submitResidentAdhocTeaching({
        teachingDate: adhocDate,
        startTime: adhocStartTime,
        teachingName: selectedAdhocOption.teachingName,
        attendedPostingCode: selectedAttendedPostingCode,
        detailsOfSession: detailsOfSession.trim() || undefined,
      })
      setAdhocState('success')
      setAdhocMessage(`Ad-hoc teaching submitted for ${response.event.postingCode}.`)
      setComplianceWarning(response.complianceWarning ?? null)
      setAdhocDate('')
      setAdhocOptions(EMPTY_ADHOC_OPTIONS)
      setAdhocStartTime('')
      setSelectedAttendedPostingCode('')
      setAdhocTeachingName('')
      setDetailsOfSession('')
      await loadResidentEvents()
      await loadHistory()
    } catch (error) {
      const message =
        error instanceof ApiRequestError
          ? normaliseResidentApiError(error)
          : 'Unable to submit ad-hoc teaching right now.'
      setAdhocState('error')
      setAdhocMessage(message)
    }
  }

  const handleDeleteAttendance = async (row: ResidentAttendanceHistoryRow) => {
    if (row.status.toLowerCase() !== 'submitted') {
      return
    }
    const confirmed = window.confirm(`Delete submission for ${row.teachingName}?`)
    if (!confirmed) {
      return
    }
    try {
      await removeResidentAttendance(row.attendanceId)
      await loadResidentEvents()
      await loadHistory()
    } catch (error) {
      const message =
        error instanceof ApiRequestError
          ? normaliseResidentApiError(error)
          : 'Unable to delete submission right now.'
      setSubmitState('error')
      setSubmitMessage(message)
    }
  }

  const updateFilter = (key: keyof ResidentEventFilters, value: string) => {
    setFilters((previous) => ({
      ...previous,
      [key]: value || undefined,
    }))
  }

  const clearFilters = () => {
    setFilters({})
  }

  return (
    <div className="page resident-page">
      <PageHero
        title="Submission Portal"
        subtitle={
          isExternalResident
            ? "Submissions are recorded for home-cluster's records only"
            : `${frontendConfig.demoResidentProgramme} - MCR ${frontendConfig.demoResidentMcr}`
        }
        actions={
          <div className="resident-hero-actions">
            <span className="scope-chip">
              <IconCalendar size={12} />
              {isExternalResident ? 'Non-NHG Resident' : 'NHG Resident'}
            </span>
            <button
              type="button"
              className="button button-resident-submit"
              disabled={selectedCount === 0 || submitState === 'submitting'}
              onClick={() => void handleSubmitAttendance()}
            >
              <IconSend size={14} />
              {submitState === 'submitting' ? 'Submitting...' : `Submit Attendance (${selectedCount})`}
            </button>
          </div>
        }
      />

      {complianceWarning ? (
        <section className="inline-callout callout-warning">
          <span>{complianceWarning}</span>
        </section>
      ) : null}
      {submitMessage ? (
        <section className={`inline-callout ${submitState === 'error' ? 'callout-error' : 'callout-success'}`}>
          <span>{submitMessage}</span>
        </section>
      ) : null}
      {eventsError ? (
        <section className="inline-callout callout-error">
          <span>{eventsError}</span>
        </section>
      ) : null}
      <section className="resident-submit-sticky sticky-action-footer" aria-label="Resident attendance action bar">
        <div className="resident-submit-sticky-copy safe-wrap">
          <strong>{selectedCount} selected</strong>
          <span>{selectedCount === 0 ? 'Select a teaching to submit attendance.' : 'Ready to submit attendance.'}</span>
        </div>
        <button
          type="button"
          className="button button-resident-submit"
          disabled={selectedCount === 0 || submitState === 'submitting'}
          onClick={() => void handleSubmitAttendance()}
        >
          <IconSend size={14} />
          {submitState === 'submitting' ? 'Submitting...' : `Submit Attendance (${selectedCount})`}
        </button>
      </section>

      <section className="card resident-events-card">
        <div className="section-header resident-events-header">
          <div className="resident-section-title">
            <h2>Available Scheduled Events</h2>
            <span className="inline-muted">{availableEvents.length} event(s)</span>
          </div>
          <div className="resident-filter-actions resident-filter-actions-top">
            <button type="button" className="button button-secondary" onClick={clearFilters}>
              <IconX size={14} />
              Clear filters
            </button>
            <button type="button" className="button button-secondary" onClick={() => void loadResidentEvents()}>
              <IconRefresh size={14} />
              Refresh
            </button>
          </div>
        </div>

        <div className="resident-filter-card" aria-label="Scheduled filters">
          <div className="resident-filter-grid">
            <label>
              Start date
              <input type="date" value={displayedDateFrom} onChange={(event) => updateFilter('dateFrom', event.target.value)} />
            </label>
            <label>
              End date
              <input type="date" value={displayedDateTo} onChange={(event) => updateFilter('dateTo', event.target.value)} />
            </label>
            <label>
              Teaching/session name
              <select value={filters.teachingName ?? ''} onChange={(event) => updateFilter('teachingName', event.target.value)}>
                <option value="">All teachings</option>
                {filterOptions.teachingNameOptions.map((option) => (
                  <option key={option.teachingName ?? option.label} value={option.teachingName ?? ''}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Posting
              <select value={filters.postingCode ?? ''} onChange={(event) => updateFilter('postingCode', event.target.value)}>
                <option value="">All postings</option>
                {filterOptions.postingOptions.map((option) => (
                  <option key={option.postingCode ?? option.label} value={option.postingCode ?? ''}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {eventsLoading ? (
          <div className="resident-empty">Loading available events...</div>
        ) : availableEvents.length === 0 ? (
          <div className="resident-empty">
            <p className="resident-empty-title">
              {eventsResponse.reason === 'posting_schedule_unavailable'
                ? 'Posting schedule unavailable'
                : 'No scheduled teaching events available'}
            </p>
            <p>{eventsResponse.message ?? 'Try again later or submit ad-hoc teaching.'}</p>
          </div>
        ) : (
          <div className="table-wrap resident-table-wrap">
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th className="col-check" />
                    <th>Teaching Name</th>
                    <th>Session Type</th>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Posting</th>
                    <th>Tags</th>
                  </tr>
                </thead>
                <tbody>
                  {availableEvents.map((event) => {
                    const selected = selectedEventIds.has(event.id)
                    const sourceLabel = getEventSourceLabel(event)
                    const submitted = event.alreadySubmitted
                    return (
                      <tr
                        key={event.id}
                        className={`table-clickable-row ${selected ? 'resident-row-selected' : ''} ${
                          submitted ? 'resident-row-disabled' : ''
                        }`}
                        onClick={() => toggleSelected(event.id)}
                      >
                        <td>
                          <input
                            type="checkbox"
                            checked={selected}
                            disabled={submitted}
                            onChange={() => toggleSelected(event.id)}
                            onClick={(clickEvent) => clickEvent.stopPropagation()}
                            aria-label={`Select ${event.teachingName}`}
                          />
                        </td>
                        <td className="resident-teaching-name">{event.teachingName}</td>
                        <td>{getEventSessionLabel(event)}</td>
                        <td className="mono">{formatDate(event.eventDate)}</td>
                        <td className="mono">
                          {formatTime(event.startTime)} - {formatTime(event.endTime)}
                        </td>
                        <td className="mono">{event.postingCode}</td>
                        <td>
                          <span className={`status-badge ${event.isGlobal ? 'status-badge-info' : 'status-badge-neutral'}`}>
                            {sourceLabel}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {!eventsLoading && availableEvents.length > 0 ? (
          <div className="resident-event-card-list responsive-card-list" aria-label="Available scheduled events">
            {availableEvents.map((event) => {
              const selected = selectedEventIds.has(event.id)
              const submitted = event.alreadySubmitted
              const sourceLabel = getEventSourceLabel(event)
              const sessionLabel = getEventSessionLabel(event)
              return (
                <button
                  type="button"
                  key={event.id}
                  className={`resident-event-card mobile-record-card ${selected ? 'is-selected' : ''} ${
                    submitted ? 'is-submitted' : ''
                  }`}
                  onClick={() => toggleSelected(event.id)}
                  disabled={submitted}
                  aria-pressed={selected}
                  aria-label={`${selected ? 'Deselect' : 'Select'} ${event.teachingName}, ${formatDate(
                    event.eventDate,
                  )}, ${formatTime(event.startTime)} to ${formatTime(event.endTime)}, ${event.postingCode}`}
                >
                  <span className="resident-event-card-header">
                    <span className="resident-event-card-title safe-wrap">{event.teachingName}</span>
                  </span>
                  <span className="resident-event-card-meta">
                    <span className="resident-event-card-line">
                      {formatDate(event.eventDate)}
                      <span aria-hidden="true"> | </span>
                      {formatCompactTime(event.startTime)}-{formatCompactTime(event.endTime)}
                    </span>
                    <span className="resident-event-card-line mono">{event.postingCode}</span>
                    <span className="resident-event-card-line resident-event-card-type-line">
                      <span className="safe-wrap">{sessionLabel}</span>
                      <span aria-hidden="true"> | </span>
                      <span className="resident-event-source-text">{sourceLabel}</span>
                    </span>
                  </span>
                  <span className="resident-event-card-footer">
                    <span className="resident-card-select-indicator" aria-hidden="true">
                      {submitted ? 'Unavailable' : selected ? 'Selected' : 'Select'}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>
        ) : null}
      </section>

      <section className="grid resident-panels-grid">
        <article className="card resident-adhoc-card">
          <div className="section-header">
            <h2>Ad-hoc Teaching Submission</h2>
            <span className="status-badge status-badge-info">Date-first</span>
          </div>
          <div className="resident-empty resident-adhoc-help">
            <p>Please ensure your current submission is not an already scheduled event. There are no CME Pts tagged to adhoc teachings.</p>
            <p>
              {isExternalResident
                ? "Submissions are recorded for home-cluster's records only and are not included in NHG compliance."
                : 'NHG ad-hoc submissions count as Department/Programme Teaching [1h] under your assigned posting when the target is available.'}
            </p>
          </div>
          <div className="resident-form-grid">
            <label>
              Teaching date
              <input
                type="date"
                value={adhocDate}
                onChange={(event) => {
                  setAdhocDate(event.target.value)
                  setSelectedAttendedPostingCode('')
                  setAdhocTeachingName('')
                }}
              />
            </label>
            <label>
              Derived posting
              <input
                type="text"
                value={adhocOptions.postingLabel ?? adhocOptions.postingCode ?? ''}
                readOnly
                placeholder={adhocDate ? 'Unavailable for selected date' : 'Select a date first'}
              />
            </label>
            <label>
              Attended department/programme
              <select
                value={selectedAttendedPostingCode}
                onChange={(event) => {
                  setSelectedAttendedPostingCode(event.target.value)
                  setAdhocTeachingName('')
                }}
                disabled={!adhocDate || adhocOptionsLoading || attendedPostingOptions.length === 0}
              >
                <option value="">
                  {adhocOptionsLoading ? 'Loading departments...' : 'Select attended department/programme'}
                </option>
                {attendedPostingOptions.map((option) => (
                  <option key={option.postingCode} value={option.postingCode}>
                    {option.label}
                    {option.programmeName ? ` - ${option.programmeName}` : ''}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Teaching/session
              <select
                value={adhocTeachingName}
                onChange={(event) => setAdhocTeachingName(event.target.value)}
                disabled={!adhocOptions.available || adhocOptionsLoading || !selectedAttendedPostingCode}
              >
                <option value="">{adhocOptionsLoading ? 'Loading options...' : 'Select teaching/session'}</option>
                {adhocOptions.options.map((option) => (
                  <option key={`${option.teachingName}-${option.sessionTypeName ?? ''}`} value={option.teachingName}>
                    {option.teachingName} - {option.sessionTypeName ?? option.sessionType ?? formatDuration(option.durationHours)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Start time
              <select value={adhocStartTime} onChange={(event) => setAdhocStartTime(event.target.value)}>
                <option value="">Select start time</option>
                {START_TIME_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="resident-details-field">
              Details of session
              <textarea
                value={detailsOfSession}
                onChange={(event) => setDetailsOfSession(event.target.value)}
                rows={3}
                placeholder="Optional context"
              />
            </label>
          </div>
          {selectedAdhocOption ? (
            <div className="resident-derived-summary">
              <span>{adhocOptions.selectedAttendedPostingLabel ?? selectedAdhocOption.postingLabel}</span>
              <span>{selectedAdhocOption.sessionTypeName ?? selectedAdhocOption.sessionType}</span>
              <span>{formatDuration(selectedAdhocOption.durationHours)}</span>
              <span>{selectedAdhocOption.isGlobal ? 'Global Type' : selectedAdhocOption.isTracked ? 'Tracked' : 'Untracked'}</span>
              <span>
                {isExternalResident
                  ? "Home-cluster's records only - not included in NHG compliance"
                  : 'Counts as Department/Programme Teaching [1h] under assigned posting'}
              </span>
            </div>
          ) : null}
          <div className="resident-adhoc-actions">
            {adhocMessage ? (
              <div className={`inline-callout ${adhocState === 'error' ? 'callout-error' : 'callout-success'}`}>
                <span>{adhocMessage}</span>
              </div>
            ) : null}
            <button
              type="button"
              className="button button-resident-submit"
              disabled={
                adhocState === 'submitting' ||
                !adhocOptions.available ||
                !selectedAttendedPostingCode ||
                !adhocTeachingName ||
                adhocOptions.reason === 'public_holiday'
              }
              onClick={() => void handleSubmitAdhoc()}
            >
              {adhocState === 'submitting' ? 'Submitting...' : 'Submit Ad-hoc Teaching'}
            </button>
          </div>
        </article>

        <article className="card resident-history-card">
          <div className="section-header resident-history-card-header">
            <h2>Recent Submissions</h2>
            <Link className="button button-secondary" to={attendanceHistoryPath}>
              View all past submissions
            </Link>
          </div>
          {historyLoading ? (
            <div className="resident-empty">Loading submission history...</div>
          ) : historyUnavailable ? (
            <div className="resident-empty">
              <p className="resident-empty-title">History endpoint unavailable</p>
              <p>Submission history will appear when the resident attendance API is available.</p>
            </div>
          ) : history.length === 0 ? (
            <div className="resident-empty">No past submissions yet.</div>
          ) : (
            <div className="resident-history-list responsive-card-list">
              {history.slice(0, 6).map((row) => {
                const sourceLabel = row.source === 'adhoc' || row.isAdhoc ? 'Ad-hoc' : 'Scheduled'
                const canDelete = row.status.toLowerCase() === 'submitted'
                return (
                  <div
                    className={`resident-history-row mobile-record-card ${
                      row.status.toLowerCase() === 'removed' ? 'is-removed' : ''
                    }`}
                    key={row.attendanceId}
                  >
                    <div className="resident-history-main">
                      <div className="resident-history-copy">
                        <p className="resident-history-title safe-wrap">{row.teachingName}</p>
                        <div className="resident-history-compact-meta">
                          <span>
                            {formatShortDate(row.eventDate)} | {formatTime(row.startTime)} | {formatDuration(row.durationHours)}
                          </span>
                          <span>
                            <span className="mono">{row.postingCode}</span> | {sourceLabel}
                          </span>
                        </div>
                      </div>
                      <div className="resident-history-side">
                        {canDelete ? (
                          <button
                            type="button"
                            className="button button-danger resident-delete-button"
                            onClick={() => void handleDeleteAttendance(row)}
                          >
                            <IconX size={14} />
                            Delete submission
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </article>
      </section>
    </div>
  )
}
