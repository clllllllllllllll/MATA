import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { listUploadWarnings } from '../../api/uploadWarnings'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { useAppState } from '../../context/useAppState'
import type { UploadType } from '../../types/app'
import type { UploadWarning, WarningSeverity } from '../../types/upload'
import {
  clearMemoryCache,
  getMemoryCache,
  makeScopedCacheKey,
  readThroughMemoryCache,
  setMemoryCache,
  type CacheScope,
} from '../../utils/memoryReadCache'

type WarningReviewMode = 'active' | 'history'

const uploadTypeLabels: Record<UploadType, string> = {
  rdb: 'RDB Posting Schedule',
  form_f1: 'FormF1',
  ttf: 'Teaching Target File',
  public_holidays: 'Public Holidays / AY Dates',
}

const uploadTypeOrder: UploadType[] = ['rdb', 'form_f1', 'ttf', 'public_holidays']

const formatDateTime = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : '-'

const reviewLabel = 'Review needed'

const modeDescriptions: Record<WarningReviewMode, string> = {
  active: 'Latest warning state from the most recent upload per source/scope.',
  history: 'Deduped warning history across previous upload logs.',
}

const toWarningMode = (value: string | null): WarningReviewMode => {
  return value === 'history' ? 'history' : 'active'
}

const toUploadTypeFilter = (value: string | null): UploadType | 'all' => {
  if (value === 'rdb' || value === 'ttf' || value === 'form_f1' || value === 'public_holidays') {
    return value
  }
  return 'all'
}

const matchesSearch = (warning: UploadWarning, rawSearch: string): boolean => {
  const search = rawSearch.trim().toLowerCase()
  if (!search) {
    return true
  }
  return [
    warning.warningType,
    warning.residentName,
    warning.mcr,
    warning.programmeCode,
    warning.monthLabel,
    warning.sheetName,
    warning.cellRef,
    warning.message,
    warning.sourceLabel,
    warning.postingCodes.join(' '),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
    .includes(search)
}

const fieldValue = (value?: string | number | null) => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  return String(value)
}

export const AdminWarningsPage = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { demoAdminId, demoAdminProgrammes, role } = useAppState()
  const adminLevel = role === 'master_admin' ? 'master' : 'programme'
  const isProgrammePc = location.pathname.startsWith('/pc') || role === 'programme_pc'
  const [warnings, setWarnings] = useState<UploadWarning[]>([])
  const hasLoadedWarningsRef = useRef(false)
  const [isInitialLoading, setIsInitialLoading] = useState(true)
  const [isRefetching, setIsRefetching] = useState(false)
  const [isManualRefreshing, setIsManualRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedWarning, setSelectedWarning] = useState<UploadWarning | null>(null)
  const [uploadTypeFilter, setUploadTypeFilter] = useState<UploadType | 'all'>(
    toUploadTypeFilter(searchParams.get('upload_type')),
  )
  const [severityFilter, setSeverityFilter] = useState<WarningSeverity | 'all'>('all')
  const [programmeFilter, setProgrammeFilter] = useState<string>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [warningMode, setWarningMode] = useState<WarningReviewMode>(
    toWarningMode(searchParams.get('mode')),
  )

  const cacheScope = useMemo<CacheScope>(() => ({
    role,
    userId: demoAdminId,
    programmeScope: demoAdminProgrammes,
  }), [demoAdminId, demoAdminProgrammes, role])

  const warningCacheKey = useCallback((
    mode: WarningReviewMode,
    uploadType: UploadType | 'all',
    severity: WarningSeverity | 'all',
    programmeCode: string,
    search: string,
  ) => makeScopedCacheKey(cacheScope, 'admin.upload-warnings.list', {
    adminLevel,
    mode,
    uploadType,
    severity,
    programmeCode,
    search: search.trim(),
  }), [adminLevel, cacheScope])

  const loadWarnings = useCallback(() => listUploadWarnings({
    adminId: demoAdminId,
    adminProgrammes: demoAdminProgrammes,
    adminLevel,
    mode: warningMode,
    uploadType: uploadTypeFilter,
    severity: severityFilter,
    programmeCode: programmeFilter,
    search: searchTerm,
  }), [
    adminLevel,
    demoAdminId,
    demoAdminProgrammes,
    programmeFilter,
    searchTerm,
    severityFilter,
    uploadTypeFilter,
    warningMode,
  ])

  const fetchWarnings = useCallback(async () => {
    setIsManualRefreshing(true)
    setIsRefetching(warnings.length > 0)
    setError(null)
    setSelectedWarning(null)
    const key = warningCacheKey(
      warningMode,
      uploadTypeFilter,
      severityFilter,
      programmeFilter,
      searchTerm,
    )
    try {
      clearMemoryCache((cacheKey) => cacheKey === key)
      const rows = await loadWarnings()
      setMemoryCache(key, rows)
      setWarnings(rows)
      hasLoadedWarningsRef.current = true
    } catch (fetchError) {
      if (!hasLoadedWarningsRef.current) {
        setWarnings([])
      }
      hasLoadedWarningsRef.current = true
      setError(fetchError instanceof Error ? fetchError.message : 'Unable to load upload warnings.')
    } finally {
      setIsManualRefreshing(false)
      setIsInitialLoading(false)
      setIsRefetching(false)
    }
  }, [
    loadWarnings,
    programmeFilter,
    searchTerm,
    severityFilter,
    uploadTypeFilter,
    warningCacheKey,
    warningMode,
    warnings.length,
  ])

  useEffect(() => {
    let active = true
    ;(async () => {
      const key = warningCacheKey(
        warningMode,
        uploadTypeFilter,
        severityFilter,
        programmeFilter,
        searchTerm,
      )
      const cached = getMemoryCache<UploadWarning[]>(key)
      if (cached) {
        setWarnings(cached.data)
        hasLoadedWarningsRef.current = true
        setIsInitialLoading(false)
      }

      const isBackgroundRefetch = hasLoadedWarningsRef.current
      if (isBackgroundRefetch) {
        setIsRefetching(true)
      } else {
        setIsInitialLoading(true)
      }
      setError(null)
      try {
        const { data: rows } = await readThroughMemoryCache(
          key,
          loadWarnings,
          { force: Boolean(cached) },
        )
        if (active) {
          setWarnings(rows)
          hasLoadedWarningsRef.current = true
        }
      } catch (fetchError) {
        if (active) {
          if (!isBackgroundRefetch) {
            setWarnings([])
          }
          hasLoadedWarningsRef.current = true
          setError(fetchError instanceof Error ? fetchError.message : 'Unable to load upload warnings.')
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
    loadWarnings,
    programmeFilter,
    searchTerm,
    severityFilter,
    uploadTypeFilter,
    warningCacheKey,
    warningMode,
  ])

  const programmeOptions = useMemo(
    () =>
      Array.from(
        new Set(
          [
            programmeFilter === 'all' ? null : programmeFilter,
            ...warnings.map((warning) => warning.programmeCode),
          ].filter((item): item is string => Boolean(item && item.trim())),
        ),
      ).sort(),
    [programmeFilter, warnings],
  )

  const filteredWarnings = useMemo(() => {
    return warnings.filter((warning) => {
      const byUploadType = uploadTypeFilter === 'all' || warning.uploadType === uploadTypeFilter
      const bySeverity = severityFilter === 'all' || warning.severity === severityFilter
      const byProgramme = programmeFilter === 'all' || warning.programmeCode === programmeFilter
      return byUploadType && bySeverity && byProgramme && matchesSearch(warning, searchTerm)
    })
  }, [programmeFilter, searchTerm, severityFilter, uploadTypeFilter, warnings])

  const groupedWarnings = useMemo(
    () =>
      uploadTypeOrder
        .map((uploadType) => ({
          uploadType,
          warnings: filteredWarnings.filter((warning) => warning.uploadType === uploadType),
        }))
        .filter((group) => group.warnings.length > 0),
    [filteredWarnings],
  )

  const clearFilters = () => {
    setUploadTypeFilter('all')
    setSeverityFilter('all')
    setProgrammeFilter('all')
    setSearchTerm('')
  }

  const openMultiPostingRules = () => {
    const basePath = isProgrammePc ? '/pc/config' : '/admin/config'
    navigate(`${basePath}?section=multi-posting-rules`, {
      state: { configSection: 'multi-posting-rules' },
    })
  }

  const isShowingFirstLoad = isInitialLoading && warnings.length === 0

  const pageSubtitle = isShowingFirstLoad
    ? 'Loading persisted warnings'
    : `${filteredWarnings.length} ${warningMode === 'active' ? 'active ' : 'historical '}warning${filteredWarnings.length === 1 ? '' : 's'} from upload logs`

  return (
    <div className="page">
      <PageHero
        title="Warnings"
        subtitle={pageSubtitle}
        actions={
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void fetchWarnings()}
            disabled={isManualRefreshing || isShowingFirstLoad}
          >
            <IconRefresh size={14} />
            {isManualRefreshing ? 'Refreshing' : 'Refresh'}
          </button>
        }
      />

      <section className="warning-mode-panel">
        <div className="warning-mode-copy">
          <span className="warning-group-kicker">Review mode</span>
          <p>{modeDescriptions[warningMode]}</p>
        </div>
        <div className="warning-mode-toggle" role="tablist" aria-label="Warning review mode">
          <button
            type="button"
            className={warningMode === 'active' ? 'is-active' : ''}
            role="tab"
            aria-selected={warningMode === 'active'}
            onClick={() => setWarningMode('active')}
          >
            Active warnings
          </button>
          <button
            type="button"
            className={warningMode === 'history' ? 'is-active' : ''}
            role="tab"
            aria-selected={warningMode === 'history'}
            onClick={() => setWarningMode('history')}
          >
            History
          </button>
        </div>
      </section>

      {warningMode === 'history' ? (
        <section className="warning-history-banner">
          History mode shows warnings from previous uploads. These may have been superseded by newer uploads and are shown for audit review only.
        </section>
      ) : null}

      <section className="card filter-bar warning-filter-card">
        <label>
          Upload type
          <select value={uploadTypeFilter} onChange={(event) => setUploadTypeFilter(event.target.value as UploadType | 'all')}>
            <option value="all">All uploads</option>
            {uploadTypeOrder.map((uploadType) => (
              <option key={uploadType} value={uploadType}>
                {uploadTypeLabels[uploadType]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Severity
          <select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value as WarningSeverity | 'all')}>
            <option value="all">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </label>
        <label>
          Programme
          <select value={programmeFilter} onChange={(event) => setProgrammeFilter(event.target.value)}>
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
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="Type, resident, MCR, source, message..."
          />
        </label>
        <button type="button" className="button button-ghost" onClick={clearFilters}>
          Clear filters
        </button>
      </section>

      <section className={`warning-results-card ${isRefetching ? 'is-refetching' : ''}`}>
        <div className="warning-results-header">
          <div>
            <span className="warning-group-kicker">Persisted upload warnings</span>
            <h2>{warningMode === 'active' ? 'Active warnings' : 'Warning history'}</h2>
          </div>
          <div className="parsed-data-count-status">
            {isRefetching ? <span className="parsed-data-updating">Refreshing...</span> : null}
            <span className="warning-count-pill">
              {filteredWarnings.length} warning{filteredWarnings.length === 1 ? '' : 's'}
            </span>
          </div>
        </div>
        {isShowingFirstLoad ? (
          <div className="warning-state-card warning-results-state">Loading persisted upload warnings...</div>
        ) : error && warnings.length === 0 ? (
          <div className="warning-state-card warning-results-state">
            <strong>Warnings could not be loaded.</strong>
            <p>{error}</p>
            <button type="button" className="button button-secondary" onClick={() => void fetchWarnings()}>
              Retry
            </button>
          </div>
        ) : warnings.length === 0 ? (
          <div className="warning-state-card warning-results-state">
            <strong>No persisted warnings found.</strong>
            <p>Upload warnings will appear here after parser summaries are written to upload logs.</p>
          </div>
        ) : groupedWarnings.length === 0 ? (
          <div className="warning-state-card warning-results-state">
            <strong>No warnings match the selected filters.</strong>
            <p>Clear filters or adjust the search to review persisted upload warnings.</p>
          </div>
        ) : (
          <div className="warning-groups warning-groups-in-card">
          {groupedWarnings.map((group) => (
            <section key={group.uploadType} className="warning-group-card">
              <div className="warning-group-header">
                <div>
                  <span className="warning-group-kicker">Upload source</span>
                  <h2>{uploadTypeLabels[group.uploadType]}</h2>
                </div>
                <span className="warning-count-pill">
                  {group.warnings.length} warning{group.warnings.length === 1 ? '' : 's'}
                </span>
              </div>
              <div className="table-scroll">
                <table className="table grouped-warnings-table">
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>Resident</th>
                      <th>MCR</th>
                      <th>Programme</th>
                      <th>Month</th>
                      <th>Source</th>
                      <th>Status</th>
                      <th aria-label="Open detail" />
                    </tr>
                  </thead>
                  <tbody>
                    {group.warnings.map((warning) => (
                      <tr
                        key={warning.warningId}
                        className="table-clickable-row"
                        onClick={() => setSelectedWarning(warning)}
                      >
                        <td className="cell-type">
                          <span className={`severity-dot severity-dot-${warning.severity}`} />
                          <span className="mono-chip">{warning.warningType}</span>
                        </td>
                        <td>{fieldValue(warning.residentName)}</td>
                        <td className="mono-cell">{fieldValue(warning.mcr)}</td>
                        <td>{fieldValue(warning.programmeCode)}</td>
                        <td>{fieldValue(warning.monthLabel)}</td>
                        <td className="mono-cell">{fieldValue(warning.sourceLabel)}</td>
                        <td>
                          <span className="warning-status-stack">
                            <span className="review-marker">{reviewLabel}</span>
                            {warning.seenCount > 1 ? (
                              <span className="warning-seen-pill">Seen in {warning.seenCount} uploads</span>
                            ) : null}
                          </span>
                        </td>
                        <td className="cell-chevron">
                          <IconChevRight size={14} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
          </div>
        )}
      </section>

      <DetailDrawer
        title={selectedWarning ? selectedWarning.warningType : 'Warning detail'}
        open={Boolean(selectedWarning)}
        onClose={() => setSelectedWarning(null)}
        footer={
          selectedWarning?.warningType === 'unmatched_multi_posting' ? (
            <button type="button" className="button button-primary" onClick={openMultiPostingRules}>
              Open Multi-Posting Rules
            </button>
          ) : null
        }
      >
        {selectedWarning ? (
          <div className="warning-detail">
            <div className="detail-block">
              <h3>Summary</h3>
              <p>{selectedWarning.message}</p>
              <p>
                <span className={`severity-dot severity-dot-${selectedWarning.severity}`} />
                {selectedWarning.severity} - {reviewLabel}
              </p>
            </div>
            <div className="detail-block">
              <h3>Upload</h3>
              <p>Source: {uploadTypeLabels[selectedWarning.uploadType]}</p>
              <p>Latest upload: {formatDateTime(selectedWarning.uploadedAt)}</p>
              <p>First seen: {formatDateTime(selectedWarning.firstSeenAt)}</p>
              <p>Last seen: {formatDateTime(selectedWarning.lastSeenAt)}</p>
              <p>Seen count: {selectedWarning.seenCount}</p>
              <p>Uploaded by: {fieldValue(selectedWarning.uploadedBy)}</p>
              <p>Upload log: {selectedWarning.uploadLogId}</p>
              <p>
                Upload logs:{' '}
                {selectedWarning.uploadLogIds.length > 0 ? selectedWarning.uploadLogIds.join(', ') : '-'}
              </p>
              <p>Reporting period: {fieldValue(selectedWarning.reportingPeriodId)}</p>
            </div>
            <div className="detail-block">
              <h3>Subject</h3>
              <p>Resident: {fieldValue(selectedWarning.residentName)}</p>
              <p>MCR: {fieldValue(selectedWarning.mcr)}</p>
              <p>Programme: {fieldValue(selectedWarning.programmeCode)}</p>
              <p>Month: {fieldValue(selectedWarning.monthLabel)}</p>
              <p>Session type: {fieldValue(selectedWarning.sessionType)}</p>
              <p>Count: {fieldValue(selectedWarning.count)}</p>
            </div>
            <div className="detail-block">
              <h3>Traceability</h3>
              <p>Sheet: {fieldValue(selectedWarning.sheetName)}</p>
              <p>Row: {fieldValue(selectedWarning.rowNumber)}</p>
              <p>Cell: {fieldValue(selectedWarning.cellRef)}</p>
              <p>Posting codes: {selectedWarning.postingCodes.length > 0 ? selectedWarning.postingCodes.join(', ') : '-'}</p>
              <p>Source: {fieldValue(selectedWarning.sourceLabel)}</p>
            </div>
            <div className="detail-block">
              <h3>Raw payload</h3>
              <pre className="raw-json">{JSON.stringify(selectedWarning.rawPayload, null, 2)}</pre>
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
