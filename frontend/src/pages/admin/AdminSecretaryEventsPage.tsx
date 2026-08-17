import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from 'react'
import type { SetStateAction } from 'react'
import { useSearchParams } from 'react-router'
import {
  forceDeleteAdminSecretaryEvent,
  getAdminSecretaryEvent,
  listAdminSecretaryEvents,
  type AdminSecretaryEventDetail,
  type AdminSecretaryEventListItem,
  type AdminSecretaryEventListSummary,
  type AdminSecretaryEventSourceFilter,
} from '../../api/adminSecretaryEvents'
import { listPostingCodes, type PostingCodeOption } from '../../api/postingCodes'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'
import {
  AuthScopedReportingPageRequestController,
  authScopedReportingPageReducer,
  createAuthScopedReportingPageState,
  revalidateReportingPeriodFilterId,
  type AuthScopedReportingPageState,
} from '../../utils/authScopedReportingPeriodFilter'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'
import {
  adminEventForceDeleteSuccessMessage,
  adminEventListOffsetAfterDeletion,
  adminTeachingEventSourceLabel,
  canCloseAdminEventDetail,
  isAdminEventForceDeleteConfirmationValid,
} from './adminSecretaryEventsPageLogic'

type AttendanceFilter = 'all' | 'with' | 'without'

interface FilterState {
  reportingPeriodId: string
  postingCode: string
  dateFrom: string
  dateTo: string
  search: string
  sourceType: AdminSecretaryEventSourceFilter
  hasAttendance: AttendanceFilter
}

const pageSize = 25
const searchDebounceMs = 300

const emptyFilters = (reportingPeriodId = ''): FilterState => ({
  reportingPeriodId,
  postingCode: 'all',
  dateFrom: '',
  dateTo: '',
  search: '',
  sourceType: 'all',
  hasAttendance: 'all',
})

const emptySummary: AdminSecretaryEventListSummary = {
  totalEvents: 0,
  withAttendance: 0,
  withoutAttendance: 0,
  totalAttendanceCount: 0,
  totalExternalAttendanceCount: 0,
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
  const minutes = parts[1]
  const suffix = hours >= 12 ? 'pm' : 'am'
  const hour12 = hours % 12 || 12
  return `${hour12}:${minutes} ${suffix}`
}

const formatDuration = (value?: number | null) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '-'
  }
  const label = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return `${label}h`
}

const compactParts = (parts: Array<string | number | null | undefined>) => {
  const values = parts
    .map((part) => (part === null || part === undefined ? '' : String(part).trim()))
    .filter((part) => part && part !== '-')
  return values.length > 0 ? values.join(' - ') : '-'
}

const fieldValue = (value?: string | number | null) => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  return String(value)
}

const sourceBadgeTone = (
  event: Pick<AdminSecretaryEventListItem, 'sourceType'>,
): 'info' | 'neutral' => event.sourceType === 'programme_pc' ? 'info' : 'neutral'

const toAttendanceParam = (value: AttendanceFilter): boolean | null => {
  if (value === 'with') {
    return true
  }
  if (value === 'without') {
    return false
  }
  return null
}

const DetailField = ({
  label,
  value,
}: {
  label: string
  value?: string | number | null
}) => (
  <div className="parsed-data-detail-item">
    <span>{label}</span>
    <strong>{fieldValue(value)}</strong>
  </div>
)

const MetricTile = ({
  label,
  value,
}: {
  label: string
  value: number
}) => (
  <div className="secretary-event-metric">
    <span>{label}</span>
    <strong>{value}</strong>
  </div>
)

type SecretaryEventsPageState = AuthScopedReportingPageState<
  FilterState,
  AdminSecretaryEventListItem,
  AdminSecretaryEventListSummary,
  AdminSecretaryEventDetail,
  { eventId: string; message: string }
>

export const AdminSecretaryEventsPage = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const {
    role,
    demoAdminId,
    demoAdminProgrammes,
    reportingPeriodId,
    reportingPeriods,
    reportingPeriodsLoading,
    reportingPeriodsError,
    reportingPeriodAuthenticationContextVersion: authenticationContextVersion,
  } = useAppState()
  const adminLevel = role === 'programme_pc' ? 'programme' : 'master'
  const [pageState, dispatchPageState] = useReducer(
    authScopedReportingPageReducer<
      FilterState,
      AdminSecretaryEventListItem,
      AdminSecretaryEventListSummary,
      AdminSecretaryEventDetail,
      { eventId: string; message: string }
    >,
    undefined,
    () => createAuthScopedReportingPageState<
      FilterState,
      AdminSecretaryEventListItem,
      AdminSecretaryEventListSummary,
      AdminSecretaryEventDetail,
      { eventId: string; message: string }
    >(
      authenticationContextVersion,
      emptyFilters(reportingPeriodId),
      emptySummary,
      searchParams.get('event_id')?.trim() ?? '',
    ),
  )
  const [requestController] = useState(
    () => new AuthScopedReportingPageRequestController(authenticationContextVersion),
  )
  const authenticationContextChanged =
    pageState.authenticationContextVersion !== authenticationContextVersion
  const authenticationResetPending =
    authenticationContextChanged || pageState.authenticationResetPending
  const mergePageState = useCallback((changes:
    | Partial<SecretaryEventsPageState>
    | ((state: SecretaryEventsPageState) => Partial<SecretaryEventsPageState>),
  ) => {
    dispatchPageState({ type: 'merge', changes })
  }, [])
  const setFilters = useCallback((value: SetStateAction<FilterState>) => {
    mergePageState((state) => ({
      filters: typeof value === 'function' ? value(state.filters) : value,
    }))
  }, [mergePageState])
  const setEvents = useCallback((value: SetStateAction<AdminSecretaryEventListItem[]>) => {
    mergePageState((state) => ({
      rows: typeof value === 'function' ? value(state.rows) : value,
    }))
  }, [mergePageState])
  const setSummary = useCallback((value: SetStateAction<AdminSecretaryEventListSummary>) => {
    mergePageState((state) => ({
      summary: typeof value === 'function' ? value(state.summary) : value,
    }))
  }, [mergePageState])
  const setTotal = useCallback((value: SetStateAction<number>) => {
    mergePageState((state) => ({ total: typeof value === 'function' ? value(state.total) : value }))
  }, [mergePageState])
  const setOffset = useCallback((value: SetStateAction<number>) => {
    mergePageState((state) => ({ offset: typeof value === 'function' ? value(state.offset) : value }))
  }, [mergePageState])
  const setSelectedEvent = useCallback((
    value: SetStateAction<AdminSecretaryEventListItem | null>,
  ) => {
    mergePageState((state) => ({
      selectedRow: typeof value === 'function' ? value(state.selectedRow) : value,
    }))
  }, [mergePageState])
  const setSelectedDetail = useCallback((
    value: SetStateAction<AdminSecretaryEventDetail | null>,
  ) => {
    mergePageState((state) => ({
      selectedDetail: typeof value === 'function' ? value(state.selectedDetail) : value,
    }))
  }, [mergePageState])
  const setDetailError = useCallback((
    value: SetStateAction<{ eventId: string; message: string } | null>,
  ) => {
    mergePageState((state) => ({
      detailError: typeof value === 'function' ? value(state.detailError) : value,
    }))
  }, [mergePageState])
  const {
    filters,
    rows: events,
    summary,
    total,
    offset,
    selectedRow: selectedEvent,
    selectedDetail,
    detailError,
  } = pageState
  const [debouncedSearch, setDebouncedSearch] = useState(filters.search)
  const [eventsLoading, setEventsLoading] = useState(true)
  const [isRefetching, setIsRefetching] = useState(false)
  const [isManualRefreshing, setIsManualRefreshing] = useState(false)
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [postingOptions, setPostingOptions] = useState<PostingCodeOption[]>([])
  const [postingError, setPostingError] = useState<string | null>(null)
  const [deleteConfirmationOpen, setDeleteConfirmationOpen] = useState(false)
  const [deleteReason, setDeleteReason] = useState('')
  const [deleteConfirmation, setDeleteConfirmation] = useState('')
  const [deletePending, setDeletePending] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleteSuccess, setDeleteSuccess] = useState<string | null>(null)
  const deleteButtonRef = useRef<HTMLButtonElement | null>(null)
  const deleteReasonInputRef = useRef<HTMLTextAreaElement | null>(null)
  const hasLoadedRef = useRef(false)
  const selectedEventSearchParam = searchParams.get('event_id')?.trim() ?? ''
  const selectedEventId = pageState.detailId

  const updateFilter = <Key extends keyof FilterState>(
    key: Key,
    value: FilterState[Key],
  ) => {
    setFilters((previous) => ({
      ...previous,
      [key]: value,
    }))
    setOffset(0)
  }

  useLayoutEffect(() => {
    if (!authenticationContextChanged) {
      return
    }
    requestController.synchronizeAuthenticationContext(authenticationContextVersion)
    dispatchPageState({
      type: 'authentication-context-changed',
      authenticationContextVersion,
      filters: emptyFilters(reportingPeriodId),
      summary: emptySummary,
    })
  }, [
    authenticationContextChanged,
    authenticationContextVersion,
    reportingPeriodId,
    requestController,
  ])

  useEffect(() => {
    if (!pageState.authenticationResetPending) {
      return
    }
    let active = true
    void Promise.resolve().then(() => {
      if (!active) {
        return
      }
      setDebouncedSearch('')
      setEventsLoading(true)
      setIsRefetching(false)
      setIsManualRefreshing(false)
      setEventsError(null)
      setPostingOptions([])
      setPostingError(null)
      setDeleteConfirmationOpen(false)
      setDeleteReason('')
      setDeleteConfirmation('')
      setDeletePending(false)
      setDeleteError(null)
      setDeleteSuccess(null)
      hasLoadedRef.current = false
      setSearchParams((previous) => {
        const next = new URLSearchParams(previous)
        next.delete('event_id')
        return next
      }, { replace: true })
      if (!selectedEventSearchParam) {
        dispatchPageState({ type: 'authentication-reset-completed' })
      }
    })
    return () => {
      active = false
    }
  }, [pageState.authenticationResetPending, selectedEventSearchParam, setSearchParams])

  useEffect(() => {
    if (authenticationResetPending || selectedEventSearchParam === pageState.detailId) {
      return
    }
    if (deletePending && pageState.detailId) {
      setSearchParams((previous) => {
        const next = new URLSearchParams(previous)
        next.set('event_id', pageState.detailId)
        return next
      }, { replace: true })
      return
    }
    mergePageState({ detailId: selectedEventSearchParam })
  }, [
    authenticationResetPending,
    deletePending,
    mergePageState,
    pageState.detailId,
    selectedEventSearchParam,
    setSearchParams,
  ])

  useEffect(() => {
    if (authenticationResetPending || reportingPeriodsLoading) {
      return
    }
    const nextReportingPeriodId = revalidateReportingPeriodFilterId(
      reportingPeriods,
      filters.reportingPeriodId,
      reportingPeriodId,
    )
    if (nextReportingPeriodId === filters.reportingPeriodId) {
      return
    }
    let active = true
    void Promise.resolve().then(() => {
      if (active) {
        setFilters((previous) => ({ ...previous, reportingPeriodId: nextReportingPeriodId }))
      }
    })
    return () => {
      active = false
    }
  }, [
    authenticationResetPending,
    filters.reportingPeriodId,
    reportingPeriodId,
    reportingPeriods,
    reportingPeriodsLoading,
    setFilters,
  ])

  useEffect(() => () => {
    requestController.invalidateAll()
  }, [requestController])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(filters.search)
    }, searchDebounceMs)
    return () => window.clearTimeout(timer)
  }, [filters.search])

  useEffect(() => {
    let active = true
    ;(async () => {
      setPostingError(null)
      try {
        const response = await listPostingCodes({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
        })
        if (active) {
          setPostingOptions(response)
        }
      } catch (error) {
        if (active) {
          setPostingOptions([])
          setPostingError(formatUserFacingApiError(error, {
            fallbackMessage: 'Unable to load posting filter options.',
          }))
        }
      }
    })()
    return () => {
      active = false
    }
  }, [adminLevel, authenticationContextVersion, demoAdminId, demoAdminProgrammes])

  const loadEvents = useCallback(async (validatedReportingPeriodId?: string) => {
    return listAdminSecretaryEvents({
      adminId: demoAdminId,
      adminProgrammes: demoAdminProgrammes,
      adminLevel,
      reportingPeriodId: validatedReportingPeriodId,
      postingCode: filters.postingCode === 'all' ? undefined : filters.postingCode,
      dateFrom: filters.dateFrom,
      dateTo: filters.dateTo,
      search: debouncedSearch,
      sourceType: filters.sourceType,
      hasAttendance: toAttendanceParam(filters.hasAttendance),
      limit: pageSize,
      offset,
    })
  }, [
    adminLevel,
    debouncedSearch,
    demoAdminId,
    demoAdminProgrammes,
    filters.dateFrom,
    filters.dateTo,
    filters.hasAttendance,
    filters.postingCode,
    filters.sourceType,
    offset,
  ])

  const fetchEvents = useCallback(async (manual = false) => {
    if (manual) {
      setIsManualRefreshing(true)
    } else if (hasLoadedRef.current) {
      setIsRefetching(true)
    } else {
      setEventsLoading(true)
    }
    setEventsError(null)
    const result = await requestController.runListRequest(
      reportingPeriods,
      filters.reportingPeriodId,
      loadEvents,
    )
    if (result.status === 'stale') {
      return
    }
    if (result.status === 'invalid-period') {
      dispatchPageState({ type: 'invalid-reporting-period', summary: emptySummary })
      setSearchParams((previous) => {
        const next = new URLSearchParams(previous)
        next.delete('event_id')
        return next
      }, { replace: true })
    } else if (result.status === 'error') {
      setEvents([])
      setSummary(emptySummary)
      setTotal(0)
      hasLoadedRef.current = true
      setEventsError(formatUserFacingApiError(result.error, {
        fallbackMessage: 'Unable to load Secretary/PC events.',
      }))
    } else {
      setEvents(result.value.items)
      setSummary(result.value.summary)
      setTotal(result.value.total)
      hasLoadedRef.current = true
    }
    setEventsLoading(false)
    setIsRefetching(false)
    setIsManualRefreshing(false)
  }, [
    filters.reportingPeriodId,
    loadEvents,
    reportingPeriods,
    requestController,
    setEvents,
    setSearchParams,
    setSummary,
    setTotal,
  ])

  useEffect(() => {
    if (authenticationResetPending) {
      return
    }
    let active = true
    void Promise.resolve().then(() => {
      if (active) {
        void fetchEvents(false)
      }
    })
    return () => {
      active = false
      requestController.invalidateList()
    }
  }, [authenticationResetPending, fetchEvents, requestController])

  const resetDeleteConfirmation = useCallback(() => {
    setDeleteConfirmationOpen(false)
    setDeleteReason('')
    setDeleteConfirmation('')
    setDeletePending(false)
    setDeleteError(null)
  }, [])

  const openDetail = (event: AdminSecretaryEventListItem) => {
    if (!canCloseAdminEventDetail(deletePending)) {
      return
    }
    resetDeleteConfirmation()
    setDeleteSuccess(null)
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('event_id', event.id)
    setSearchParams(nextParams, { replace: true })
    setSelectedEvent(event)
    mergePageState({ detailId: event.id })
  }

  const closeDetail = useCallback(() => {
    requestController.invalidateDetail()
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous)
      next.delete('event_id')
      return next
    }, { replace: true })
    setSelectedEvent(null)
    setSelectedDetail(null)
    setDetailError(null)
    resetDeleteConfirmation()
    mergePageState({ detailId: '' })
  }, [
    mergePageState,
    requestController,
    resetDeleteConfirmation,
    setDetailError,
    setSearchParams,
    setSelectedDetail,
    setSelectedEvent,
  ])

  const requestCloseDetail = useCallback(() => {
    if (canCloseAdminEventDetail(deletePending)) {
      closeDetail()
    }
  }, [closeDetail, deletePending])

  useEffect(() => {
    if (authenticationResetPending || !selectedEventId) {
      return
    }

    ;(async () => {
      const result = await requestController.runDetailRequest(() =>
        getAdminSecretaryEvent({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          eventId: selectedEventId,
        }),
      )
      if (result.status === 'success') {
        setSelectedDetail(result.value)
        setSelectedEvent(result.value)
      } else if (result.status === 'error') {
        setDetailError({
          eventId: selectedEventId,
          message: formatUserFacingApiError(result.error, {
            fallbackMessage: 'Unable to load event detail.',
          }),
        })
      }
    })()
  }, [
    adminLevel,
    authenticationResetPending,
    demoAdminId,
    demoAdminProgrammes,
    requestController,
    selectedEventId,
    setDetailError,
    setSelectedDetail,
    setSelectedEvent,
  ])

  const clearFilters = () => {
    setFilters(emptyFilters())
    setDebouncedSearch('')
    setOffset(0)
  }

  const hasFilters =
    filters.reportingPeriodId ||
    filters.postingCode !== 'all' ||
    filters.dateFrom ||
    filters.dateTo ||
    filters.search ||
    filters.sourceType !== 'all' ||
    filters.hasAttendance !== 'all'

  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + events.length, total)
  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < total
  const currentDetail = selectedDetail?.id === selectedEventId ? selectedDetail : null
  const currentDetailError = detailError?.eventId === selectedEventId ? detailError.message : null
  const activeDetail =
    currentDetail ?? (selectedEvent?.id === selectedEventId ? selectedEvent : null)
  const detailLoading = Boolean(selectedEventId) && !currentDetail && !currentDetailError
  const selectedPeriod = useMemo(
    () => reportingPeriods.find((period) => period.id === filters.reportingPeriodId),
    [filters.reportingPeriodId, reportingPeriods],
  )
  const canForceDelete = Boolean(
    role === 'master_admin'
      && currentDetail?.forceDeleteAllowed
      && !currentDetail.isAdhoc,
  )
  const deleteConfirmationValid = isAdminEventForceDeleteConfirmationValid(
    deleteReason,
    deleteConfirmation,
  )

  useEffect(() => {
    if (!deleteConfirmationOpen || !currentDetail) {
      return
    }
    const frame = window.requestAnimationFrame(() => {
      deleteReasonInputRef.current?.scrollIntoView({ block: 'center' })
      deleteReasonInputRef.current?.focus()
    })
    return () => window.cancelAnimationFrame(frame)
  }, [currentDetail, deleteConfirmationOpen])

  const beginDeleteConfirmation = () => {
    setDeleteConfirmationOpen(true)
    setDeleteReason('')
    setDeleteConfirmation('')
    setDeleteError(null)
  }

  const cancelDeleteConfirmation = () => {
    if (!deletePending) {
      resetDeleteConfirmation()
      window.requestAnimationFrame(() => deleteButtonRef.current?.focus())
    }
  }

  const submitForceDelete = async () => {
    if (!currentDetail || !canForceDelete || !deleteConfirmationValid || deletePending) {
      return
    }

    setDeletePending(true)
    setDeleteError(null)
    const mutationResult = await requestController.runMutationRequest(() =>
      forceDeleteAdminSecretaryEvent({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        eventId: currentDetail.id,
        reason: deleteReason.trim(),
        confirmation: deleteConfirmation,
        expectedNativeAttendanceCount: currentDetail.attendanceCounts.native,
        expectedExternalAttendanceCount: currentDetail.attendanceCounts.external,
      }),
    )
    if (mutationResult.status === 'stale') {
      return
    }
    if (mutationResult.status === 'error') {
      setDeleteError(formatUserFacingApiError(mutationResult.error, {
        fallbackMessage: 'Unable to delete this event.',
      }))
      const errorStatus = mutationResult.error && typeof mutationResult.error === 'object'
        ? (mutationResult.error as { status?: unknown }).status
        : undefined
      if (errorStatus === 409) {
        const detailResult = await requestController.runDetailRequest(() =>
          getAdminSecretaryEvent({
            adminId: demoAdminId,
            adminProgrammes: demoAdminProgrammes,
            adminLevel,
            eventId: currentDetail.id,
          }),
        )
        if (detailResult.status === 'stale') {
          return
        }
        if (detailResult.status === 'success') {
          setSelectedDetail(detailResult.value)
          setSelectedEvent(detailResult.value)
          setDeleteConfirmation('')
        }
      }
      setDeletePending(false)
      return
    }

    const result = mutationResult.value
    if (!result.deleted) {
      setDeleteError('The event was not deleted. Please try again.')
      setDeletePending(false)
      return
    }
    setDeleteSuccess(adminEventForceDeleteSuccessMessage(result))
    const nextOffset = adminEventListOffsetAfterDeletion(offset, events.length, pageSize)
    closeDetail()
    if (nextOffset !== offset) {
      setOffset(nextOffset)
    } else {
      await fetchEvents(false)
    }
  }

  if (authenticationResetPending) {
    return null
  }

  return (
    <div className="page admin-secretary-events-page">
      <PageHero
        title="Secretary/PC Events"
        subtitle="Master Admin - review scheduled Secretary and PC teaching events"
        actions={
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void fetchEvents(true)}
            disabled={isManualRefreshing || eventsLoading}
          >
            <IconRefresh size={14} />
            {isManualRefreshing ? 'Refreshing' : 'Refresh'}
          </button>
        }
      />

      <section className="card filter-bar admin-secretary-events-filters">
        <div className="admin-filter-summary">
          <span>Filters</span>
          <strong>{hasFilters ? 'Active filters applied' : 'All Secretary/PC events'}</strong>
        </div>
        <label className="admin-secretary-events-search">
          Search
          <input
            type="search"
            value={filters.search}
            onChange={(event) => updateFilter('search', event.target.value)}
            placeholder="Teaching, posting, SMC code..."
          />
        </label>
        <label>
          Reporting period
          <select
            value={filters.reportingPeriodId}
            onChange={(event) => updateFilter('reportingPeriodId', event.target.value)}
            disabled={reportingPeriodsLoading}
          >
            <option value="">All periods</option>
            {reportingPeriods.map((period) => (
              <option key={period.id} value={period.id}>
                {period.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Posting
          <select
            value={filters.postingCode}
            onChange={(event) => updateFilter('postingCode', event.target.value)}
          >
            <option value="all">All postings</option>
            {postingOptions.map((posting) => (
              <option key={posting.code} value={posting.code}>
                {posting.displayName ? `${posting.code} - ${posting.displayName}` : posting.code}
              </option>
            ))}
          </select>
        </label>
        <label>
          Source
          <select
            value={filters.sourceType}
            onChange={(event) => updateFilter(
              'sourceType',
              event.target.value as AdminSecretaryEventSourceFilter,
            )}
          >
            <option value="all">All sources</option>
            <option value="secretary">Secretary</option>
            <option value="programme_pc">PC</option>
          </select>
        </label>
        <label>
          Attendance
          <select
            value={filters.hasAttendance}
            onChange={(event) => updateFilter('hasAttendance', event.target.value as AttendanceFilter)}
          >
            <option value="all">All events</option>
            <option value="with">With attendance</option>
            <option value="without">Without attendance</option>
          </select>
        </label>
        <label>
          Date from
          <input
            type="date"
            value={filters.dateFrom}
            onChange={(event) => updateFilter('dateFrom', event.target.value)}
          />
        </label>
        <label>
          Date to
          <input
            type="date"
            value={filters.dateTo}
            onChange={(event) => updateFilter('dateTo', event.target.value)}
          />
        </label>
        <div className="admin-secretary-events-filter-actions">
          <button type="button" className="button button-ghost" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      </section>

      {reportingPeriodsError ? (
        <section className="inline-callout callout-warning">
          <span>{reportingPeriodsError}</span>
        </section>
      ) : null}
      {postingError ? (
        <section className="inline-callout callout-warning">
          <span>{postingError}</span>
        </section>
      ) : null}

      <section className="secretary-event-metrics" aria-label="Secretary/PC event counts">
        <MetricTile label="Events" value={summary.totalEvents} />
        <MetricTile label="With attendance" value={summary.withAttendance} />
        <MetricTile label="NHG attendances" value={summary.totalAttendanceCount} />
        <MetricTile label="Non-NHG attendances" value={summary.totalExternalAttendanceCount} />
      </section>

      {deleteSuccess ? (
        <section className="inline-callout callout-success" role="status">
          <span>{deleteSuccess}</span>
        </section>
      ) : null}

      {eventsError && events.length > 0 ? (
        <section className="inline-callout callout-warning">
          <span>{eventsError}</span>
        </section>
      ) : null}

      {eventsLoading ? (
        <section className="card warning-state-card">Loading Secretary/PC events...</section>
      ) : eventsError && events.length === 0 ? (
        <section className="card warning-state-card">
          <strong>Secretary/PC events could not be loaded.</strong>
          <p>{eventsError}</p>
          <button type="button" className="button button-secondary" onClick={() => void fetchEvents(true)}>
            Retry
          </button>
        </section>
      ) : events.length === 0 ? (
        <section className="card warning-state-card">
          <strong>{hasFilters ? 'No Secretary/PC events match these filters' : 'No Secretary/PC events yet'}</strong>
          <p>
            {selectedPeriod
              ? `No scheduled Secretary or PC events are visible for ${selectedPeriod.label}.`
              : 'Scheduled Secretary and PC events will appear here after they are created.'}
          </p>
        </section>
      ) : (
        <section className={`warning-group-card admin-secretary-events-table-card ${isRefetching ? 'is-refetching' : ''}`}>
          <div className="warning-group-header">
            <div>
              <span className="warning-group-kicker">Teaching schedule</span>
              <h2>Secretary/PC scheduled events</h2>
            </div>
            <div className="parsed-data-count-status">
              {isRefetching ? <span className="parsed-data-updating">Refreshing...</span> : null}
              <span className="warning-count-pill">
                {firstItem}-{lastItem} of {total}
              </span>
            </div>
          </div>
          <div className="table-scroll">
            <table className="table admin-secretary-events-table">
              <thead>
                <tr>
                  <th>Teaching</th>
                  <th>Posting</th>
                  <th>Date + time</th>
                  <th>Duration</th>
                  <th>Attendance</th>
                  <th>CME / SMC</th>
                  <th>Session type display</th>
                  <th>Source</th>
                  <th aria-label="Open detail" />
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr
                    key={event.id}
                    className="table-clickable-row"
                    tabIndex={0}
                    onClick={() => openDetail(event)}
                    onKeyDown={(keyboardEvent) => {
                      if (keyboardEvent.key === 'Enter' || keyboardEvent.key === ' ') {
                        keyboardEvent.preventDefault()
                        openDetail(event)
                      }
                    }}
                  >
                    <td>
                      <div className="secretary-event-title-cell">
                        <strong>{event.teachingName}</strong>
                        {event.isRecurring ? <span>Recurring series</span> : null}
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack">
                        <strong>{event.postingCode}</strong>
                        <span>{event.postingDisplayName ?? '-'}</span>
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack">
                        <strong>{formatDate(event.eventDate)}</strong>
                        <span>
                          {formatTime(event.startTime)}-{formatTime(event.endTime)}
                        </span>
                      </div>
                    </td>
                    <td>{formatDuration(event.durationHours)}</td>
                    <td>
                      <div className="secretary-event-stack">
                        <strong>{event.totalAttendanceCount}</strong>
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-badge-stack">
                        <StatusBadge
                          label={event.cmePointsAwarded ? 'CME awarded' : 'No CME'}
                          tone={event.cmePointsAwarded ? 'success' : 'neutral'}
                        />
                        {event.smcEventCode ? (
                          <span className="mono admin-log-compact-text">{event.smcEventCode}</span>
                        ) : null}
                      </div>
                    </td>
                    <td>
                      <div className="secretary-event-stack">
                        <strong>{event.sessionTypeName ?? '-'}</strong>
                      </div>
                    </td>
                    <td className="secretary-event-source-cell">
                      <div className="secretary-event-stack">
                        <StatusBadge
                          label={adminTeachingEventSourceLabel(event.sourceType)}
                          tone={sourceBadgeTone(event)}
                        />
                        {event.sourceType === 'programme_pc' && event.createdForProgrammeCode ? (
                          <span>Owner: {event.createdForProgrammeCode}</span>
                        ) : null}
                      </div>
                    </td>
                    <td className="cell-chevron">
                      <IconChevRight size={14} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="responsive-card-list admin-mobile-record-list admin-secretary-events-mobile-card-list" aria-label="Secretary/PC event cards">
            {events.map((event) => (
              <button
                key={`${event.id}-mobile`}
                type="button"
                className="mobile-record-card admin-mobile-record-card admin-secretary-events-mobile-card"
                onClick={() => openDetail(event)}
                aria-label={`Open Secretary/PC event detail for ${event.teachingName}`}
              >
                <span className="admin-mobile-card-header">
                  <span className="admin-mobile-card-title safe-wrap">{event.teachingName}</span>
                  <StatusBadge
                    label={adminTeachingEventSourceLabel(event.sourceType)}
                    tone={sourceBadgeTone(event)}
                  />
                </span>
                <span className="admin-mobile-card-meta">
                  <span>
                    {compactParts([
                      formatDate(event.eventDate),
                      formatTime(event.startTime),
                      formatDuration(event.durationHours),
                    ])}
                  </span>
                  <span className="admin-mobile-card-source safe-wrap">
                    {compactParts([event.postingCode, event.postingDisplayName])}
                  </span>
                  {event.sourceType === 'programme_pc' && event.createdForProgrammeCode ? (
                    <span className="admin-mobile-card-source safe-wrap">
                      Owner programme: {event.createdForProgrammeCode}
                    </span>
                  ) : null}
                  {event.sessionTypeName ? (
                    <span className="safe-wrap">{event.sessionTypeName}</span>
                  ) : null}
                  <span>
                    NHG {event.nativeAttendanceCount} - Non-NHG {event.externalAttendanceCount} - Total {event.totalAttendanceCount}
                  </span>
                  {event.cmePointsAwarded || event.smcEventCode || event.isRecurring ? (
                    <span className="admin-mobile-card-source safe-wrap">
                      {compactParts([
                        event.cmePointsAwarded ? 'CME awarded' : 'No CME',
                        event.smcEventCode ? `SMC ${event.smcEventCode}` : null,
                        event.isRecurring ? 'Recurring series' : null,
                      ])}
                    </span>
                  ) : null}
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
        title={activeDetail?.teachingName ?? 'Secretary/PC event detail'}
        open={Boolean(selectedEventId)}
        onClose={requestCloseDetail}
        closeDisabled={deletePending}
        busy={deletePending}
        footer={currentDetail && canForceDelete ? (
          deleteConfirmationOpen ? (
            <div className="admin-event-delete-footer-actions">
              <button
                type="button"
                className="button button-secondary"
                onClick={cancelDeleteConfirmation}
                disabled={deletePending}
              >
                Cancel
              </button>
              <button
                type="button"
                className="button button-danger"
                onClick={() => void submitForceDelete()}
                disabled={!deleteConfirmationValid || deletePending}
                aria-label="Permanently delete event and all linked attendance submissions"
              >
                {deletePending ? 'Deleting event...' : 'Permanently delete event'}
              </button>
            </div>
          ) : (
            <button
              ref={deleteButtonRef}
              type="button"
              className="button button-danger"
              onClick={beginDeleteConfirmation}
              aria-label="Delete event and all linked attendance submissions"
            >
              Delete event
            </button>
          )
        ) : undefined}
      >
        {detailLoading ? (
          <div className="warning-detail">
            <div className="detail-block">
              <h3>Event metadata</h3>
              <p>Loading bounded event detail...</p>
            </div>
          </div>
        ) : null}
        {currentDetailError ? (
          <div className="warning-detail">
            <div className="detail-block">
              <h3>Event metadata</h3>
              <p className="inline-muted">{currentDetailError}</p>
            </div>
          </div>
        ) : null}
        {activeDetail && !currentDetailError ? (
          <div className="warning-detail secretary-event-detail">
            <div className="detail-block">
              <div className="admin-log-detail-heading">
                <StatusBadge
                  label={adminTeachingEventSourceLabel(activeDetail.sourceType)}
                  tone={sourceBadgeTone(activeDetail)}
                />
                <StatusBadge
                  label={activeDetail.hasAttendance ? 'Attendance submitted' : 'No submitted attendance'}
                  tone={activeDetail.hasAttendance ? 'success' : 'neutral'}
                />
                {activeDetail.isRecurring ? <StatusBadge label="Recurring" tone="info" /> : null}
              </div>
              <p>
                {activeDetail.postingCode} / {formatDate(activeDetail.eventDate)} / {formatTime(activeDetail.startTime)}
              </p>
            </div>

            <div className="detail-block">
              <h3>Event metadata</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="Event ID" value={activeDetail.id} />
                <DetailField label="Teaching name" value={activeDetail.teachingName} />
                <DetailField label="Date" value={formatDate(activeDetail.eventDate)} />
                <DetailField label="Start time" value={formatTime(activeDetail.startTime)} />
                <DetailField label="End time" value={formatTime(activeDetail.endTime)} />
                <DetailField label="Duration" value={formatDuration(activeDetail.durationHours)} />
                <DetailField label="Created by role" value={activeDetail.createdByRole} />
                <DetailField label="Event mode" value={activeDetail.isAdhoc ? 'Ad-hoc' : 'Scheduled'} />
                <DetailField label="Created at" value={formatDate(activeDetail.createdAt)} />
                {activeDetail.sourceType === 'programme_pc' && activeDetail.createdForProgrammeCode ? (
                  <DetailField label="Owner programme" value={activeDetail.createdForProgrammeCode} />
                ) : null}
              </div>
            </div>

            <div className="detail-block">
              <h3>Posting context</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="Posting code" value={currentDetail?.posting.code ?? activeDetail.postingCode} />
                <DetailField label="Display name" value={currentDetail?.posting.displayName ?? activeDetail.postingDisplayName} />
                <DetailField label="Institution" value={currentDetail?.posting.institution} />
                <DetailField label="Department" value={currentDetail?.posting.department} />
              </div>
            </div>

            <div className="detail-block">
              <h3>Attendance counts</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="NHG attendance" value={currentDetail?.attendanceCounts.native ?? activeDetail.nativeAttendanceCount} />
                <DetailField label="Non-NHG attendance" value={currentDetail?.attendanceCounts.external ?? activeDetail.externalAttendanceCount} />
                <DetailField
                  label="Total attendance"
                  value={
                    currentDetail?.attendanceCounts.total ??
                    activeDetail.totalAttendanceCount
                  }
                />
              </div>
            </div>

            <div className="detail-block">
              <h3>CME and display session type</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="CME points awarded" value={activeDetail.cmePointsAwarded ? 'Yes' : 'No'} />
                <DetailField label="SMC event code" value={activeDetail.smcEventCode} />
                <DetailField label="Session type display" value={activeDetail.sessionTypeName} />
                <DetailField label="Session type id" value={activeDetail.sessionTypeId} />
                <DetailField label="Teaching-name source" value="Programme teaching-name mapping" />
              </div>
            </div>

            <div className="detail-block">
              <h3>Recurrence</h3>
              {currentDetail?.recurrence ? (
                <div className="parsed-data-detail-grid">
                  <DetailField label="Series ID" value={currentDetail.recurrence.seriesId} />
                  <DetailField label="Pattern" value={currentDetail.recurrence.recurrencePattern} />
                  <DetailField label="Interval" value={currentDetail.recurrence.recurrenceInterval} />
                  <DetailField label="Days" value={currentDetail.recurrence.daysOfWeek.join(', ')} />
                  <DetailField label="End type" value={currentDetail.recurrence.endType} />
                  <DetailField label="End date" value={formatDate(currentDetail.recurrence.endDate)} />
                  <DetailField label="End after count" value={currentDetail.recurrence.endAfterCount} />
                </div>
              ) : (
                <p className="inline-muted">This event is not attached to a recurrence series.</p>
              )}
            </div>

            {deleteConfirmationOpen && currentDetail ? (
              <section
                className="detail-block admin-event-delete-confirmation"
                aria-labelledby="admin-event-delete-confirmation-heading"
                aria-live="polite"
                role="region"
              >
                <h3 id="admin-event-delete-confirmation-heading">Confirm permanent deletion</h3>
                <p className="admin-event-delete-warning">
                  This permanently deletes the event and all linked attendance submissions. This action cannot be undone.
                </p>
                <div className="admin-event-delete-impact" aria-label="Attendance deletion impact">
                  <span><strong>{currentDetail.attendanceCounts.native}</strong> NHG Resident attendance submissions</span>
                  <span><strong>{currentDetail.attendanceCounts.external}</strong> Non-NHG Resident attendance submissions</span>
                  <span><strong>{currentDetail.attendanceCounts.total}</strong> total attendance submissions</span>
                </div>
                <label>
                  Deletion reason
                  <textarea
                    ref={deleteReasonInputRef}
                    value={deleteReason}
                    onChange={(event) => setDeleteReason(event.target.value)}
                    rows={3}
                    disabled={deletePending}
                    placeholder="Required operational reason"
                    aria-required="true"
                  />
                </label>
                <label>
                  Type DELETE to confirm
                  <input
                    type="text"
                    value={deleteConfirmation}
                    onChange={(event) => setDeleteConfirmation(event.target.value)}
                    autoComplete="off"
                    spellCheck={false}
                    disabled={deletePending}
                    aria-required="true"
                  />
                </label>
                {deleteError ? (
                  <div className="inline-callout callout-error" role="alert">
                    <span>{deleteError}</span>
                  </div>
                ) : null}
              </section>
            ) : null}
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
