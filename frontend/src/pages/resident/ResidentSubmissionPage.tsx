import { useCallback, useEffect, useState } from 'react'
import { ApiRequestError } from '../../api/http'
import {
  listResidentAttendanceHistory,
  listResidentEvents,
  submitResidentAdhocTeaching,
  submitResidentAttendance,
  type ResidentAttendanceHistoryRow,
  type ResidentEventsResponse,
} from '../../api/residentSubmissions'
import { PageHero } from '../../components/PageHero'
import { IconCalendar, IconSend } from '../../components/icons'
import { frontendConfig } from '../../config/frontendConfig'

const START_TIME_OPTIONS = Array.from({ length: 24 * 4 }, (_, index) => {
  const totalMinutes = index * 15
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
})

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

const getAttendanceStatusBadgeClass = (status: string) => {
  const normalised = status.trim().toLowerCase()
  if (normalised === 'removed') {
    return 'status-badge-warning'
  }
  if (normalised === 'submitted') {
    return 'status-badge-success'
  }
  return 'status-badge-neutral'
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
  const [eventsResponse, setEventsResponse] = useState<ResidentEventsResponse>({
    events: [],
    reason: null,
    adHocAllowed: false,
    message: null,
    postingCapabilities: [],
  })
  const [eventsLoading, setEventsLoading] = useState(true)
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [selectedEventIds, setSelectedEventIds] = useState<Set<string>>(new Set())

  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')
  const [submitMessage, setSubmitMessage] = useState<string | null>(null)
  const [complianceWarning, setComplianceWarning] = useState<string | null>(null)

  const [adhocDate, setAdhocDate] = useState('')
  const [adhocStartTime, setAdhocStartTime] = useState('')
  const [adhocTeachingName, setAdhocTeachingName] = useState('')
  const [adhocState, setAdhocState] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')
  const [adhocMessage, setAdhocMessage] = useState<string | null>(null)

  const [history, setHistory] = useState<ResidentAttendanceHistoryRow[]>([])
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyUnavailable, setHistoryUnavailable] = useState(false)

  const loadResidentEvents = useCallback(async () => {
    setEventsLoading(true)
    setEventsError(null)
    try {
      const response = await listResidentEvents()
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
      })
    } finally {
      setEventsLoading(false)
    }
  }, [])

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const rows = await listResidentAttendanceHistory()
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

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadResidentEvents()
      void loadHistory()
    }, 0)
    return () => {
      window.clearTimeout(timer)
    }
  }, [loadResidentEvents, loadHistory])

  const selectedCount = selectedEventIds.size
  const availableEvents = eventsResponse.events

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
    if (!adhocDate || !adhocStartTime || !adhocTeachingName.trim()) {
      setAdhocState('error')
      setAdhocMessage('Date, start time, and teaching name are required.')
      return
    }
    setAdhocState('submitting')
    setAdhocMessage(null)
    try {
      const response = await submitResidentAdhocTeaching({
        date: adhocDate,
        startTime: adhocStartTime,
        teachingName: adhocTeachingName.trim(),
      })
      setAdhocState('success')
      setAdhocMessage(`Ad-hoc teaching submitted for ${response.event.postingCode}.`)
      setComplianceWarning(response.complianceWarning ?? null)
      setAdhocDate('')
      setAdhocStartTime('')
      setAdhocTeachingName('')
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

  return (
    <div className="page resident-page">
      <PageHero
        title="Submission Portal"
        subtitle={`${frontendConfig.demoResidentProgramme} - MCR ${frontendConfig.demoResidentMcr}`}
        actions={
          <div className="resident-hero-actions">
            <span className="scope-chip">
              <IconCalendar size={12} />
              NHG Resident
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
        <div className="section-header">
          <h2>Available Scheduled Events</h2>
          <span className="inline-muted">{availableEvents.length} event(s)</span>
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
                    <th>Status</th>
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
                          <span className={`status-badge ${submitted ? 'status-badge-success' : 'status-badge-warning'}`}>
                            {submitted ? 'Submitted' : 'Pending'}
                          </span>
                        </td>
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
                  )}, ${formatTime(event.startTime)} to ${formatTime(event.endTime)}, ${event.postingCode}, ${
                    submitted ? 'Submitted' : 'Pending'
                  }`}
                >
                  <span className="resident-event-card-header">
                    <span className="resident-event-card-title safe-wrap">{event.teachingName}</span>
                    <span className={`status-badge ${submitted ? 'status-badge-success' : 'status-badge-warning'}`}>
                      {submitted ? 'Submitted' : 'Pending'}
                    </span>
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
                      {submitted ? 'Submitted' : selected ? 'Selected' : 'Select'}
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
            <p>
              Please ensure your current submission is not an already scheduled event. There are no CME Pts tagged to
              adhoc teachings.
            </p>
            <p>Availability is checked after you select a teaching date.</p>
          </div>
          <div className="resident-form-grid">
            <label>
              Teaching date
              <input type="date" value={adhocDate} onChange={(event) => setAdhocDate(event.target.value)} />
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
            <label>
              Teaching name
              <input
                type="text"
                value={adhocTeachingName}
                onChange={(event) => setAdhocTeachingName(event.target.value)}
                placeholder="e.g. Journal Club"
              />
              <small>Teaching name must match your posting visibility catalogue.</small>
            </label>
          </div>
          {adhocMessage ? (
            <div className={`inline-callout ${adhocState === 'error' ? 'callout-error' : 'callout-success'}`}>
              <span>{adhocMessage}</span>
            </div>
          ) : null}
          <div className="resident-adhoc-footer">
            <button
              type="button"
              className="button button-resident-submit"
              disabled={adhocState === 'submitting'}
              onClick={() => void handleSubmitAdhoc()}
            >
              {adhocState === 'submitting' ? 'Submitting...' : 'Submit Ad-hoc Teaching'}
            </button>
          </div>
        </article>

        <article className="card resident-history-card">
          <div className="section-header">
            <h2>Recent Submissions</h2>
          </div>
          {historyLoading ? (
            <div className="resident-empty">Loading submission history...</div>
          ) : historyUnavailable ? (
            <div className="resident-empty">
              <p className="resident-empty-title">History endpoint unavailable</p>
              <p>Submission history will appear when the resident attendance-history API is available.</p>
            </div>
          ) : history.length === 0 ? (
            <div className="resident-empty">No past submissions yet.</div>
          ) : (
            <div className="resident-history-list responsive-card-list">
              {history.slice(0, 6).map((row) => {
                const sourceLabel = row.isAdhoc ? 'Ad-hoc' : 'Scheduled'
                return (
                  <div className="resident-history-row mobile-record-card" key={row.attendanceId}>
                    <div className="resident-history-header">
                      <p className="resident-history-title safe-wrap">{row.teachingName}</p>
                      <span className={`status-badge resident-history-status ${getAttendanceStatusBadgeClass(row.status)}`}>
                        {row.status}
                      </span>
                    </div>
                    <div className="resident-history-compact-meta">
                      <span>
                        {formatShortDate(row.eventDate)} | {formatTime(row.startTime)} | {formatDuration(row.durationHours)}
                      </span>
                      <span>
                        <span className="mono">{row.postingCode}</span> | {sourceLabel}
                      </span>
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
