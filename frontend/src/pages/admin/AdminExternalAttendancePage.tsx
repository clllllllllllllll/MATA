import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  downloadAdminExternalAttendanceXlsx,
  listAdminExternalAttendance,
  type AdminExternalAttendanceFilters,
  type AdminExternalAttendanceListItem,
} from '../../api/adminExternalAttendance'
import { ApiRequestError } from '../../api/http'
import { IconDownload, IconRefresh, IconX } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'

const pageSize = 50

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

const statusTone = (status?: string): 'success' | 'warning' | 'neutral' => {
  if (status?.toLowerCase() === 'submitted') {
    return 'success'
  }
  if (status?.toLowerCase() === 'flagged') {
    return 'warning'
  }
  return 'neutral'
}

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
  const [total, setTotal] = useState(0)
  const [filters, setFilters] = useState<AdminExternalAttendanceFilters>({ limit: pageSize, offset: 0 })
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)

  const loadRows = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    setExportError(null)
    try {
      const response = await listAdminExternalAttendance(filters)
      setRows(response.items)
      setTotal(response.total)
    } catch (error) {
      setRows([])
      setTotal(0)
      setLoadError(normaliseError(error))
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
    setExportError(null)
    try {
      const blob = await downloadAdminExternalAttendanceXlsx(filters)
      downloadBlob(blob)
    } catch (error) {
      setExportError(normaliseError(error))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="page pc-attendance-page external-attendance-page">
      <PageHero
        title="Non-NHG Attendance"
        subtitle="Forwarding-only attendance records outside NHG compliance, surplus, snapshots, and clawback"
        actions={
          <div className="pc-attendance-hero-actions">
            <button type="button" className="button button-secondary" onClick={() => void loadRows()} disabled={loading}>
              <IconRefresh size={14} />
              Refresh
            </button>
            <button type="button" className="button button-primary" onClick={() => void handleExport()} disabled={exporting}>
              <IconDownload size={14} />
              {exporting ? 'Exporting...' : 'Export XLSX'}
            </button>
          </div>
        }
      />

      {exportError ? (
        <section className="inline-callout callout-error">
          <span>{exportError}</span>
        </section>
      ) : null}

      <section
        className="card filter-bar pc-attendance-filter-card external-attendance-filters"
        aria-label="Non-NHG attendance filters"
      >
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
        <div className="pc-attendance-filter-actions external-attendance-filter-actions">
          <button type="button" className="button button-secondary" onClick={clearFilters}>
            <IconX size={14} />
            Clear filters
          </button>
        </div>
      </section>

      {loading && rows.length === 0 ? (
        <section className="card warning-state-card" aria-live="polite">
          Loading Non-NHG attendance...
        </section>
      ) : null}

      {!loading && loadError ? (
        <section className="card warning-state-card" role="alert">
          <strong>Non-NHG attendance could not be loaded.</strong>
          <p>{loadError}</p>
          <button type="button" className="button button-secondary" onClick={() => void loadRows()}>
            Retry
          </button>
        </section>
      ) : null}

      {!loading && !loadError && rows.length === 0 ? (
        <section className="card warning-state-card">
          <strong>No Non-NHG attendance found.</strong>
        </section>
      ) : null}

      {!loadError && rows.length > 0 ? (
        <section className={`card pc-attendance-table-card external-attendance-table-card ${loading ? 'is-refetching' : ''}`}>
          <div className="section-header pc-attendance-list-header">
            <div>
              <h2>Non-NHG Resident Attendance Records</h2>
              <p>Forwarding/export-only attendance records.</p>
            </div>
            <span className="inline-muted">{total} row(s)</span>
          </div>

          <div className="table-scroll">
              <table className="table external-attendance-table">
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
                      <td>
                        <StatusBadge tone={statusTone(row.status)} label={row.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
          </div>

          <div
            className="responsive-card-list pc-attendance-mobile-list external-attendance-mobile-list"
            aria-label="Non-NHG attendance cards"
          >
            {rows.map((row) => (
              <article className="mobile-record-card pc-attendance-record-card external-attendance-card" key={row.id}>
                <div className="pc-attendance-card-header">
                  <div className="secretary-event-title-cell">
                    <strong>{row.residentName}</strong>
                    <span className="mono">{row.mcr}</span>
                  </div>
                  <StatusBadge tone={statusTone(row.status)} label={row.status} />
                </div>
                <dl className="pc-attendance-card-details">
                  <div><dt>Home cluster</dt><dd>{row.homeCluster}</dd></div>
                  <div><dt>Date</dt><dd>{formatDate(row.eventDate)}</dd></div>
                  <div><dt>Time</dt><dd>{formatTime(row.startTime)}</dd></div>
                  <div><dt>Posting</dt><dd>{row.postingDisplayName ?? row.postingCode}</dd></div>
                  <div><dt>Source</dt><dd><StatusBadge tone={sourceTone(row.source)} label={row.source} /></dd></div>
                </dl>
                <div className="external-attendance-card-teaching">
                  <strong>{row.teachingName}</strong>
                  {row.detailsOfSession ? <span>{row.detailsOfSession}</span> : null}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  )
}
