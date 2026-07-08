import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiRequestError } from '../../api/http'
import {
  listResidentAttendance,
  removeResidentAttendance,
  type ResidentAttendanceFilters,
  type ResidentAttendanceHistoryRow,
} from '../../api/residentSubmissions'
import { PageHero } from '../../components/PageHero'
import { IconRefresh, IconX } from '../../components/icons'
import { useAuth } from '../../context/useAuth'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'

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

const formatDuration = (value?: number) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '-'
  }
  return `${Number.isInteger(value) ? value : value.toFixed(1)}h`
}

const statusClass = (status: string) => {
  if (status.toLowerCase() === 'removed') {
    return 'status-badge-warning'
  }
  if (status.toLowerCase() === 'submitted') {
    return 'status-badge-success'
  }
  return 'status-badge-neutral'
}

const formatAttendanceStatus = (status: string) => {
  const normalised = status.trim().toLowerCase()
  if (normalised === 'submitted') {
    return 'Submitted'
  }
  if (normalised === 'removed') {
    return 'Removed'
  }
  return status
}

const normaliseError = (error: unknown) => {
  if (error instanceof ApiRequestError) {
    return formatUserFacingApiError(error, {
      fallbackMessage: 'Unable to load past submissions.',
    })
  }
  return 'Unable to load past submissions.'
}

export const ResidentAttendancePage = () => {
  const { identity } = useAuth()
  const isExternalResident = identity?.role === 'external_resident'
  const showStatusColumn = !isExternalResident
  const [rows, setRows] = useState<ResidentAttendanceHistoryRow[]>([])
  const [filters, setFilters] = useState<ResidentAttendanceFilters>({ limit: 100, offset: 0 })
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState<string | null>(null)

  const loadRows = useCallback(async () => {
    setLoading(true)
    setMessage(null)
    try {
      const response = await listResidentAttendance(filters)
      setRows(response)
    } catch (error) {
      setRows([])
      setMessage(normaliseError(error))
    } finally {
      setLoading(false)
    }
  }, [filters])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadRows()
    }, 0)
    return () => {
      window.clearTimeout(timer)
    }
  }, [loadRows])

  const postingOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.postingCode).filter(Boolean))).sort(),
    [rows],
  )
  const teachingOptions = useMemo(
    () => Array.from(new Set(rows.map((row) => row.teachingName).filter(Boolean))).sort((a, b) => a.localeCompare(b)),
    [rows],
  )

  const updateFilter = (key: keyof ResidentAttendanceFilters, value: string) => {
    setFilters((previous) => ({
      ...previous,
      [key]: value || undefined,
      offset: 0,
    }))
  }

  const clearFilters = () => {
    setFilters({ limit: 100, offset: 0 })
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
      await loadRows()
    } catch (error) {
      setMessage(normaliseError(error))
    }
  }

  return (
    <div className="page resident-page resident-attendance-page">
      <PageHero
        title="Past Submissions"
        subtitle={
          isExternalResident
            ? 'Non-NHG Resident - Attendance stored for forwarding only, outside NHG compliance'
            : 'NHG Resident - Your submitted teachings'
        }
        actions={
          <button type="button" className="button button-secondary" onClick={() => void loadRows()}>
            <IconRefresh size={14} />
            Refresh
          </button>
        }
      />

      {message ? (
        <section className="inline-callout callout-error">
          <span>{message}</span>
        </section>
      ) : null}

      <section className="card resident-attendance-filter-card filter" aria-label="Past submissions filters">
        <div className="resident-filter-grid">
          <label>
            Start date
            <input type="date" value={filters.dateFrom ?? ''} onChange={(event) => updateFilter('dateFrom', event.target.value)} />
          </label>
          <label>
            End date
            <input type="date" value={filters.dateTo ?? ''} onChange={(event) => updateFilter('dateTo', event.target.value)} />
          </label>
          <label>
            Posting
            <select value={filters.postingCode ?? ''} onChange={(event) => updateFilter('postingCode', event.target.value)}>
              <option value="">All postings</option>
              {postingOptions.map((postingCode) => (
                <option key={postingCode} value={postingCode}>
                  {postingCode}
                </option>
              ))}
            </select>
          </label>
          <label>
            Teaching name
            <select value={filters.teachingName ?? ''} onChange={(event) => updateFilter('teachingName', event.target.value)}>
              <option value="">All teachings</option>
              {teachingOptions.map((teachingName) => (
                <option key={teachingName} value={teachingName}>
                  {teachingName}
                </option>
              ))}
            </select>
          </label>
          <label>
            Source
            <select value={filters.source ?? ''} onChange={(event) => updateFilter('source', event.target.value)}>
              <option value="">All sources</option>
              <option value="scheduled">Scheduled</option>
              <option value="adhoc">Ad-hoc</option>
            </select>
          </label>
          <label>
            Status
            <select value={filters.status ?? ''} onChange={(event) => updateFilter('status', event.target.value)}>
              <option value="">All statuses</option>
              <option value="submitted">Submitted</option>
              <option value="removed">Removed</option>
            </select>
          </label>
        </div>
        <div className="resident-filter-actions">
          <button type="button" className="button button-secondary" onClick={clearFilters}>
            <IconX size={14} />
            Clear filters
          </button>
        </div>
      </section>

      <section className="card resident-attendance-table-card">
        <div className="section-header">
          <h2>Past Submissions</h2>
          <span className="inline-muted">{rows.length} row(s)</span>
        </div>
        {loading ? (
          <div className="resident-empty">Loading past submissions...</div>
        ) : rows.length === 0 ? (
          <div className="resident-empty">No past submissions found.</div>
        ) : (
          <div className="table-wrap resident-table-wrap">
            <div className="table-scroll">
              <table className="table resident-attendance-table">
                <thead>
                  <tr>
                    <th>Teaching Name</th>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Posting</th>
                    <th>Source</th>
                    {showStatusColumn ? <th>Status</th> : null}
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const canDelete = row.status.toLowerCase() === 'submitted'
                    return (
                      <tr key={row.attendanceId} className={row.status.toLowerCase() === 'removed' ? 'resident-row-removed' : ''}>
                        <td className="resident-teaching-name">{row.teachingName}</td>
                        <td className="mono">{formatDate(row.eventDate)}</td>
                        <td className="mono">
                          {formatTime(row.startTime)} - {formatTime(row.endTime)}
                        </td>
                        <td className="mono">{row.postingCode}</td>
                        <td>{row.source === 'adhoc' ? 'Ad-hoc' : 'Scheduled'}</td>
                        {showStatusColumn ? (
                          <td>
                            <span className={`status-badge ${statusClass(row.status)}`}>
                              {formatAttendanceStatus(row.status)}
                            </span>
                          </td>
                        ) : null}
                        <td>
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
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
        {!loading && rows.length > 0 ? (
          <div className="resident-attendance-card-list responsive-card-list">
            {rows.map((row) => {
              const canDelete = row.status.toLowerCase() === 'submitted'
              return (
                <div
                  className={`resident-history-row resident-attendance-card mobile-record-card ${
                    row.status.toLowerCase() === 'removed' ? 'is-removed' : ''
                  }`}
                  key={row.attendanceId}
                >
                  <div className="resident-history-main">
                    <div className="resident-history-copy">
                      <p className="resident-history-title safe-wrap">{row.teachingName}</p>
                      <div className="resident-history-compact-meta">
                        <span>
                          {formatDate(row.eventDate)} | {formatTime(row.startTime)} | {formatDuration(row.durationHours)}
                        </span>
                        <span>
                          <span className="mono">{row.postingCode}</span> | {row.source === 'adhoc' ? 'Ad-hoc' : 'Scheduled'}
                        </span>
                        {row.detailsOfSession ? <span>{row.detailsOfSession}</span> : null}
                      </div>
                    </div>
                    <div className="resident-history-side">
                      {showStatusColumn ? (
                        <span className={`status-badge resident-history-status ${statusClass(row.status)}`}>
                          {formatAttendanceStatus(row.status)}
                        </span>
                      ) : null}
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
        ) : null}
      </section>
    </div>
  )
}
