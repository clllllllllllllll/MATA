import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { listUploadLogs } from '../../api/uploadLogs'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'
import type { UploadType } from '../../types/app'
import type { UploadLogListItem, UploadLogStatus } from '../../types/upload'
import {
  clearMemoryCache,
  getMemoryCache,
  makeScopedCacheKey,
  readThroughMemoryCache,
  setMemoryCache,
  type CacheScope,
} from '../../utils/memoryReadCache'

const uploadTypeLabels: Record<UploadType, string> = {
  rdb: 'RDB Posting Schedule',
  form_f1: 'FormF1',
  ttf: 'Teaching Target File',
  public_holidays: 'Public Holidays / AY Dates',
}

const uploadTypeOrder: UploadType[] = ['rdb', 'form_f1', 'ttf', 'public_holidays']
const statusOptions: UploadLogStatus[] = ['success', 'partial', 'failed']
const pageSize = 10
const searchDebounceMs = 300

const formatDateTime = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : '-'

const fieldValue = (value?: string | number | null) => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  return String(value)
}

const statusTone = (status: UploadLogStatus): 'success' | 'warning' | 'critical' => {
  if (status === 'failed') {
    return 'critical'
  }
  if (status === 'partial') {
    return 'warning'
  }
  return 'success'
}

const countTone = (count: number, kind: 'warning' | 'error') => {
  if (count === 0) {
    return 'count-chip'
  }
  return kind === 'error' ? 'count-chip count-chip-error' : 'count-chip count-chip-warning'
}

const summaryEntries = (counts: Record<string, number>) =>
  Object.entries(counts).filter(([, value]) => Number.isFinite(value))

const SummaryCountChips = ({
  counts,
  maxItems = 4,
}: {
  counts: Record<string, number>
  maxItems?: number
}) => {
  const entries = summaryEntries(counts)
  if (entries.length === 0) {
    return <span className="muted-text">-</span>
  }
  const visibleEntries = entries.slice(0, maxItems)
  const remaining = entries.length - visibleEntries.length
  return (
    <span className="summary-chip-list">
      {visibleEntries.map(([key, value]) => (
        <span key={key} className="summary-count-chip">
          <span>{key}</span>
          <strong>{value}</strong>
        </span>
      ))}
      {remaining > 0 ? <span className="summary-count-more">+{remaining} more</span> : null}
    </span>
  )
}

export const AdminUploadLogsPage = () => {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const initialSearchTerm = searchParams.get('search')?.trim() ?? ''
  const { role, demoAdminId, demoAdminProgrammes } = useAppState()
  const [logs, setLogs] = useState<UploadLogListItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const hasLoadedLogsRef = useRef(false)
  const [isInitialLoading, setIsInitialLoading] = useState(true)
  const [isRefetching, setIsRefetching] = useState(false)
  const [isManualRefreshing, setIsManualRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uploadTypeFilter, setUploadTypeFilter] = useState<UploadType | 'all'>('all')
  const [statusFilter, setStatusFilter] = useState<UploadLogStatus | 'all'>('all')
  const [programmeFilter, setProgrammeFilter] = useState<string>('all')
  const [searchTerm, setSearchTerm] = useState(initialSearchTerm)
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState(initialSearchTerm)
  const [selectedLogId, setSelectedLogId] = useState<string | null>(null)
  const [selectedLog, setSelectedLog] = useState<UploadLogListItem | null>(null)

  const cacheScope = useMemo<CacheScope>(() => ({
    role,
    userId: demoAdminId,
    programmeScope: demoAdminProgrammes,
  }), [demoAdminId, demoAdminProgrammes, role])

  const uploadLogsCacheKey = useCallback((querySearch: string) => makeScopedCacheKey(cacheScope, 'admin.upload-logs.list', {
    uploadType: uploadTypeFilter,
    status: statusFilter,
    programmeCode: programmeFilter,
    search: querySearch,
    limit: pageSize,
    offset,
  }), [cacheScope, offset, programmeFilter, statusFilter, uploadTypeFilter])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearchTerm((previous) => (previous === searchTerm ? previous : searchTerm))
    }, searchDebounceMs)
    return () => window.clearTimeout(timer)
  }, [searchTerm])

  const loadLogs = useCallback(async (querySearch: string) => {
    return listUploadLogs({
      adminId: demoAdminId,
      adminProgrammes: demoAdminProgrammes,
      adminLevel: 'master',
      uploadType: uploadTypeFilter,
      status: statusFilter,
      programmeCode: programmeFilter,
      search: querySearch,
      limit: pageSize,
      offset,
    })
  }, [
    demoAdminId,
    demoAdminProgrammes,
    offset,
    programmeFilter,
    statusFilter,
    uploadTypeFilter,
  ])

  const fetchLogs = useCallback(async () => {
    setIsManualRefreshing(true)
    setError(null)
    try {
      const key = uploadLogsCacheKey(searchTerm)
      clearMemoryCache((cacheKey) => cacheKey === key)
      const response = await loadLogs(searchTerm)
      setMemoryCache(key, response)
      setDebouncedSearchTerm((previous) => (previous === searchTerm ? previous : searchTerm))
      setLogs(response.items)
      setTotal(response.total)
      hasLoadedLogsRef.current = true
    } catch (fetchError) {
      setLogs([])
      setTotal(0)
      hasLoadedLogsRef.current = true
      setError(fetchError instanceof Error ? fetchError.message : 'Unable to load upload logs.')
    } finally {
      setIsManualRefreshing(false)
      setIsInitialLoading(false)
      setIsRefetching(false)
    }
  }, [loadLogs, searchTerm, uploadLogsCacheKey])

  useEffect(() => {
    let active = true
    ;(async () => {
      const key = uploadLogsCacheKey(debouncedSearchTerm)
      const cached = getMemoryCache<Awaited<ReturnType<typeof listUploadLogs>>>(key)
      if (cached) {
        setLogs(cached.data.items)
        setTotal(cached.data.total)
        hasLoadedLogsRef.current = true
        setIsInitialLoading(false)
      }
      const isBackgroundRefetch = hasLoadedLogsRef.current
      if (isBackgroundRefetch) {
        setIsRefetching(true)
      } else {
        setIsInitialLoading(true)
      }
      setError(null)
      try {
        const { data: response } = await readThroughMemoryCache(
          key,
          () => loadLogs(debouncedSearchTerm),
          { force: Boolean(cached) },
        )
        if (active) {
          setLogs(response.items)
          setTotal(response.total)
          hasLoadedLogsRef.current = true
        }
      } catch (fetchError) {
        if (active) {
          if (!isBackgroundRefetch) {
            setLogs([])
            setTotal(0)
          }
          hasLoadedLogsRef.current = true
          setError(fetchError instanceof Error ? fetchError.message : 'Unable to load upload logs.')
        }
      } finally {
        if (active) {
          setIsInitialLoading(false)
          setIsRefetching(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [
    debouncedSearchTerm,
    loadLogs,
    uploadLogsCacheKey,
  ])

  const programmeOptions = useMemo(() => {
    return Array.from(
      new Set(
        [...demoAdminProgrammes, ...logs.map((log) => log.programme_code ?? '')]
          .map((item) => item.trim())
          .filter(Boolean),
      ),
    ).sort()
  }, [demoAdminProgrammes, logs])

  const hasFilters =
    uploadTypeFilter !== 'all' ||
    statusFilter !== 'all' ||
    programmeFilter !== 'all' ||
    searchTerm.trim().length > 0

  const clearFilters = () => {
    setUploadTypeFilter('all')
    setStatusFilter('all')
    setProgrammeFilter('all')
    setSearchTerm('')
    setOffset(0)
  }

  const openDetail = (uploadLog: UploadLogListItem) => {
    setSelectedLogId(uploadLog.id)
    setSelectedLog(uploadLog)
  }

  const closeDetail = () => {
    setSelectedLogId(null)
    setSelectedLog(null)
  }

  const openRelatedWarnings = () => {
    const uploadType = selectedLog?.upload_type
    const params = new URLSearchParams({ mode: 'history' })
    if (uploadType) {
      params.set('upload_type', uploadType)
    }
    if (selectedLog?.reporting_period_id) {
      params.set('reporting_period_id', selectedLog.reporting_period_id)
    }
    if (selectedLog?.programme_code) {
      params.set('programme_code', selectedLog.programme_code)
    }
    const query = `?${params.toString()}`
    navigate(`/admin/upload/warnings${query}`)
  }

  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + logs.length, total)
  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < total

  return (
    <div className="page admin-upload-logs-page">
      <PageHero
        title="Upload Logs"
        subtitle="Audit history of uploaded source files"
        actions={
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void fetchLogs()}
            disabled={isManualRefreshing || isInitialLoading}
          >
            <IconRefresh size={14} />
            {isManualRefreshing ? 'Refreshing' : 'Refresh'}
          </button>
        }
      />

      <section className="card filter-bar warning-filter-card upload-log-filter-card">
        <div className="admin-filter-summary">
          <span>Filters</span>
          <strong>{hasFilters ? 'Active filters applied' : 'All upload logs'}</strong>
        </div>
        <label>
          Upload type
          <select
            value={uploadTypeFilter}
            onChange={(event) => {
              setUploadTypeFilter(event.target.value as UploadType | 'all')
              setOffset(0)
            }}
          >
            <option value="all">All uploads</option>
            {uploadTypeOrder.map((uploadType) => (
              <option key={uploadType} value={uploadType}>
                {uploadTypeLabels[uploadType]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Status
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as UploadLogStatus | 'all')
              setOffset(0)
            }}
          >
            <option value="all">All statuses</option>
            {statusOptions.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label>
          Programme
          <select
            value={programmeFilter}
            onChange={(event) => {
              setProgrammeFilter(event.target.value)
              setOffset(0)
            }}
          >
            <option value="all">All programmes</option>
            {programmeOptions.map((programmeCode) => (
              <option key={programmeCode} value={programmeCode}>
                {programmeCode}
              </option>
            ))}
          </select>
        </label>
        <label>
          Search
          <input
            type="search"
            value={searchTerm}
            onChange={(event) => {
              setSearchTerm(event.target.value)
              setOffset(0)
            }}
            placeholder="Type, status, programme, uploader..."
          />
        </label>
        <button type="button" className="button button-ghost" onClick={clearFilters}>
          Clear filters
        </button>
      </section>

      {error && logs.length > 0 ? (
        <section className="inline-callout callout-warning upload-log-inline-error">
          <span>{error}</span>
        </section>
      ) : null}

      {isInitialLoading ? (
        <section className="card warning-state-card">Loading upload logs...</section>
      ) : error && logs.length === 0 ? (
        <section className="card warning-state-card">
          <strong>Upload logs could not be loaded.</strong>
          <p>{error}</p>
          <button type="button" className="button button-secondary" onClick={() => void fetchLogs()}>
            Retry
          </button>
        </section>
      ) : logs.length === 0 ? (
        <section className="card warning-state-card">
          <strong>{hasFilters ? 'No upload logs match these filters' : 'No upload logs yet'}</strong>
          <p>
            {hasFilters
              ? 'Clear filters or adjust the search to review upload audit history.'
              : 'Upload source files to populate this audit history.'}
          </p>
        </section>
      ) : (
        <section className={`warning-group-card upload-log-table-card ${isRefetching ? 'is-refetching' : ''}`}>
          <div className="warning-group-header">
            <div>
              <span className="warning-group-kicker">Audit trail</span>
              <h2>Persisted upload logs</h2>
            </div>
            <div className="parsed-data-count-status">
              {isRefetching ? <span className="parsed-data-updating">Updating...</span> : null}
              <span className="warning-count-pill">
                {firstItem}-{lastItem} of {total}
              </span>
            </div>
          </div>
          <div className="table-scroll">
            <table className="table upload-logs-table">
              <thead>
                <tr>
                  <th>Upload type</th>
                  <th>Uploaded at</th>
                  <th>Uploaded by</th>
                  <th>Reporting period</th>
                  <th>Programme</th>
                  <th>Status</th>
                  <th>Warnings</th>
                  <th>Errors</th>
                  <th>Summary counts</th>
                  <th aria-label="Open detail" />
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr
                    key={log.id}
                    className="table-clickable-row"
                    tabIndex={0}
                    onClick={() => openDetail(log)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        openDetail(log)
                      }
                    }}
                  >
                    <td>{uploadTypeLabels[log.upload_type]}</td>
                    <td>{formatDateTime(log.uploaded_at)}</td>
                    <td>{fieldValue(log.uploaded_by_name ?? log.uploaded_by)}</td>
                    <td>{fieldValue(log.reporting_period_label ?? log.reporting_period_id)}</td>
                    <td>{fieldValue(log.programme_code ?? 'Global')}</td>
                    <td>
                      <StatusBadge label={log.status} tone={statusTone(log.status)} />
                    </td>
                    <td>
                      <span className={countTone(log.warning_count, 'warning')}>{log.warning_count}</span>
                    </td>
                    <td>
                      <span className={countTone(log.error_count, 'error')}>{log.error_count}</span>
                    </td>
                    <td>
                      <SummaryCountChips counts={log.summary_counts} maxItems={2} />
                    </td>
                    <td className="cell-chevron">
                      <IconChevRight size={14} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="responsive-card-list admin-mobile-record-list upload-log-mobile-card-list" aria-label="Upload log cards">
            {logs.map((log) => (
              <button
                key={`${log.id}-mobile`}
                type="button"
                className="mobile-record-card admin-mobile-record-card upload-log-mobile-card"
                onClick={() => openDetail(log)}
                aria-label={`Open upload log detail for ${uploadTypeLabels[log.upload_type]}`}
              >
                <span className="admin-mobile-card-header">
                  <span className="admin-mobile-card-title safe-wrap">{uploadTypeLabels[log.upload_type]}</span>
                  <StatusBadge label={log.status} tone={statusTone(log.status)} />
                </span>
                <span className="admin-mobile-card-meta">
                  <span>{formatDateTime(log.uploaded_at)} - {fieldValue(log.uploaded_by_name ?? log.uploaded_by)}</span>
                  <span>
                    {fieldValue(log.reporting_period_label ?? log.reporting_period_id)}
                    {' - '}
                    {fieldValue(log.programme_code ?? 'Global')}
                  </span>
                  <span>{log.warning_count} warnings - {log.error_count} errors</span>
                </span>
                <span className="admin-mobile-summary-chips">
                  <SummaryCountChips counts={log.summary_counts} maxItems={2} />
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
        title={selectedLog ? uploadTypeLabels[selectedLog.upload_type] : 'Upload log detail'}
        open={Boolean(selectedLogId)}
        onClose={closeDetail}
        footer={
          selectedLog ? (
            <button type="button" className="button button-primary" onClick={openRelatedWarnings}>
              View related warnings
            </button>
          ) : null
        }
      >
        {selectedLog ? (
          <div className="warning-detail upload-log-detail">
            <div className="detail-block">
              <h3>Upload</h3>
              <p>Type: {uploadTypeLabels[selectedLog.upload_type]}</p>
              <p>Uploaded: {formatDateTime(selectedLog.uploaded_at)}</p>
              <p>Uploaded by: {fieldValue(selectedLog.uploaded_by_name ?? selectedLog.uploaded_by)}</p>
              <p>Status: {selectedLog.status}</p>
              <p>Reporting period: {fieldValue(selectedLog.reporting_period_label ?? selectedLog.reporting_period_id)}</p>
              <p>Programme: {fieldValue(selectedLog.programme_code ?? 'Global')}</p>
            </div>
            <div className="detail-block">
              <h3>Counts</h3>
              <p>Warnings: {selectedLog.warning_count}</p>
              <p>Errors: {selectedLog.error_count}</p>
              <div className="summary-count-detail-list">
                <SummaryCountChips counts={selectedLog.summary_counts} maxItems={20} />
              </div>
            </div>
            <div className="detail-block">
              <h3>Audit summary</h3>
              <p className="inline-muted">
                Raw upload summary is retained for backend audit but hidden from the UI for performance.
              </p>
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
