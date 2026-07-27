import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import {
  applyWarningSourceCellReplacement,
  getUploadWarningIssue,
  listUploadWarnings,
  previewWarningSourceCellReplacement,
  updateUploadWarningIssueStatus,
} from '../../api/uploadWarnings'
import { DataRevalidationCallout } from '../../components/DataRevalidationCallout'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { useAppState } from '../../context/useAppState'
import type { UploadType } from '../../types/app'
import type {
  UploadWarning,
  UploadWarningIssueDetail,
  WarningSeverity,
  WarningSourceCellApplyResponse,
  WarningSourceCellPreviewResponse,
  WarningSourceTrace,
} from '../../types/upload'
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

type WarningReviewMode = 'active' | 'history'
type WarningAction = 'resolve' | 'dismiss' | 'supersede'

const uploadTypeLabels: Record<UploadType, string> = {
  rdb: 'RDB Posting Schedule',
  form_f1: 'FormF1',
  ttf: 'Teaching Target File',
  public_holidays: 'Public Holidays / AY Dates',
}

const uploadTypeOrder: UploadType[] = ['rdb', 'form_f1', 'ttf', 'public_holidays']
const sourceCellWarningTypes = new Set(['empty_posting_cell', 'unmatched_multi_posting'])
const pageSize = 50

const formatDateTime = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : '-'

const modeDescriptions: Record<WarningReviewMode, string> = {
  active: 'Latest warning state from the most recent upload per source/scope.',
  history: 'Deduped warning history across previous upload logs.',
}

const statusLabel: Record<string, string> = {
  unresolved: 'Unresolved',
  reappeared: 'Reappeared',
  resolved: 'Resolved',
  dismissed: 'Dismissed',
  superseded: 'Superseded',
}

const actionLabel: Record<WarningAction, string> = {
  resolve: 'Resolve',
  dismiss: 'Dismiss',
  supersede: 'Supersede',
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
    warning.warningIssueId,
    warning.latestUploadWarningId,
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

const traceValue = (trace: WarningSourceTrace | null | undefined, key: keyof WarningSourceTrace) =>
  fieldValue(trace?.[key] as string | number | null | undefined)

const warningIssueIdForRow = (warning: UploadWarning) =>
  warning.warningIssueId ?? warning.issueId ?? null

const statusText = (status?: string | null) => statusLabel[status ?? ''] ?? fieldValue(status)

export const AdminWarningsPage = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { authCacheScope, demoAdminId, demoAdminProgrammes, role } = useAppState()
  const adminLevel = role === 'master_admin' ? 'master' : 'programme'
  const isProgrammePc = location.pathname.startsWith('/pc') || role === 'programme_pc'
  const [warnings, setWarnings] = useState<UploadWarning[]>([])
  const hasLoadedWarningsRef = useRef(false)
  const [isInitialLoading, setIsInitialLoading] = useState(true)
  const [isRefetching, setIsRefetching] = useState(false)
  const [isManualRefreshing, setIsManualRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedWarning, setSelectedWarning] = useState<UploadWarning | null>(null)
  const [warningDetail, setWarningDetail] = useState<UploadWarningIssueDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [isDetailLoading, setIsDetailLoading] = useState(false)
  const [actionNote, setActionNote] = useState('')
  const [actionBusy, setActionBusy] = useState<WarningAction | null>(null)
  const [actionResult, setActionResult] = useState<string | null>(null)
  const [replacementValue, setReplacementValue] = useState('')
  const [correctionReason, setCorrectionReason] = useState('')
  const [sourceCellError, setSourceCellError] = useState<string | null>(null)
  const [sourceCellPreview, setSourceCellPreview] =
    useState<WarningSourceCellPreviewResponse | null>(null)
  const [sourceCellApplyResult, setSourceCellApplyResult] =
    useState<WarningSourceCellApplyResponse | null>(null)
  const [sourceCellState, setSourceCellState] =
    useState<'idle' | 'previewing' | 'applying'>('idle')
  const [uploadTypeFilter, setUploadTypeFilter] = useState<UploadType | 'all'>(
    toUploadTypeFilter(searchParams.get('upload_type')),
  )
  const [severityFilter, setSeverityFilter] = useState<WarningSeverity | 'all'>('all')
  const [programmeFilter, setProgrammeFilter] = useState<string>(
    searchParams.get('programme_code') ?? 'all',
  )
  const [warningTypeFilter, setWarningTypeFilter] = useState(searchParams.get('warning_type') ?? '')
  const [reportingPeriodFilter, setReportingPeriodFilter] = useState(
    searchParams.get('reporting_period_id') ?? '',
  )
  const [uploadLogFilter] = useState(searchParams.get('upload_log_id') ?? '')
  const [searchTerm, setSearchTerm] = useState(searchParams.get('search') ?? '')
  const [warningMode, setWarningMode] = useState<WarningReviewMode>(
    toWarningMode(searchParams.get('mode')),
  )
  const [offset, setOffset] = useState(0)
  const authScopeKey = useMemo(
    () => makeScopedCacheKey(authCacheScope, 'admin.upload-warnings.auth-scope', {}),
    [authCacheScope],
  )
  const currentAuthScopeKeyRef = useRef(authScopeKey)
  const listRequestRef = useRef(0)
  const detailRequestRef = useRef(0)
  const actionRequestRef = useRef(0)
  const sourceCellRequestRef = useRef(0)

  useLayoutEffect(() => {
    currentAuthScopeKeyRef.current = authScopeKey
    detailRequestRef.current += 1
    actionRequestRef.current += 1
    sourceCellRequestRef.current += 1
  }, [authScopeKey])

  const warningCacheKey = useCallback((
    mode: WarningReviewMode,
    uploadType: UploadType | 'all',
    severity: WarningSeverity | 'all',
    programmeCode: string,
    warningType: string,
    reportingPeriodId: string,
    search: string,
    pageOffset: number,
  ) => makeScopedCacheKey(authCacheScope, 'admin.upload-warnings.list', {
    adminLevel,
    mode,
    uploadType,
    severity,
    programmeCode,
    warningType,
    reportingPeriodId,
    uploadLogId: uploadLogFilter,
    search: search.trim(),
    limit: pageSize,
    offset: pageOffset,
  }), [adminLevel, authCacheScope, uploadLogFilter])
  const listRequestContextKey = warningCacheKey(
    warningMode,
    uploadTypeFilter,
    severityFilter,
    programmeFilter,
    warningTypeFilter,
    reportingPeriodFilter,
    searchTerm,
    offset,
  )
  const currentListRequestContextKeyRef = useRef(listRequestContextKey)

  useLayoutEffect(() => {
    currentListRequestContextKeyRef.current = listRequestContextKey
    listRequestRef.current += 1
  }, [listRequestContextKey])

  const loadWarnings = useCallback(() => listUploadWarnings({
    adminId: demoAdminId,
    adminProgrammes: demoAdminProgrammes,
    adminLevel,
    mode: warningMode,
    uploadType: uploadTypeFilter,
    severity: severityFilter,
    programmeCode: programmeFilter,
    warningType: warningTypeFilter,
    reportingPeriodId: reportingPeriodFilter,
    uploadLogId: uploadLogFilter,
    search: searchTerm,
    limit: pageSize,
    offset,
  }), [
    adminLevel,
    demoAdminId,
    demoAdminProgrammes,
    offset,
    programmeFilter,
    reportingPeriodFilter,
    searchTerm,
    severityFilter,
    uploadLogFilter,
    uploadTypeFilter,
    warningMode,
    warningTypeFilter,
  ])

  const resetSourceCellState = useCallback(() => {
    setReplacementValue('')
    setCorrectionReason('')
    setSourceCellError(null)
    setSourceCellPreview(null)
    setSourceCellApplyResult(null)
    setSourceCellState('idle')
  }, [])

  useEffect(() => {
    let active = true
    queueMicrotask(() => {
      if (!active) {
        return
      }
      hasLoadedWarningsRef.current = false
      setWarnings([])
      setError(null)
      setSelectedWarning(null)
      setWarningDetail(null)
      setDetailError(null)
      setIsDetailLoading(false)
      setActionNote('')
      setActionBusy(null)
      setActionResult(null)
      resetSourceCellState()
      setIsManualRefreshing(false)
      setIsRefetching(false)
      setIsInitialLoading(true)
    })
    return () => {
      active = false
    }
  }, [authScopeKey, resetSourceCellState])

  const loadDetail = useCallback(async (warningIssueId: string) => {
    const requestId = detailRequestRef.current + 1
    detailRequestRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(authScopeKey, requestId)
    const isCurrentRequest = () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentAuthScopeKeyRef.current,
      detailRequestRef.current,
    )
    setIsDetailLoading(true)
    setDetailError(null)
    setActionResult(null)
    try {
      const detail = await getUploadWarningIssue({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        warningIssueId,
      })
      if (!isCurrentRequest()) {
        return
      }
      setWarningDetail(detail)
    } catch (fetchError) {
      if (!isCurrentRequest()) {
        return
      }
      setWarningDetail(null)
      setDetailError(formatUserFacingApiError(fetchError, {
        fallbackMessage: 'Unable to load warning detail.',
      }))
    } finally {
      if (isCurrentRequest()) {
        setIsDetailLoading(false)
      }
    }
  }, [adminLevel, authScopeKey, demoAdminId, demoAdminProgrammes])

  const fetchWarnings = useCallback(async () => {
    const requestId = listRequestRef.current + 1
    listRequestRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(listRequestContextKey, requestId)
    const isCurrentRequest = () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentListRequestContextKeyRef.current,
      listRequestRef.current,
    )
    setIsManualRefreshing(true)
    setIsRefetching(warnings.length > 0)
    setError(null)
    const key = warningCacheKey(
      warningMode,
      uploadTypeFilter,
      severityFilter,
      programmeFilter,
      warningTypeFilter,
      reportingPeriodFilter,
      searchTerm,
      offset,
    )
    try {
      clearMemoryCache((cacheKey) => cacheKey === key)
      const { data: rows } = await readThroughMemoryCache(
        key,
        loadWarnings,
        { force: true },
      )
      if (!isCurrentRequest()) {
        return
      }
      setWarnings(rows)
      hasLoadedWarningsRef.current = true
    } catch (fetchError) {
      if (isMemoryCacheInvalidatedError(fetchError) || !isCurrentRequest()) {
        return
      }
      if (!hasLoadedWarningsRef.current) {
        setWarnings([])
      }
      hasLoadedWarningsRef.current = true
      setError(formatUserFacingApiError(fetchError, {
        fallbackMessage: 'Unable to load upload warnings.',
      }))
    } finally {
      if (isCurrentRequest()) {
        setIsManualRefreshing(false)
        setIsInitialLoading(false)
        setIsRefetching(false)
      }
    }
  }, [
    listRequestContextKey,
    loadWarnings,
    offset,
    programmeFilter,
    reportingPeriodFilter,
    searchTerm,
    severityFilter,
    uploadTypeFilter,
    warningCacheKey,
    warningMode,
    warningTypeFilter,
    warnings.length,
  ])

  useEffect(() => {
    let active = true
    ;(async () => {
      const requestId = listRequestRef.current + 1
      listRequestRef.current = requestId
      const requestFence = captureProtectedAsyncRequestFence(listRequestContextKey, requestId)
      const isCurrentRequest = () => active && isProtectedAsyncRequestFenceCurrent(
        requestFence,
        currentListRequestContextKeyRef.current,
        listRequestRef.current,
      )
      const key = warningCacheKey(
        warningMode,
        uploadTypeFilter,
        severityFilter,
        programmeFilter,
        warningTypeFilter,
        reportingPeriodFilter,
        searchTerm,
        offset,
      )
      const cached = getMemoryCache<UploadWarning[]>(key)
      if (cached && isCurrentRequest()) {
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
        if (isCurrentRequest()) {
          setWarnings(rows)
          hasLoadedWarningsRef.current = true
        }
      } catch (fetchError) {
        if (!isMemoryCacheInvalidatedError(fetchError) && isCurrentRequest()) {
          if (!isBackgroundRefetch) {
            setWarnings([])
          }
          hasLoadedWarningsRef.current = true
          setError(formatUserFacingApiError(fetchError, {
            fallbackMessage: 'Unable to load upload warnings.',
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
    listRequestContextKey,
    loadWarnings,
    offset,
    programmeFilter,
    reportingPeriodFilter,
    searchTerm,
    severityFilter,
    uploadTypeFilter,
    warningCacheKey,
    warningMode,
    warningTypeFilter,
  ])

  const refreshAfterMutation = async (isCurrentRequest: () => boolean) => {
    if (!isCurrentRequest()) {
      return
    }
    clearMemoryCache((key) => key.includes('admin.upload-warnings'))
    await fetchWarnings()
    if (!isCurrentRequest()) {
      return
    }
    const warningIssueId = selectedWarning ? warningIssueIdForRow(selectedWarning) : ''
    if (warningIssueId) {
      await loadDetail(warningIssueId)
    }
  }

  const programmeOptions = useMemo(
    () =>
      Array.from(
        new Set(
          [
            ...demoAdminProgrammes,
            programmeFilter === 'all' ? null : programmeFilter,
            ...warnings.map((warning) => warning.programmeCode),
          ].filter((item): item is string => Boolean(item && item.trim())),
        ),
      ).sort(),
    [demoAdminProgrammes, programmeFilter, warnings],
  )

  const filteredWarnings = useMemo(() => {
    return warnings.filter((warning) => {
      const byUploadType = uploadTypeFilter === 'all' || warning.uploadType === uploadTypeFilter
      const bySeverity = severityFilter === 'all' || warning.severity === severityFilter
      const byProgramme = programmeFilter === 'all' || warning.programmeCode === programmeFilter
      const byType = !warningTypeFilter || warning.warningType === warningTypeFilter
      return byUploadType && bySeverity && byProgramme && byType && matchesSearch(warning, searchTerm)
    })
  }, [programmeFilter, searchTerm, severityFilter, uploadTypeFilter, warningTypeFilter, warnings])

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
    setWarningTypeFilter('')
    setReportingPeriodFilter('')
    setSearchTerm('')
    setOffset(0)
  }

  const openWarningDetail = (warning: UploadWarning) => {
    detailRequestRef.current += 1
    actionRequestRef.current += 1
    sourceCellRequestRef.current += 1
    resetSourceCellState()
    setWarningDetail(null)
    setDetailError(null)
    setActionNote('')
    setActionResult(null)
    setSelectedWarning(warning)
    const warningIssueId = warningIssueIdForRow(warning)
    if (warningIssueId) {
      void loadDetail(warningIssueId)
    } else {
      setDetailError('Warning detail is unavailable for this row.')
    }
  }

  const closeWarningDetail = () => {
    detailRequestRef.current += 1
    actionRequestRef.current += 1
    sourceCellRequestRef.current += 1
    setSelectedWarning(null)
    setWarningDetail(null)
    setDetailError(null)
    setActionNote('')
    setActionResult(null)
    resetSourceCellState()
  }

  const openMultiPostingRules = () => {
    const basePath = isProgrammePc ? '/pc/config' : '/admin/config'
    const params = new URLSearchParams({ section: 'multi-posting-rules' })
    if (warningDetail?.mcr) {
      params.set('mcr', warningDetail.mcr)
    }
    if (warningDetail?.monthLabel) {
      params.set('month', warningDetail.monthLabel)
    }
    params.set('warningType', 'unmatched_multi_posting')
    navigate(`${basePath}?${params.toString()}`, {
      state: { configSection: 'multi-posting-rules' },
    })
  }

  const submitWarningAction = async (action: WarningAction) => {
    if (!warningDetail) {
      return
    }
    const requestId = actionRequestRef.current + 1
    actionRequestRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(authScopeKey, requestId)
    const isCurrentRequest = () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentAuthScopeKeyRef.current,
      actionRequestRef.current,
    )
    setActionBusy(action)
    setActionResult(null)
    setDetailError(null)
    try {
      const response = await updateUploadWarningIssueStatus({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        warningIssueId: warningDetail.warningIssueId,
        action,
        note: actionNote,
      })
      if (!isCurrentRequest()) {
        return
      }
      setActionNote('')
      setActionResult(`${statusText(response.previousStatus)} -> ${statusText(response.newStatus)}`)
      await refreshAfterMutation(isCurrentRequest)
    } catch (actionError) {
      if (!isCurrentRequest()) {
        return
      }
      setDetailError(formatUserFacingApiError(actionError, {
        fallbackMessage: 'Unable to update warning status.',
      }))
    } finally {
      if (isCurrentRequest()) {
        setActionBusy(null)
      }
    }
  }

  const previewSourceCell = async () => {
    if (!warningDetail) {
      return
    }
    const requestId = sourceCellRequestRef.current + 1
    sourceCellRequestRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(authScopeKey, requestId)
    const isCurrentRequest = () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentAuthScopeKeyRef.current,
      sourceCellRequestRef.current,
    )
    setSourceCellState('previewing')
    setSourceCellError(null)
    setSourceCellPreview(null)
    setSourceCellApplyResult(null)
    try {
      const preview = await previewWarningSourceCellReplacement({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        warningIssueId: warningDetail.warningIssueId,
        request: {
          replacement_raw_cell_value: replacementValue,
          upload_warning_id: warningDetail.latestUploadWarningId,
          expected_latest_upload_warning_id: warningDetail.latestUploadWarningId,
          expected_fingerprint: warningDetail.fingerprint,
        },
      })
      if (!isCurrentRequest()) {
        return
      }
      setSourceCellPreview(preview)
    } catch (previewError) {
      if (!isCurrentRequest()) {
        return
      }
      setSourceCellError(formatUserFacingApiError(previewError, {
        fallbackMessage: 'Unable to preview replacement.',
      }))
    } finally {
      if (isCurrentRequest()) {
        setSourceCellState('idle')
      }
    }
  }

  const applySourceCell = async () => {
    if (!warningDetail || !sourceCellPreview?.applyAllowed || !correctionReason.trim()) {
      return
    }
    const requestId = sourceCellRequestRef.current + 1
    sourceCellRequestRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(authScopeKey, requestId)
    const isCurrentRequest = () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentAuthScopeKeyRef.current,
      sourceCellRequestRef.current,
    )
    setSourceCellState('applying')
    setSourceCellError(null)
    setSourceCellApplyResult(null)
    try {
      const result = await applyWarningSourceCellReplacement({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        warningIssueId: warningDetail.warningIssueId,
        request: {
          replacement_raw_cell_value: replacementValue,
          upload_warning_id: sourceCellPreview.latestUploadWarningId ?? warningDetail.latestUploadWarningId,
          expected_latest_upload_warning_id: sourceCellPreview.latestUploadWarningId ?? warningDetail.latestUploadWarningId,
          expected_fingerprint: warningDetail.fingerprint,
          correction_reason: correctionReason.trim(),
        },
      })
      if (!isCurrentRequest()) {
        return
      }
      setSourceCellApplyResult(result)
      await refreshAfterMutation(isCurrentRequest)
    } catch (applyError) {
      if (!isCurrentRequest()) {
        return
      }
      setSourceCellError(formatUserFacingApiError(applyError, {
        fallbackMessage: 'Unable to apply replacement.',
      }))
    } finally {
      if (isCurrentRequest()) {
        setSourceCellState('idle')
      }
    }
  }

  const isShowingFirstLoad = isInitialLoading && warnings.length === 0
  const canLoadNextPage = warnings.length === pageSize
  const selectedIssueStatus = warningDetail?.status ?? selectedWarning?.status ?? 'unresolved'
  const selectedTrace = warningDetail?.latestSourceTrace ?? selectedWarning?.latestSourceTrace
  const canUseSourceCell =
    Boolean(warningDetail) &&
    (selectedWarning?.uploadType === 'rdb' || selectedTrace?.source_payload !== undefined) &&
    sourceCellWarningTypes.has(warningDetail?.warningType ?? '')
  const hasFilters =
    uploadTypeFilter !== 'all' ||
    severityFilter !== 'all' ||
    programmeFilter !== 'all' ||
    warningTypeFilter.trim().length > 0 ||
    reportingPeriodFilter.trim().length > 0 ||
    uploadLogFilter.trim().length > 0 ||
    searchTerm.trim().length > 0

  const pageSubtitle = isShowingFirstLoad
    ? 'Loading persisted warnings'
    : `${filteredWarnings.length} ${warningMode === 'active' ? 'active ' : 'historical '}warning${filteredWarnings.length === 1 ? '' : 's'} on this page`

  return (
    <div className="page admin-warnings-page">
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
            onClick={() => {
              setWarningMode('active')
              setOffset(0)
            }}
          >
            Active warnings
          </button>
          <button
            type="button"
            className={warningMode === 'history' ? 'is-active' : ''}
            role="tab"
            aria-selected={warningMode === 'history'}
            onClick={() => {
              setWarningMode('history')
              setOffset(0)
            }}
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
        <div className="admin-filter-summary">
          <span>Filters</span>
          <strong>{hasFilters ? 'Active filters applied' : 'All warnings'}</strong>
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
          Severity
          <select
            value={severityFilter}
            onChange={(event) => {
              setSeverityFilter(event.target.value as WarningSeverity | 'all')
              setOffset(0)
            }}
          >
            <option value="all">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
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
          Warning type
          <input
            type="text"
            value={warningTypeFilter}
            onChange={(event) => {
              setWarningTypeFilter(event.target.value.trim())
              setOffset(0)
            }}
            placeholder="empty_posting_cell"
          />
        </label>
        <label>
          Reporting period
          <input
            type="text"
            value={reportingPeriodFilter}
            onChange={(event) => {
              setReportingPeriodFilter(event.target.value.trim())
              setOffset(0)
            }}
            placeholder="Optional period filter"
          />
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
            placeholder="Type, resident, MCR, source, message..."
          />
        </label>
        <button type="button" className="button button-ghost" onClick={clearFilters}>
          Clear filters
        </button>
      </section>

      {uploadLogFilter ? (
        <section className="inline-callout callout-info warning-query-callout">
          <span>Reviewing warnings linked to the selected upload.</span>
        </section>
      ) : null}

      <section className={`warning-results-card ${isRefetching ? 'is-refetching' : ''}`}>
        <div className="warning-results-header">
          <div>
            <span className="warning-group-kicker">Persisted upload warnings</span>
            <h2>{warningMode === 'active' ? 'Active warnings' : 'Warning history'}</h2>
          </div>
          <div className="parsed-data-count-status">
            {isRefetching ? <span className="parsed-data-updating">Refreshing...</span> : null}
            <span className="warning-count-pill">
              Page {Math.floor(offset / pageSize) + 1} - {filteredWarnings.length} warning{filteredWarnings.length === 1 ? '' : 's'}
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
                          key={`${warningIssueIdForRow(warning) ?? warning.latestUploadWarningId ?? warning.warningId}-${warning.latestUploadWarningId ?? warning.warningId}`}
                          className="table-clickable-row"
                          tabIndex={0}
                          onClick={() => openWarningDetail(warning)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault()
                              openWarningDetail(warning)
                            }
                          }}
                        >
                          <td className="cell-type">
                            <span className="warning-type-cell-content">
                              <span className={`severity-dot severity-dot-${warning.severity}`} />
                              <span className="mono-chip">{warning.warningType}</span>
                            </span>
                          </td>
                          <td>{fieldValue(warning.residentName)}</td>
                          <td className="mono-cell">{fieldValue(warning.mcr)}</td>
                          <td>{fieldValue(warning.programmeCode)}</td>
                          <td>{fieldValue(warning.monthLabel)}</td>
                          <td className="mono-cell">{fieldValue(warning.sourceLabel ?? warning.cellRef)}</td>
                          <td>
                            <span className="warning-status-stack">
                              <span className={`review-marker warning-status-${warning.status ?? 'unresolved'}`}>
                                {statusText(warning.status ?? 'unresolved')}
                              </span>
                              {warning.reappeared ? <span className="warning-seen-pill">Reappeared</span> : null}
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
                <div className="responsive-card-list admin-mobile-record-list warning-mobile-card-list" aria-label={`${uploadTypeLabels[group.uploadType]} warning cards`}>
                  {group.warnings.map((warning) => (
                    <button
                      key={`${warningIssueIdForRow(warning) ?? warning.latestUploadWarningId ?? warning.warningId}-mobile`}
                      type="button"
                      className="mobile-record-card admin-mobile-record-card warning-mobile-card"
                      onClick={() => openWarningDetail(warning)}
                      aria-label={`Open warning detail for ${warning.warningType}`}
                    >
                      <span className="admin-mobile-card-header">
                        <span className="admin-mobile-card-title warning-mobile-card-title safe-wrap">
                          <span className={`severity-dot severity-dot-${warning.severity}`} />
                          <span className="mono-chip">{warning.warningType}</span>
                        </span>
                        <span className={`review-marker warning-status-${warning.status ?? 'unresolved'}`}>
                          {statusText(warning.status ?? 'unresolved')}
                        </span>
                      </span>
                      <span className="admin-mobile-card-meta">
                        <span>
                          {warning.severity}
                          {' - '}
                          {fieldValue(warning.programmeCode)}
                          {' - '}
                          {fieldValue(warning.monthLabel)}
                        </span>
                        <span>{fieldValue(warning.residentName)} - {fieldValue(warning.mcr)}</span>
                        <span className="admin-mobile-card-source mono-cell">
                          {fieldValue(warning.sourceLabel ?? warning.cellRef)}
                        </span>
                        <span className="safe-wrap">{fieldValue(warning.message)}</span>
                      </span>
                      <span className="admin-mobile-card-badges">
                        {warning.reappeared ? <span className="warning-seen-pill">Reappeared</span> : null}
                        {warning.seenCount > 1 ? (
                          <span className="warning-seen-pill">Seen in {warning.seenCount} uploads</span>
                        ) : null}
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
        <div className="warning-pagination">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => setOffset((current) => Math.max(0, current - pageSize))}
            disabled={offset === 0 || isRefetching || isInitialLoading}
          >
            Previous
          </button>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => setOffset((current) => current + pageSize)}
            disabled={!canLoadNextPage || isRefetching || isInitialLoading}
          >
            Next
          </button>
        </div>
      </section>

      <DetailDrawer
        title={warningDetail ? warningDetail.warningType : selectedWarning?.warningType ?? 'Warning detail'}
        open={Boolean(selectedWarning)}
        onClose={closeWarningDetail}
        footer={
          warningDetail?.warningType === 'unmatched_multi_posting' ? (
            <button type="button" className="button button-primary" onClick={openMultiPostingRules}>
              Open Multi-Posting Rules
            </button>
          ) : null
        }
      >
        {selectedWarning ? (
          <div className="warning-detail">
            {isDetailLoading ? (
              <div className="warning-state-card">Loading warning detail...</div>
            ) : detailError ? (
              <div className="inline-callout callout-error">
                <span>{detailError}</span>
              </div>
            ) : null}

            {warningDetail ? (
              <>
                <div className="detail-block">
                  <h3>Summary</h3>
                  <p>{warningDetail.message ?? selectedWarning.message}</p>
                  <p>
                    <span className={`severity-dot severity-dot-${warningDetail.severity}`} />
                    {warningDetail.severity} - {statusText(selectedIssueStatus)}
                  </p>
                  {warningDetail.suggestedAction ? <p>{warningDetail.suggestedAction}</p> : null}
                </div>

                <div className="detail-block">
                  <h3>Source Trace</h3>
                  <div className="parsed-data-detail-grid">
                    <div className="parsed-data-detail-item">
                      <span>Programme</span>
                      <strong>{fieldValue(warningDetail.programmeCode ?? selectedTrace?.programme_code as string | null)}</strong>
                    </div>
                    <div className="parsed-data-detail-item">
                      <span>MCR</span>
                      <strong>{fieldValue(warningDetail.mcr ?? selectedTrace?.mcr as string | null)}</strong>
                    </div>
                    <div className="parsed-data-detail-item">
                      <span>Resident</span>
                      <strong>{fieldValue(warningDetail.residentName ?? selectedTrace?.resident_name as string | null)}</strong>
                    </div>
                    <div className="parsed-data-detail-item">
                      <span>Month</span>
                      <strong>{fieldValue(warningDetail.monthLabel ?? selectedTrace?.month_label as string | null)}</strong>
                    </div>
                    <div className="parsed-data-detail-item">
                      <span>Sheet</span>
                      <strong>{traceValue(selectedTrace, 'sheet_name')}</strong>
                    </div>
                    <div className="parsed-data-detail-item">
                      <span>Row</span>
                      <strong>{traceValue(selectedTrace, 'row_number')}</strong>
                    </div>
                    <div className="parsed-data-detail-item">
                      <span>Cell</span>
                      <strong>{traceValue(selectedTrace, 'cell_ref')}</strong>
                    </div>
                  </div>
                </div>

                <div className="detail-block">
                  <h3>Workflow</h3>
                  {actionResult ? (
                    <div className="inline-callout callout-success">
                      <span>{actionResult}</span>
                    </div>
                  ) : null}
                  <label>
                    Note
                    <textarea
                      value={actionNote}
                      onChange={(event) => setActionNote(event.target.value)}
                      rows={3}
                      maxLength={2000}
                      placeholder="Optional note for resolve, dismiss, or supersede"
                    />
                  </label>
                  <div className="warning-action-row">
                    {(['resolve', 'dismiss', 'supersede'] as WarningAction[]).map((action) => (
                      <button
                        key={action}
                        type="button"
                        className={action === 'resolve' ? 'button button-primary' : 'button button-secondary'}
                        onClick={() => void submitWarningAction(action)}
                        disabled={Boolean(actionBusy)}
                      >
                        {actionBusy === action ? 'Saving...' : actionLabel[action]}
                      </button>
                    ))}
                  </div>
                  <div className="warning-resolution-grid">
                    <span>Resolved by</span>
                    <strong>{fieldValue(warningDetail.resolvedBy)}</strong>
                    <span>Resolved at</span>
                    <strong>{formatDateTime(warningDetail.resolvedAt)}</strong>
                    <span>Resolution note</span>
                    <strong>{fieldValue(warningDetail.resolutionNote)}</strong>
                  </div>
                </div>

                {canUseSourceCell ? (
                  <div className="detail-block source-cell-warning-panel">
                    <h3>Source-Cell Replacement</h3>
                    <p>Preview parses the corrected cell without writes. Apply replaces only the linked resident/month source-cell rows and leaves warning resolution manual.</p>
                    <label>
                      Replacement cell value
                      <textarea
                        value={replacementValue}
                        onChange={(event) => {
                          setReplacementValue(event.target.value)
                          setSourceCellPreview(null)
                          setSourceCellApplyResult(null)
                          setSourceCellError(null)
                        }}
                        rows={4}
                        placeholder="e.g. TTSHAnaes or Annual Leaves (01-Jul-2025 to 05-Jul-2025)"
                      />
                    </label>
                    <div className="warning-action-row">
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => void previewSourceCell()}
                        disabled={sourceCellState !== 'idle'}
                      >
                        {sourceCellState === 'previewing' ? 'Previewing...' : 'Preview'}
                      </button>
                    </div>
                    {sourceCellError ? (
                      <div className="inline-callout callout-error">
                        <span>{sourceCellError}</span>
                      </div>
                    ) : null}
                    {sourceCellPreview ? (
                      <div className="source-cell-preview-result">
                        <div className={`inline-callout ${sourceCellPreview.applyAllowed ? 'callout-success' : 'callout-warning'}`}>
                          <span>
                            {sourceCellPreview.applyAllowed
                              ? 'Preview parsed successfully and can be applied.'
                              : 'Preview returned a non-applyable result.'}
                          </span>
                        </div>
                        <DataRevalidationCallout impact={sourceCellPreview.dataRevalidation} />
                        <div className="parsed-data-detail-grid">
                          <div className="parsed-data-detail-item">
                            <span>Normalized value</span>
                            <strong>{fieldValue(sourceCellPreview.normalizedCellValue)}</strong>
                          </div>
                          <div className="parsed-data-detail-item">
                            <span>Candidate rows</span>
                            <strong>{sourceCellPreview.parsedCandidateRows.length}</strong>
                          </div>
                          <div className="parsed-data-detail-item">
                            <span>Parser warnings</span>
                            <strong>{sourceCellPreview.parserWarnings.length}</strong>
                          </div>
                          <div className="parsed-data-detail-item">
                            <span>Parser errors</span>
                            <strong>{sourceCellPreview.parserErrors.length}</strong>
                          </div>
                        </div>
                        {sourceCellPreview.nextActions.length > 0 ? (
                          <ul className="source-cell-next-actions">
                            {sourceCellPreview.nextActions.map((action) => (
                              <li key={action}>{action}</li>
                            ))}
                          </ul>
                        ) : null}
                        <label>
                          Correction reason
                          <textarea
                            value={correctionReason}
                            onChange={(event) => setCorrectionReason(event.target.value)}
                            rows={3}
                            maxLength={500}
                            placeholder="Required before applying"
                          />
                        </label>
                        <button
                          type="button"
                          className="button button-primary"
                          onClick={() => void applySourceCell()}
                          disabled={
                            sourceCellState !== 'idle' ||
                            !sourceCellPreview.applyAllowed ||
                            !correctionReason.trim()
                          }
                        >
                          {sourceCellState === 'applying' ? 'Applying...' : 'Apply replacement'}
                        </button>
                      </div>
                    ) : null}
                    {sourceCellApplyResult ? (
                      <div className="source-cell-apply-result">
                        <div className="inline-callout callout-success">
                          <span>Correction recorded. Review the updated warning status below.</span>
                        </div>
                        <DataRevalidationCallout impact={sourceCellApplyResult.dataRevalidation} />
                        <div className="parsed-data-detail-grid">
                          {Object.entries(sourceCellApplyResult.replacementSummary).map(([key, value]) => (
                            <div key={key} className="parsed-data-detail-item">
                              <span>{key.replace(/_/g, ' ')}</span>
                              <strong>{value}</strong>
                            </div>
                          ))}
                          <div className="parsed-data-detail-item">
                            <span>Warning status</span>
                            <strong>{statusText(sourceCellApplyResult.warningIssueStatus)}</strong>
                          </div>
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}

                <div className="detail-block">
                  <h3>Occurrences</h3>
                  {warningDetail.occurrences.length === 0 ? (
                    <p>No occurrences are linked to this issue.</p>
                  ) : (
                    <div className="warning-occurrence-list">
                      {warningDetail.occurrences.map((occurrence) => (
                        <div key={occurrence.id} className="warning-occurrence-card">
                          <div>
                            <strong>{formatDateTime(occurrence.createdAt)}</strong>
                          </div>
                          <p>{occurrence.message}</p>
                          <small>
                            {fieldValue(occurrence.sheetName)} row {fieldValue(occurrence.rowNumber)} cell {fieldValue(occurrence.cellRef)}
                          </small>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : null}
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
