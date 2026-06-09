import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getUploadLog, listUploadLogs } from '../../api/uploadLogs'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'
import type { UploadType } from '../../types/app'
import type { UploadLogDetail, UploadLogListItem, UploadLogStatus } from '../../types/upload'

const uploadTypeLabels: Record<UploadType, string> = {
  rdb: 'RDB Posting Schedule',
  form_f1: 'FormF1',
  ttf: 'Teaching Target File',
  public_holidays: 'Public Holidays / AY Dates',
}

const uploadTypeOrder: UploadType[] = ['rdb', 'form_f1', 'ttf', 'public_holidays']
const statusOptions: UploadLogStatus[] = ['success', 'partial', 'failed']
const pageSize = 10

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
  const { demoAdminId, demoAdminProgrammes } = useAppState()
  const [logs, setLogs] = useState<UploadLogListItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [uploadTypeFilter, setUploadTypeFilter] = useState<UploadType | 'all'>('all')
  const [statusFilter, setStatusFilter] = useState<UploadLogStatus | 'all'>('all')
  const [programmeFilter, setProgrammeFilter] = useState<string>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedLogId, setSelectedLogId] = useState<string | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<UploadLogDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await listUploadLogs({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel: 'master',
        uploadType: uploadTypeFilter,
        status: statusFilter,
        programmeCode: programmeFilter,
        search: searchTerm,
        limit: pageSize,
        offset,
      })
      setLogs(response.items)
      setTotal(response.total)
    } catch (fetchError) {
      setLogs([])
      setTotal(0)
      setError(fetchError instanceof Error ? fetchError.message : 'Unable to load upload logs.')
    } finally {
      setLoading(false)
    }
  }, [
    demoAdminId,
    demoAdminProgrammes,
    offset,
    programmeFilter,
    searchTerm,
    statusFilter,
    uploadTypeFilter,
  ])

  useEffect(() => {
    let active = true
    ;(async () => {
      setLoading(true)
      setError(null)
      try {
        const response = await listUploadLogs({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel: 'master',
          uploadType: uploadTypeFilter,
          status: statusFilter,
          programmeCode: programmeFilter,
          search: searchTerm,
          limit: pageSize,
          offset,
        })
        if (active) {
          setLogs(response.items)
          setTotal(response.total)
        }
      } catch (fetchError) {
        if (active) {
          setLogs([])
          setTotal(0)
          setError(fetchError instanceof Error ? fetchError.message : 'Unable to load upload logs.')
        }
      } finally {
        if (active) {
          setLoading(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [
    demoAdminId,
    demoAdminProgrammes,
    offset,
    programmeFilter,
    searchTerm,
    statusFilter,
    uploadTypeFilter,
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

  const openDetail = async (uploadLogId: string) => {
    setSelectedLogId(uploadLogId)
    setSelectedDetail(null)
    setDetailError(null)
    setDetailLoading(true)
    try {
      const detail = await getUploadLog({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel: 'master',
        uploadLogId,
      })
      setSelectedDetail(detail)
    } catch (fetchError) {
      setDetailError(fetchError instanceof Error ? fetchError.message : 'Unable to load upload log detail.')
    } finally {
      setDetailLoading(false)
    }
  }

  const closeDetail = () => {
    setSelectedLogId(null)
    setSelectedDetail(null)
    setDetailError(null)
    setDetailLoading(false)
  }

  const openRelatedWarnings = () => {
    const uploadType = selectedDetail?.upload_type
    const query = uploadType ? `?mode=history&upload_type=${uploadType}` : '?mode=history'
    navigate(`/admin/upload/warnings${query}`)
  }

  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + logs.length, total)
  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < total

  const pageSubtitle = loading
    ? 'Audit history of uploaded source files'
    : `${total} persisted upload log${total === 1 ? '' : 's'}`

  return (
    <div className="page">
      <PageHero
        title="Upload Logs"
        subtitle="Audit history of uploaded source files"
        metaInline={[pageSubtitle]}
        actions={
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void fetchLogs()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            {loading ? 'Refreshing' : 'Refresh'}
          </button>
        }
      />

      <section className="card filter-bar warning-filter-card upload-log-filter-card">
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

      {loading ? (
        <section className="card warning-state-card">Loading upload logs...</section>
      ) : error ? (
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
        <section className="warning-group-card upload-log-table-card">
          <div className="warning-group-header">
            <div>
              <span className="warning-group-kicker">Audit trail</span>
              <h2>Persisted upload logs</h2>
            </div>
            <span className="warning-count-pill">
              {firstItem}-{lastItem} of {total}
            </span>
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
                    onClick={() => void openDetail(log.id)}
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
        title={selectedDetail ? uploadTypeLabels[selectedDetail.upload_type] : 'Upload log detail'}
        open={Boolean(selectedLogId)}
        onClose={closeDetail}
        footer={
          selectedDetail ? (
            <button type="button" className="button button-primary" onClick={openRelatedWarnings}>
              View related warnings
            </button>
          ) : null
        }
      >
        {detailLoading ? (
          <section className="warning-state-card">Loading upload log detail...</section>
        ) : detailError ? (
          <section className="warning-state-card">
            <strong>Detail could not be loaded.</strong>
            <p>{detailError}</p>
            {selectedLogId ? (
              <button type="button" className="button button-secondary" onClick={() => void openDetail(selectedLogId)}>
                Retry
              </button>
            ) : null}
          </section>
        ) : selectedDetail ? (
          <div className="warning-detail upload-log-detail">
            <div className="detail-block">
              <h3>Upload</h3>
              <p>Type: {uploadTypeLabels[selectedDetail.upload_type]}</p>
              <p>Uploaded: {formatDateTime(selectedDetail.uploaded_at)}</p>
              <p>Uploaded by: {fieldValue(selectedDetail.uploaded_by_name ?? selectedDetail.uploaded_by)}</p>
              <p>Status: {selectedDetail.status}</p>
              <p>Reporting period: {fieldValue(selectedDetail.reporting_period_label ?? selectedDetail.reporting_period_id)}</p>
              <p>Programme: {fieldValue(selectedDetail.programme_code ?? 'Global')}</p>
              <p>Original filename: {fieldValue(selectedDetail.original_filename)}</p>
            </div>
            <div className="detail-block">
              <h3>Counts</h3>
              <p>Warnings: {selectedDetail.warning_count}</p>
              <p>Errors: {selectedDetail.error_count}</p>
              <div className="summary-count-detail-list">
                <SummaryCountChips counts={selectedDetail.summary_counts} maxItems={20} />
              </div>
            </div>
            <div className="detail-block">
              <h3>Raw summary</h3>
              <pre className="raw-json">{JSON.stringify(selectedDetail.summary, null, 2)}</pre>
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
