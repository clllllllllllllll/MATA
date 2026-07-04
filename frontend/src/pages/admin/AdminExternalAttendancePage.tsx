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

const pageSize = 50

const emptySummary: AdminExternalAttendanceSummary = {
  totalRecords: 0,
  submittedCount: 0,
  flaggedCount: 0,
  removedCount: 0,
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

const statusTone = (status: string): 'success' | 'warning' | 'critical' | 'neutral' => {
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

const normaliseError = (error: unknown) => {
  if (error instanceof ApiRequestError) {
    return error.message || 'Unable to load Non-NHG attendance.'
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

      <section className="grid metrics-grid resident-submissions-metrics">
        <div className="metric-tile">
          <span>Total</span>
          <strong>{summary.totalRecords}</strong>
        </div>
        <div className="metric-tile">
          <span>Submitted</span>
          <strong>{summary.submittedCount}</strong>
        </div>
        <div className="metric-tile">
          <span>Ad-hoc</span>
          <strong>{summary.adhocCount}</strong>
        </div>
      </section>

      <section className="card resident-attendance-filter-card filter" aria-label="Non-NHG attendance filters">
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
        </div>
        <div className="resident-filter-actions">
          <button type="button" className="button button-secondary" onClick={clearFilters}>
            <IconX size={14} />
            Clear filters
          </button>
        </div>
      </section>

      <section className="card">
        <div className="section-header">
          <h2>Attendance Records</h2>
          <span className="inline-muted">{rows.length} row(s)</span>
        </div>
        {loading ? (
          <div className="resident-empty">Loading Non-NHG attendance...</div>
        ) : rows.length === 0 ? (
          <div className="resident-empty">No Non-NHG attendance found.</div>
        ) : (
          <div className="table-wrap resident-table-wrap">
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th>Resident</th>
                    <th>Home Cluster</th>
                    <th>Teaching</th>
                    <th>Date</th>
                    <th>Posting</th>
                    <th>Source</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <strong>{row.residentName}</strong>
                        <div className="inline-muted mono">{row.mcr}</div>
                      </td>
                      <td>{row.homeCluster}</td>
                      <td>
                        <span className="safe-wrap">{row.teachingName}</span>
                        {row.detailsOfSession ? <div className="inline-muted safe-wrap">{row.detailsOfSession}</div> : null}
                      </td>
                      <td className="mono">
                        {formatDate(row.eventDate)}
                        <div>{formatTime(row.startTime)}</div>
                      </td>
                      <td className="mono">{row.postingCode}</td>
                      <td>{row.source}</td>
                      <td>
                        <StatusBadge tone={statusTone(row.status)} label={row.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
