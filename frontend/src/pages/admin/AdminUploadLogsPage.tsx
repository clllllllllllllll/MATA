import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
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
  isMemoryCacheInvalidatedError,
  makeScopedCacheKey,
  readThroughMemoryCache,
} from '../../utils/memoryReadCache'
import {
  captureProtectedAsyncRequestFence,
  isProtectedAsyncRequestFenceCurrent,
} from '../../utils/protectedAsyncFence'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'
import { buildAdminUploadWarningsPath } from './adminUploadPageLogic'

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

const reportingPeriodText = (log: Pick<UploadLogListItem, 'reporting_period_label'>) =>
  log.reporting_period_label || 'Reporting period unavailable'

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
  const { authCacheScope, demoAdminId, demoAdminProgrammes } = useAppState()
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
  const authScopeKey = useMemo(
    () => makeScopedCacheKey(authCacheScope, 'admin.upload-logs.auth-scope', {}),
    [authCacheScope],
  )
  const listRequestRef = useRef(0)

  const uploadLogsCacheKey = useCallback((querySearch: string) => makeScopedCacheKey(authCacheScope, 'admin.upload-logs.list', {
    uploadType: uploadTypeFilter,
    status: statusFilter,
    programmeCode: programmeFilter,
    search: querySearch,
    limit: pageSize,
    offset,
  }), [authCacheScope, offset, programmeFilter, statusFilter, uploadTypeFilter])
  const listRequestContextKey = uploadLogsCacheKey(searchTerm)
  const currentListRequestContextKeyRef = useRef(listRequestContextKey)

  useLayoutEffect(() => {
    currentListRequestContextKeyRef.current = listRequestContextKey
    listRequestRef.current += 1
  }, [listRequestContextKey])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearchTerm((previous) => (previous === searchTerm ? previous : searchTerm))
    }, searchDebounceMs)
    return () => window.clearTimeout(timer)
  }, [searchTerm])

  useEffect(() => {
    let active = true
    queueMicrotask(() => {
      if (!active) {
        return
      }
      hasLoadedLogsRef.current = false
      setLogs([])
      setTotal(0)
      setError(null)
      setSelectedLogId(null)
      setSelectedLog(null)
      setIsManualRefreshing(false)
      setIsRefetching(false)
      setIsInitialLoading(true)
    })
    return () => {
      active = false
    }
  }, [authScopeKey])

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
    const requestId = listRequestRef.current + 1
    listRequestRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(listRequestContextKey, requestId)
    const isCurrentRequest = () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentListRequestContextKeyRef.current,
      listRequestRef.current,
    )
    setIsManualRefreshing(true)
    setError(null)
    try {
      const key = uploadLogsCacheKey(searchTerm)
      clearMemoryCache((cacheKey) => cacheKey === key)
      const { data: response } = await readThroughMemoryCache(
        key,
        () => loadLogs(searchTerm),
        { force: true },
      )
      if (!isCurrentRequest()) {
        return
      }
      setDebouncedSearchTerm((previous) => (previous === searchTerm ? previous : searchTerm))
      setLogs(response.items)
      setTotal(response.total)
      hasLoadedLogsRef.current = true
    } catch (fetchError) {
      if (isMemoryCacheInvalidatedError(fetchError) || !isCurrentRequest()) {
        return
      }
      setLogs([])
      setTotal(0)
      hasLoadedLogsRef.current = true
      setError(formatUserFacingApiError(fetchError, {
        fallbackMessage: 'Unable to load upload logs.',
      }))
    } finally {
      if (isCurrentRequest()) {
        setIsManualRefreshing(false)
        setIsInitialLoading(false)
        setIsRefetching(false)
      }
    }
  }, [listRequestContextKey, loadLogs, searchTerm, uploadLogsCacheKey])

  useEffect(() => {
    let active = true
    ;(async () => {
      if (uploadLogsCacheKey(debouncedSearchTerm) !== listRequestContextKey) {
        return
      }
      const requestId = listRequestRef.current + 1
      listRequestRef.current = requestId
      const requestFence = captureProtectedAsyncRequestFence(listRequestContextKey, requestId)
      const isCurrentRequest = () => active && isProtectedAsyncRequestFenceCurrent(
        requestFence,
        currentListRequestContextKeyRef.current,
        listRequestRef.current,
      )
      const key = uploadLogsCacheKey(debouncedSearchTerm)
      const cached = getMemoryCache<Awaited<ReturnType<typeof listUploadLogs>>>(key)
      if (cached && isCurrentRequest()) {
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
        if (isCurrentRequest()) {
          setLogs(response.items)
          setTotal(response.total)
          hasLoadedLogsRef.current = true
        }
      } catch (fetchError) {
        if (!isMemoryCacheInvalidatedError(fetchError) && isCurrentRequest()) {
          if (!isBackgroundRefetch) {
            setLogs([])
            setTotal(0)
          }
          hasLoadedLogsRef.current = true
          setError(formatUserFacingApiError(fetchError, {
            fallbackMessage: 'Unable to load upload logs.',
          }))
        }
      } finally {
        if (isCurrentRequest()) {
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
    listRequestContextKey,
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
    navigate(buildAdminUploadWarningsPath({
      mode: 'history',
      uploadType: selectedLog?.upload_type,
      reportingPeriodId: selectedLog?.reporting_period_id,
      programmeCode: selectedLog?.programme_code,
    }))
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
                    <td>{reportingPeriodText(log)}</td>
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
                    {reportingPeriodText(log)}
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
              <p>Reporting period: {reportingPeriodText(selectedLog)}</p>
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
                Detailed upload evidence is retained for audit but hidden from this view for performance.
              </p>
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
