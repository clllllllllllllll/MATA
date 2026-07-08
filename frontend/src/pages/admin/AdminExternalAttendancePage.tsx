import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  downloadAdminExternalAttendanceXlsx,
  listAdminExternalAttendance,
  type AdminExternalAttendanceFilters,
  type AdminExternalAttendanceListItem,
  type AdminExternalAttendanceSummary,
} from '../../api/adminExternalAttendance'
import { ApiRequestError } from '../../api/http'
import { IconDownload, IconRefresh, IconX } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'

const pageSize = 50

const emptySummary: AdminExternalAttendanceSummary = {
  totalRecords: 0,
  submittedCount: 0,
  flaggedCount: 0,
  removedCount: 0,
  adhocCount: 0,
}

const MetricTile = ({
  label,
  value,
  className = '',
}: {
  label: string
  value: number
  className?: string
}) => (
  <div className={['secretary-event-metric', className].filter(Boolean).join(' ')}>
    <span>{label}</span>
    <strong>{value}</strong>
  </div>
)

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
  const suffix = hours >= 12 ? 'pm' : 'am'
  const hour12 = hours % 12 || 12
  return `${hour12}:${parts[1]} ${suffix}`
}

const sourceTone = (source?: string): 'warning' | 'info' =>
  source?.toLowerCase().includes('ad-hoc') || source?.toLowerCase().includes('adhoc') ? 'warning' : 'info'

const normaliseError = (error: unknown) => {
  if (error instanceof ApiRequestError) {
    return formatUserFacingApiError(error, {
      fallbackMessage: 'Unable to load Non-NHG attendance.',
    })
  }
  return 'Unable to load Non-NHG attendance.'
}

const downloadBlob = (blob: Blob) => {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'non-nhg-attendance.xlsx'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export const AdminExternalAttendancePage = () => {
  const [rows, setRows] = useState<AdminExternalAttendanceListItem[]>([])
  const [summary, setSummary] = useState<AdminExternalAttendanceSummary>(emptySummary)
  const [filters, setFilters] = useState<AdminExternalAttendanceFilters>({ limit: pageSize, offset: 0 })
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const loadRows = useCallback(async () => {
    setLoading(true)
    setMessage(null)
    try {
      const response = await listAdminExternalAttendance(filters)
      setRows(response.items)
      setSummary(response.summary)
    } catch (error) {
      setRows([])
      setSummary(emptySummary)
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

  const updateFilter = (key: keyof AdminExternalAttendanceFilters, value: string) => {
    setFilters((previous) => ({
      ...previous,
      [key]: value || undefined,
      offset: 0,
      limit: pageSize,
    }))
  }

  const clearFilters = () => {
    setFilters({ limit: pageSize, offset: 0 })
  }

  const handleExport = async () => {
    setExporting(true)
    setMessage(null)
    try {
      const blob = await downloadAdminExternalAttendanceXlsx(filters)
      downloadBlob(blob)
    } catch (error) {
      setMessage(normaliseError(error))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="page admin-resident-submissions-page">
      <PageHero
        title="Non-NHG Attendance"
        subtitle="Forwarding-only attendance records outside NHG compliance, surplus, snapshots, and clawback"
        actions={
          <>
            <button type="button" className="button button-secondary" onClick={() => void loadRows()}>
              <IconRefresh size={14} />
              Refresh
            </button>
            <button type="button" className="button button-primary" onClick={() => void handleExport()} disabled={exporting}>
              <IconDownload size={14} />
              {exporting ? 'Exporting...' : 'Export XLSX'}
            </button>
          </>
        }
      />

      {message ? (
        <section className="inline-callout callout-error">
          <span>{message}</span>
        </section>
      ) : null}

      <section
        className="card filter-bar admin-resident-submissions-filters external-attendance-filters"
        aria-label="Non-NHG attendance filters"
      >
        <div className="admin-filter-summary">
          <span>Filters</span>
          <strong>Non-NHG attendance records</strong>
        </div>
        <label>
          Start date
          <input type="date" value={filters.dateFrom ?? ''} onChange={(event) => updateFilter('dateFrom', event.target.value)} />
        </label>
        <label>
          End date
          <input type="date" value={filters.dateTo ?? ''} onChange={(event) => updateFilter('dateTo', event.target.value)} />
        </label>
        <label>
          Home cluster
          <select value={filters.homeCluster ?? ''} onChange={(event) => updateFilter('homeCluster', event.target.value)}>
            <option value="">All clusters</option>
            <option value="NUH">NUH</option>
            <option value="SingHealth">SingHealth</option>
          </select>
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
          MCR
          <input value={filters.mcr ?? ''} onChange={(event) => updateFilter('mcr', event.target.value)} />
        </label>
        <label>
          Status
          <select value={filters.status ?? ''} onChange={(event) => updateFilter('status', event.target.value)}>
            <option value="">Active records</option>
            <option value="submitted">Submitted</option>
            <option value="flagged">Flagged</option>
            <option value="removed">Removed</option>
          </select>
        </label>
        <div className="admin-secretary-events-filter-actions external-attendance-filter-actions">
          <button type="button" className="button button-ghost" onClick={clearFilters}>
            <IconX size={14} />
            Clear filters
          </button>
        </div>
      </section>

      <section
        className="secretary-event-metrics admin-resident-submissions-metrics external-attendance-metrics"
        aria-label="Non-NHG attendance counts"
      >
        <div className="resident-submissions-mobile-summary-card" aria-label="Non-NHG attendance summary">
          <span className="resident-submissions-summary-label">Attendance summary</span>
          <span className="resident-submissions-summary-values">
            <strong>Submitted: {summary.submittedCount}</strong>
            <span>Flagged: {summary.flaggedCount}</span>
            <span>Ad-hoc: {summary.adhocCount}</span>
          </span>
        </div>
        <MetricTile className="resident-submissions-desktop-metric" label="Submitted" value={summary.submittedCount} />
        <MetricTile className="resident-submissions-desktop-metric" label="Flagged" value={summary.flaggedCount} />
        <MetricTile className="resident-submissions-desktop-metric" label="Ad-hoc" value={summary.adhocCount} />
      </section>

      <section className="warning-group-card admin-resident-submissions-table-card external-attendance-table-card">
        <div className="warning-group-header">
          <div>
            <span className="warning-group-kicker">Attendance Submissions</span>
            <h2>Non-NHG Resident Attendance Records</h2>
          </div>
          <span className="warning-count-pill">{rows.length} row(s)</span>
        </div>
        {loading ? (
          <div className="resident-empty">Loading Non-NHG attendance...</div>
        ) : rows.length === 0 ? (
          <div className="resident-empty">No Non-NHG attendance found.</div>
        ) : (
          <div className="table-scroll">
              <table className="table admin-resident-submissions-table external-attendance-table">
                <thead>
                  <tr>
                    <th>Resident</th>
                    <th>Home Cluster</th>
                    <th>Teaching</th>
                    <th>Date</th>
                    <th>Posting</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <div className="secretary-event-title-cell">
                          <strong>{row.residentName}</strong>
                          <span className="mono">{row.mcr}</span>
                        </div>
                      </td>
                      <td><StatusBadge tone="neutral" label={row.homeCluster} /></td>
                      <td>
                        <div className="secretary-event-stack">
                          <strong>{row.teachingName}</strong>
                          {row.detailsOfSession ? <span>{row.detailsOfSession}</span> : null}
                        </div>
                      </td>
                      <td>
                        <div className="secretary-event-stack admin-resident-submissions-datetime">
                          <strong>{formatDate(row.eventDate)}</strong>
                          <span>{formatTime(row.startTime)}</span>
                        </div>
                      </td>
                      <td>
                        <div className="secretary-event-stack admin-resident-submissions-posting">
                          <strong>{row.postingCode}</strong>
                          <span>{row.postingDisplayName ?? '-'}</span>
                        </div>
                      </td>
                      <td className="secretary-event-source-cell">
                        <StatusBadge tone={sourceTone(row.source)} label={row.source} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
          </div>
        )}
      </section>
    </div>
  )
}
