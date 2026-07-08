import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  getAdminLogDetail,
  listAdminLogs,
  type ListAdminLogsParams,
} from '../../api/adminLogs'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'
import type { UploadType } from '../../types/app'
import type {
  AdminLogAction,
  AdminLogDeepLink,
  AdminLogDetailResponse,
  AdminLogListItem,
  AdminLogType,
} from '../../types/adminLogs'
import {
  clearMemoryCache,
  getMemoryCache,
  makeScopedCacheKey,
  readThroughMemoryCache,
  setMemoryCache,
  type CacheScope,
} from '../../utils/memoryReadCache'

type BadgeTone = 'success' | 'warning' | 'critical' | 'info' | 'neutral'

interface AdminLogFilterState {
  logType: AdminLogType | 'all'
  actorRole: string
  uploadType: UploadType | 'all'
  warningType: string
  actorUserId: string
  entityType: string
  entityId: string
  programmeCode: string
  reportingPeriodId: string
  status: string
  outcome: string
  dateFrom: string
  dateTo: string
  correctionType: string
  configEntityType: string
}

const pageSize = 50
const searchDebounceMs = 300
const evidencePreviewLimit = 4800

const logTypeLabels: Record<AdminLogType, string> = {
  upload: 'Upload',
  warning: 'Warning',
  warning_action: 'Warning action',
  source_cell_correction: 'Source-cell correction',
  parsed_data_correction: 'Parsed-data correction',
  config_mutation: 'Config mutation',
  data_revalidation: 'Data revalidation',
}

const logTypeOrder: AdminLogType[] = [
  'upload',
  'warning',
  'warning_action',
  'source_cell_correction',
  'parsed_data_correction',
  'config_mutation',
  'data_revalidation',
]

const uploadTypeLabels: Record<UploadType, string> = {
  rdb: 'RDB',
  form_f1: 'FormF1',
  ttf: 'TTF',
  public_holidays: 'Public Holidays / AY Dates',
}

const uploadTypeOrder: UploadType[] = ['rdb', 'form_f1', 'ttf', 'public_holidays']

const actorRoleOptions = [
  'master_admin',
  'programme_pc',
  'admin',
  'secretary',
  'resident',
  'external_resident',
]

const actorRoleLabels: Record<string, string> = {
  master_admin: 'Master Admin',
  programme_pc: 'PC',
  admin: 'Admin',
  secretary: 'Secretary',
  resident: 'NHG Resident',
  external_resident: 'Non-NHG Resident',
}

const statusOptions = [
  'success',
  'partial',
  'failed',
  'unresolved',
  'resolved',
  'dismissed',
  'superseded',
  'reappeared',
]

const outcomeOptions = [
  'no_op',
  'warning_only',
  'targeted_revalidation',
  'future_compliance_impact',
  'manual_revalidation_required',
]

const formatDateTime = (iso?: string | null) => {
  if (!iso) {
    return '-'
  }
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) {
    return iso
  }
  return parsed.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

const fieldValue = (value?: string | number | null) => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  return String(value)
}

const normalizeParam = (value: string | null) => value?.trim() ?? ''

const parseLogType = (value: string | null): AdminLogType | 'all' => {
  const text = normalizeParam(value)
  return logTypeOrder.find((item) => item === text) ?? 'all'
}

const parseUploadType = (value: string | null): UploadType | 'all' => {
  const text = normalizeParam(value)
  return uploadTypeOrder.find((item) => item === text) ?? 'all'
}

const parseOffset = (value: string | null) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

const searchValue = (value: unknown): string | null => {
  if (typeof value === 'string') {
    const text = value.trim()
    return text || null
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value)
  }
  return null
}

const withQuery = (path: string, query?: Record<string, unknown>) => {
  const params = new URLSearchParams()
  Object.entries(query ?? {}).forEach(([key, value]) => {
    const text = searchValue(value)
    if (text) {
      params.set(key, text)
    }
  })
  const queryString = params.toString()
  return queryString ? `${path}?${queryString}` : path
}

const sourceText = (log: AdminLogListItem) => {
  const source = log.source_ref
  const parts = [
    source?.sheet_name,
    source?.row_number ? `row ${source.row_number}` : null,
    source?.cell_ref,
  ].filter(Boolean)
  if (parts.length > 0) {
    return parts.join(' · ')
  }
  if (log.upload_log_id) {
    return 'Upload record'
  }
  if (log.warning_issue_id) {
    return 'Warning issue'
  }
  return '-'
}

const actorText = (log: AdminLogListItem) => {
  return (
    log.actor_name ??
    log.actor_user_id ??
    labelForActorRole(log.actor_role) ??
    labelForActorRole(log.stored_actor_role) ??
    'Unknown actor'
  )
}

const entityText = (log: AdminLogListItem) => {
  if (log.entity_type === 'upload_log') {
    return 'Upload log'
  }
  if (log.entity_type === 'warning_issue') {
    return 'Warning issue'
  }
  const entity = [log.entity_type, log.entity_id].filter(Boolean).join(' · ')
  if (entity) {
    return entity
  }
  if (log.warning_issue_id) {
    return 'Warning issue'
  }
  if (log.upload_log_id) {
    return 'Upload log'
  }
  return '-'
}

const labelForLogType = (logType: AdminLogType) => logTypeLabels[logType] ?? logType

const labelForUploadType = (uploadType?: UploadType | null) =>
  uploadType ? uploadTypeLabels[uploadType] ?? uploadType : null

const labelForActorRole = (actorRole?: string | null) =>
  actorRole ? actorRoleLabels[actorRole] ?? actorRole : null

const statusTone = (value?: string | null): BadgeTone => {
  const text = value?.toLowerCase()
  if (!text) {
    return 'neutral'
  }
  if (text.includes('fail') || text.includes('manual')) {
    return 'critical'
  }
  if (text.includes('partial') || text.includes('warning') || text.includes('reappeared')) {
    return 'warning'
  }
  if (text.includes('success') || text.includes('resolved') || text.includes('no_op')) {
    return 'success'
  }
  if (text.includes('targeted') || text.includes('impact')) {
    return 'info'
  }
  return 'neutral'
}

const formatAuditStatus = (value: string) =>
  value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())

const formatWorkflowStatus = (workflowStatus?: Record<string, unknown> | null) => {
  const status = searchValue(workflowStatus?.status)
  return status ? formatAuditStatus(status) : null
}

const typeTone = (logType: AdminLogType): BadgeTone => {
  if (logType === 'warning' || logType === 'warning_action') {
    return 'warning'
  }
  if (logType === 'config_mutation' || logType === 'data_revalidation') {
    return 'info'
  }
  if (logType.includes('correction')) {
    return 'neutral'
  }
  return 'success'
}

const routeIsDirectPath = (route: string) => route.startsWith('/admin/') || route.startsWith('/pc/')

const resolveDeepLinkPath = (
  deepLink: AdminLogDeepLink | null | undefined,
  log: AdminLogListItem,
  action?: AdminLogAction,
) => {
  if (action?.action === 'view_raw_summary' || action?.action === 'download_raw_audit') {
    return null
  }

  const route = deepLink?.route ?? ''
  if (routeIsDirectPath(route) && route !== '/admin/logs') {
    return withQuery(route, deepLink?.query)
  }

  const routeHint = route.toLowerCase()
  if (routeHint.includes('warning') || log.warning_issue_id || log.upload_warning_id) {
    const query: Record<string, unknown> = { mode: 'history' }
    if (log.warning_issue_id) {
      query.warning_issue_id = log.warning_issue_id
    }
    if (log.upload_warning_id) {
      query.upload_warning_id = log.upload_warning_id
    }
    if (log.upload_type) {
      query.upload_type = log.upload_type
    }
    return withQuery('/admin/upload/warnings', query)
  }

  if (
    routeHint.includes('parsed') ||
    log.log_type === 'source_cell_correction' ||
    log.log_type === 'parsed_data_correction'
  ) {
    return withQuery('/admin/parsed-data', deepLink?.query)
  }

  if (routeHint.includes('config') || log.log_type === 'config_mutation') {
    return withQuery('/admin/config', deepLink?.query)
  }

  if (routeHint.includes('upload') || log.upload_log_id || log.log_type === 'upload') {
    const query = log.upload_log_id ? { search: log.upload_log_id } : deepLink?.query
    return withQuery('/admin/upload-logs', query)
  }

  return null
}

const initialFiltersFromParams = (params: URLSearchParams): AdminLogFilterState => ({
  logType: parseLogType(params.get('log_type')),
  actorRole: normalizeParam(params.get('actor_role')) || 'all',
  uploadType: parseUploadType(params.get('upload_type')),
  warningType: normalizeParam(params.get('warning_type')),
  actorUserId: normalizeParam(params.get('actor_user_id')),
  entityType: normalizeParam(params.get('entity_type')),
  entityId: normalizeParam(params.get('entity_id')),
  programmeCode: normalizeParam(params.get('programme_code')) || 'all',
  reportingPeriodId: normalizeParam(params.get('reporting_period_id')),
  status: normalizeParam(params.get('status')) || 'all',
  outcome: normalizeParam(params.get('outcome')) || 'all',
  dateFrom: normalizeParam(params.get('date_from')),
  dateTo: normalizeParam(params.get('date_to')),
  correctionType: normalizeParam(params.get('correction_type')),
  configEntityType: normalizeParam(params.get('config_entity_type')),
})

const buildSearchParams = (
  filters: AdminLogFilterState,
  searchTerm: string,
  offset: number,
) => {
  const params = new URLSearchParams()
  if (filters.logType !== 'all') {
    params.set('log_type', filters.logType)
  }
  if (filters.actorRole && filters.actorRole !== 'all') {
    params.set('actor_role', filters.actorRole)
  }
  if (filters.uploadType !== 'all') {
    params.set('upload_type', filters.uploadType)
  }
  if (filters.programmeCode && filters.programmeCode !== 'all') {
    params.set('programme_code', filters.programmeCode)
  }
  if (filters.status && filters.status !== 'all') {
    params.set('status', filters.status)
  }
  if (filters.outcome && filters.outcome !== 'all') {
    params.set('outcome', filters.outcome)
  }

  const simpleFilters: Array<[string, string]> = [
    ['actor_user_id', filters.actorUserId],
    ['warning_type', filters.warningType],
    ['entity_type', filters.entityType],
    ['entity_id', filters.entityId],
    ['reporting_period_id', filters.reportingPeriodId],
    ['date_from', filters.dateFrom],
    ['date_to', filters.dateTo],
    ['correction_type', filters.correctionType],
    ['config_entity_type', filters.configEntityType],
    ['search', searchTerm],
  ]

  simpleFilters.forEach(([key, value]) => {
    const text = value.trim()
    if (text) {
      params.set(key, text)
    }
  })

  if (offset > 0) {
    params.set('offset', String(offset))
  }

  return params
}

const JsonPreview = ({
  title,
  value,
  emptyText,
}: {
  title: string
  value?: unknown
  emptyText?: string
}) => {
  const json = useMemo(() => JSON.stringify(value ?? {}, null, 2), [value])
  const hasContent = json !== '{}'
  if (!hasContent) {
    return emptyText ? (
      <div className="admin-log-empty-evidence">
        <strong>{title}</strong>
        <p>{emptyText}</p>
      </div>
    ) : null
  }
  const isTruncated = json.length > evidencePreviewLimit
  const preview = isTruncated ? `${json.slice(0, evidencePreviewLimit)}\n... truncated` : json
  return (
    <details className="admin-log-json-section">
      <summary>
        {title}
        {isTruncated ? <span>Preview truncated</span> : null}
      </summary>
      <pre className="raw-json admin-log-json-preview">{preview}</pre>
    </details>
  )
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

export const AdminLogsPage = () => {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const currentQueryString = searchParams.toString()
  const {
    role,
    demoAdminId,
    demoAdminProgrammes,
    reportingPeriods,
  } = useAppState()
  const [logs, setLogs] = useState<AdminLogListItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(() => parseOffset(searchParams.get('offset')))
  const [filters, setFilters] = useState<AdminLogFilterState>(() => initialFiltersFromParams(searchParams))
  const [searchTerm, setSearchTerm] = useState(() => normalizeParam(searchParams.get('search')))
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState(() => normalizeParam(searchParams.get('search')))
  const [isInitialLoading, setIsInitialLoading] = useState(true)
  const [isRefetching, setIsRefetching] = useState(false)
  const [isManualRefreshing, setIsManualRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedLog, setSelectedLog] = useState<AdminLogListItem | null>(null)
  const [selectedDetail, setSelectedDetail] = useState<AdminLogDetailResponse | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const hasLoadedLogsRef = useRef(false)
  const detailRequestRef = useRef(0)

  const adminLevel = role === 'programme_pc' ? 'programme' : 'master'

  const cacheScope = useMemo<CacheScope>(() => ({
    role,
    userId: demoAdminId,
    programmeScope: demoAdminProgrammes,
  }), [demoAdminId, demoAdminProgrammes, role])

  const updateFilter = <Key extends keyof AdminLogFilterState>(
    key: Key,
    value: AdminLogFilterState[Key],
  ) => {
    setFilters((previous) => ({
      ...previous,
      [key]: value,
    }))
    setOffset(0)
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearchTerm((previous) => (previous === searchTerm ? previous : searchTerm))
    }, searchDebounceMs)
    return () => window.clearTimeout(timer)
  }, [searchTerm])

  useEffect(() => {
    const nextParams = buildSearchParams(filters, searchTerm, offset)
    const nextQueryString = nextParams.toString()
    if (nextQueryString !== currentQueryString) {
      setSearchParams(nextParams, { replace: true })
    }
  }, [currentQueryString, filters, offset, searchTerm, setSearchParams])

  const requestFilters = useCallback((
    querySearch: string,
  ): Omit<ListAdminLogsParams, 'adminId' | 'adminProgrammes' | 'adminLevel'> => ({
    logType: filters.logType,
    actorUserId: filters.actorUserId,
    actorRole: filters.actorRole,
    uploadType: filters.uploadType,
    warningType: filters.warningType,
    entityType: filters.entityType,
    entityId: filters.entityId,
    programmeCode: filters.programmeCode,
    reportingPeriodId: filters.reportingPeriodId,
    status: filters.status,
    outcome: filters.outcome,
    dateFrom: filters.dateFrom,
    dateTo: filters.dateTo,
    search: querySearch,
    correctionType: filters.correctionType,
    configEntityType: filters.configEntityType,
    limit: pageSize,
    offset,
  }), [filters, offset])

  const adminLogsCacheKey = useCallback((querySearch: string) => makeScopedCacheKey(
    cacheScope,
    'admin.logs.list',
    requestFilters(querySearch),
  ), [cacheScope, requestFilters])

  const loadLogs = useCallback(async (querySearch: string) => {
    return listAdminLogs({
      adminId: demoAdminId,
      adminProgrammes: demoAdminProgrammes,
      adminLevel,
      ...requestFilters(querySearch),
    })
  }, [adminLevel, demoAdminId, demoAdminProgrammes, requestFilters])

  const fetchLogs = useCallback(async () => {
    setIsManualRefreshing(true)
    setError(null)
    try {
      const key = adminLogsCacheKey(searchTerm)
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
      setError(fetchError instanceof Error ? fetchError.message : 'Unable to load admin logs.')
    } finally {
      setIsManualRefreshing(false)
      setIsInitialLoading(false)
      setIsRefetching(false)
    }
  }, [adminLogsCacheKey, loadLogs, searchTerm])

  useEffect(() => {
    let active = true
    ;(async () => {
      const key = adminLogsCacheKey(debouncedSearchTerm)
      const cached = getMemoryCache<Awaited<ReturnType<typeof listAdminLogs>>>(key)
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
          setError(fetchError instanceof Error ? fetchError.message : 'Unable to load admin logs.')
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
  }, [adminLogsCacheKey, debouncedSearchTerm, loadLogs])

  const programmeOptions = useMemo(() => {
    return Array.from(
      new Set(
        [...demoAdminProgrammes, ...logs.map((log) => log.programme_code ?? '')]
          .map((item) => item.trim())
          .filter(Boolean),
      ),
    ).sort()
  }, [demoAdminProgrammes, logs])

  const activeDetail = selectedDetail?.list_item ?? selectedLog
  const primaryDeepLink = activeDetail
    ? resolveDeepLinkPath(activeDetail.deep_link, activeDetail)
    : null
  const workflowStatusText = selectedDetail ? formatWorkflowStatus(selectedDetail.workflow_status) : null
  const technicalDetailFields = activeDetail
    ? [
        { label: 'Log ID', value: activeDetail.id },
        { label: 'Upload log UUID', value: activeDetail.upload_log_id },
        { label: 'Warning issue UUID', value: activeDetail.warning_issue_id },
        { label: 'Upload warning UUID', value: activeDetail.upload_warning_id },
        { label: 'Entity ID', value: activeDetail.entity_id },
      ].filter((field) => field.value)
    : []

  const hasFilters = useMemo(() => {
    const filterValues = Object.values(filters)
    return filterValues.some((value) => value && value !== 'all') || searchTerm.trim().length > 0
  }, [filters, searchTerm])

  const clearFilters = () => {
    setFilters({
      logType: 'all',
      actorRole: 'all',
      uploadType: 'all',
      warningType: '',
      actorUserId: '',
      entityType: '',
      entityId: '',
      programmeCode: 'all',
      reportingPeriodId: '',
      status: 'all',
      outcome: 'all',
      dateFrom: '',
      dateTo: '',
      correctionType: '',
      configEntityType: '',
    })
    setSearchTerm('')
    setOffset(0)
  }

  const openDetail = (log: AdminLogListItem) => {
    const requestId = detailRequestRef.current + 1
    detailRequestRef.current = requestId
    setSelectedLog(log)
    setSelectedDetail(null)
    setDetailError(null)
    setDetailLoading(true)

    ;(async () => {
      try {
        const detail = await getAdminLogDetail({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          logId: log.id,
        })
        if (detailRequestRef.current === requestId) {
          setSelectedDetail(detail)
        }
      } catch (detailFetchError) {
        if (detailRequestRef.current === requestId) {
          setDetailError(
            detailFetchError instanceof Error
              ? detailFetchError.message
              : 'Unable to load admin log detail.',
          )
        }
      } finally {
        if (detailRequestRef.current === requestId) {
          setDetailLoading(false)
        }
      }
    })()
  }

  const closeDetail = () => {
    detailRequestRef.current += 1
    setSelectedLog(null)
    setSelectedDetail(null)
    setDetailError(null)
    setDetailLoading(false)
  }

  const openPath = (path: string | null) => {
    if (path) {
      navigate(path)
    }
  }

  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + logs.length, total)
  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < total

  return (
    <div className="page admin-logs-page">
      <PageHero
        title="Admin Logs"
        subtitle="Uploads, warnings, corrections, config changes, and revalidation activity"
      />

      <section className="card filter-bar warning-filter-card admin-logs-filter-card">
        <div className="admin-filter-summary">
          <span>Filters</span>
          <strong>{hasFilters ? 'Active filters applied' : 'All admin logs'}</strong>
        </div>
        <label className="admin-logs-search-field">
          Search logs
          <input
            type="search"
            value={searchTerm}
            onChange={(event) => {
              setSearchTerm(event.target.value)
              setOffset(0)
            }}
            placeholder="Title, actor, source, MCR..."
          />
        </label>
        <label>
          Type
          <select
            value={filters.logType}
            onChange={(event) => updateFilter('logType', event.target.value as AdminLogType | 'all')}
          >
            <option value="all">All types</option>
            {logTypeOrder.map((logType) => (
              <option key={logType} value={logType}>
                {logTypeLabels[logType]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Programme
          <select
            value={filters.programmeCode}
            onChange={(event) => updateFilter('programmeCode', event.target.value)}
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
          Reporting period
          <select
            value={filters.reportingPeriodId}
            onChange={(event) => updateFilter('reportingPeriodId', event.target.value)}
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
          Status
          <select
            value={filters.status}
            onChange={(event) => updateFilter('status', event.target.value)}
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
          Outcome
          <select
            value={filters.outcome}
            onChange={(event) => updateFilter('outcome', event.target.value)}
          >
            <option value="all">All outcomes</option>
            {outcomeOptions.map((outcome) => (
              <option key={outcome} value={outcome}>
                {outcome}
              </option>
            ))}
          </select>
        </label>
        <label>
          Upload type
          <select
            value={filters.uploadType}
            onChange={(event) => updateFilter('uploadType', event.target.value as UploadType | 'all')}
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
          Actor role
          <select
            value={filters.actorRole}
            onChange={(event) => updateFilter('actorRole', event.target.value)}
          >
            <option value="all">All roles</option>
            {actorRoleOptions.map((actorRole) => (
              <option key={actorRole} value={actorRole}>
                {labelForActorRole(actorRole)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Date from
          <input
            type="datetime-local"
            value={filters.dateFrom}
            onChange={(event) => updateFilter('dateFrom', event.target.value)}
          />
        </label>
        <label>
          Date to
          <input
            type="datetime-local"
            value={filters.dateTo}
            onChange={(event) => updateFilter('dateTo', event.target.value)}
          />
        </label>
        <div className="admin-logs-filter-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void fetchLogs()}
            disabled={isManualRefreshing || isInitialLoading}
          >
            <IconRefresh size={14} />
            {isManualRefreshing ? 'Refreshing' : 'Refresh'}
          </button>
          <button type="button" className="button button-ghost" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
        <details className="admin-logs-advanced-filters">
          <summary>Advanced filters</summary>
          <div className="admin-logs-advanced-grid">
            <label>
              Warning type
              <input
                value={filters.warningType}
                onChange={(event) => updateFilter('warningType', event.target.value)}
                placeholder="unmatched_multi_posting"
              />
            </label>
            <label>
              Actor user ID
              <input
                value={filters.actorUserId}
                onChange={(event) => updateFilter('actorUserId', event.target.value)}
                placeholder="UUID"
              />
            </label>
            <label>
              Entity type
              <input
                value={filters.entityType}
                onChange={(event) => updateFilter('entityType', event.target.value)}
                placeholder="resident_posting"
              />
            </label>
            <label>
              Entity ID
              <input
                value={filters.entityId}
                onChange={(event) => updateFilter('entityId', event.target.value)}
                placeholder="UUID or source id"
              />
            </label>
            <label>
              Correction type
              <input
                value={filters.correctionType}
                onChange={(event) => updateFilter('correctionType', event.target.value)}
                placeholder="source_cell_replace"
              />
            </label>
            <label>
              Config entity type
              <input
                value={filters.configEntityType}
                onChange={(event) => updateFilter('configEntityType', event.target.value)}
                placeholder="posting_group"
              />
            </label>
          </div>
        </details>
      </section>

      {error && logs.length > 0 ? (
        <section className="inline-callout callout-warning upload-log-inline-error">
          <span>{error}</span>
        </section>
      ) : null}

      {isInitialLoading ? (
        <section className="card warning-state-card">Loading admin logs...</section>
      ) : error && logs.length === 0 ? (
        <section className="card warning-state-card">
          <strong>Admin logs could not be loaded.</strong>
          <p>{error}</p>
          <button type="button" className="button button-secondary" onClick={() => void fetchLogs()}>
            Retry
          </button>
        </section>
      ) : logs.length === 0 ? (
        <section className="card warning-state-card">
          <strong>{hasFilters ? 'No admin logs match these filters' : 'No admin logs yet'}</strong>
          <p>
            {hasFilters
              ? 'Clear filters or adjust the search to review the audit trail.'
              : 'Uploads, warnings, corrections, config mutations, and revalidation entries will appear here.'}
          </p>
        </section>
      ) : (
        <section className={`warning-group-card admin-logs-table-card ${isRefetching ? 'is-refetching' : ''}`}>
          <div className="warning-group-header">
            <div>
              <span className="warning-group-kicker">Audit trail</span>
              <h2>Unified admin logs</h2>
            </div>
            <div className="parsed-data-count-status">
              {isRefetching ? <span className="parsed-data-updating">Refreshing...</span> : null}
              <span className="warning-count-pill">
                {firstItem}-{lastItem} of {total}
              </span>
            </div>
          </div>
          <div className="table-scroll">
            <table className="table admin-logs-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Type</th>
                  <th>Title + summary</th>
                  <th>Actor</th>
                  <th>Programme</th>
                  <th>Entity</th>
                  <th>Status + outcome</th>
                  <th>Source</th>
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
                    <td>{formatDateTime(log.occurred_at)}</td>
                    <td>
                      <StatusBadge label={labelForLogType(log.log_type)} tone={typeTone(log.log_type)} />
                      {log.upload_type ? (
                        <span className="admin-log-secondary-chip">{labelForUploadType(log.upload_type)}</span>
                      ) : null}
                    </td>
                    <td>
                      <div className="admin-log-title-cell">
                        <strong>{log.title}</strong>
                        <span>{log.summary || '-'}</span>
                      </div>
                    </td>
                    <td>
                      <div className="admin-log-stack">
                        <strong>{actorText(log)}</strong>
                        <span>{fieldValue(labelForActorRole(log.actor_role ?? log.stored_actor_role))}</span>
                      </div>
                    </td>
                    <td>{fieldValue(log.programme_code ?? 'Global')}</td>
                    <td>
                      <span className="admin-log-compact-text">{entityText(log)}</span>
                    </td>
                    <td>
                      <div className="admin-log-badge-stack">
                        {log.status ? <StatusBadge label={log.status} tone={statusTone(log.status)} /> : null}
                        {log.outcome ? <StatusBadge label={log.outcome} tone={statusTone(log.outcome)} /> : null}
                        {!log.status && !log.outcome ? <span className="muted-text">-</span> : null}
                      </div>
                    </td>
                    <td>
                      <span className="admin-log-compact-text">{sourceText(log)}</span>
                    </td>
                    <td className="cell-chevron">
                      <IconChevRight size={14} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="responsive-card-list admin-mobile-record-list admin-log-mobile-card-list" aria-label="Admin log cards">
            {logs.map((log) => (
              <button
                key={`${log.id}-mobile`}
                type="button"
                className="mobile-record-card admin-mobile-record-card admin-log-mobile-card"
                onClick={() => openDetail(log)}
                aria-label={`Open admin log detail for ${log.title}`}
              >
                <span className="admin-mobile-card-header">
                  <span className="admin-mobile-card-title safe-wrap">{log.title}</span>
                  <StatusBadge label={labelForLogType(log.log_type)} tone={typeTone(log.log_type)} />
                </span>
                <span className="admin-mobile-card-meta">
                  <span>{formatDateTime(log.occurred_at)} - {actorText(log)}</span>
                  <span>
                    {fieldValue(labelForActorRole(log.actor_role ?? log.stored_actor_role))}
                    {' - '}
                    {fieldValue(log.programme_code ?? 'Global')}
                  </span>
                  {log.summary ? <span className="safe-wrap">{log.summary}</span> : null}
                  <span className="admin-mobile-card-source safe-wrap">
                    {entityText(log)} - {sourceText(log)}
                  </span>
                </span>
                <span className="admin-mobile-card-badges">
                  {log.upload_type ? (
                    <StatusBadge label={labelForUploadType(log.upload_type) ?? log.upload_type} tone="neutral" />
                  ) : null}
                  {log.status ? <StatusBadge label={log.status} tone={statusTone(log.status)} /> : null}
                  {log.outcome ? <StatusBadge label={log.outcome} tone={statusTone(log.outcome)} /> : null}
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
        title={activeDetail?.title ?? 'Admin log detail'}
        open={Boolean(selectedLog)}
        onClose={closeDetail}
        footer={
          activeDetail ? (
            <button
              type="button"
              className="button button-primary"
              onClick={() => openPath(primaryDeepLink)}
              disabled={!primaryDeepLink}
            >
              {primaryDeepLink ? 'Open related surface' : 'Deep link not wired'}
            </button>
          ) : null
        }
      >
        {activeDetail ? (
          <div className="warning-detail admin-log-detail">
            <div className="detail-block">
              <div className="admin-log-detail-heading">
                <StatusBadge label={labelForLogType(activeDetail.log_type)} tone={typeTone(activeDetail.log_type)} />
                {activeDetail.status ? (
                  <StatusBadge label={activeDetail.status} tone={statusTone(activeDetail.status)} />
                ) : null}
                {activeDetail.outcome ? (
                  <StatusBadge label={activeDetail.outcome} tone={statusTone(activeDetail.outcome)} />
                ) : null}
              </div>
              <p>{activeDetail.summary || '-'}</p>
            </div>

            <div className="detail-block">
              <h3>Log detail</h3>
              <div className="parsed-data-detail-grid">
                <DetailField label="Occurred at" value={formatDateTime(activeDetail.occurred_at)} />
                <DetailField label="Actor" value={actorText(activeDetail)} />
                <DetailField label="Actor role" value={labelForActorRole(activeDetail.actor_role ?? activeDetail.stored_actor_role)} />
                <DetailField label="Programme" value={activeDetail.programme_code ?? 'Global'} />
                <DetailField label="Reporting period" value={activeDetail.reporting_period_id} />
                <DetailField label="Entity" value={entityText(activeDetail)} />
                <DetailField label="Source" value={sourceText(activeDetail)} />
                {selectedDetail ? (
                  <DetailField label="Workflow status" value={workflowStatusText ?? 'No workflow status returned'} />
                ) : null}
              </div>
            </div>

            {technicalDetailFields.length > 0 ? (
              <details className="detail-block admin-log-support-details">
                <summary>Technical details</summary>
                <div className="parsed-data-detail-grid">
                  {technicalDetailFields.map((field) => (
                    <DetailField key={field.label} label={field.label} value={field.value} />
                  ))}
                </div>
              </details>
            ) : null}

            {detailLoading ? (
              <div className="detail-block">
                <h3>Evidence</h3>
                <p>Loading bounded audit evidence...</p>
              </div>
            ) : null}

            {detailError ? (
              <div className="detail-block">
                <h3>Evidence</h3>
                <p className="inline-muted">{detailError}</p>
              </div>
            ) : null}

            {selectedDetail ? (
              <>
                <div className="detail-block">
                  <h3>Related entities</h3>
                  {selectedDetail.related_entities.length === 0 ? (
                    <p className="inline-muted">No related entities were returned.</p>
                  ) : (
                    <div className="admin-log-related-list">
                      {selectedDetail.related_entities.map((entity, index) => {
                        const path = resolveDeepLinkPath(entity.deep_link, activeDetail)
                        return (
                          <div key={`${entity.entity_type}-${entity.entity_id ?? index}`} className="admin-log-related-card">
                            <div>
                              <strong>{entity.label}</strong>
                              <span>
                                {entity.relationship} · {entity.entity_type}
                                {entity.entity_id ? ` · ${entity.entity_id}` : ''}
                              </span>
                            </div>
                            <button
                              type="button"
                              className="button button-secondary"
                              disabled={!path}
                              onClick={() => openPath(path)}
                            >
                              {path ? 'Open' : 'Not wired'}
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>

                <div className="detail-block">
                  <h3>Available actions</h3>
                  {selectedDetail.available_actions.length === 0 ? (
                    <p className="inline-muted">No actions were returned for this log entry.</p>
                  ) : (
                    <div className="admin-log-action-list">
                      {selectedDetail.available_actions.map((action) => {
                        const path = resolveDeepLinkPath(action.deep_link, activeDetail, action)
                        const rawAction =
                          action.action === 'view_raw_summary' || action.action === 'download_raw_audit'
                        return (
                          <div key={`${action.action}-${action.endpoint ?? action.label}`} className="admin-log-action-card">
                            <div>
                              <strong>{action.label}</strong>
                              <span>
                                {rawAction
                                  ? 'Raw audit payloads are not fetched by default.'
                                  : action.endpoint ?? 'Route metadata only'}
                              </span>
                            </div>
                            <button
                              type="button"
                              className="button button-secondary"
                              disabled={!path}
                              onClick={() => openPath(path)}
                            >
                              {path ? 'Open' : 'Not wired'}
                            </button>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>

                <div className="detail-block">
                  <h3>Immutable evidence</h3>
                  <JsonPreview
                    title="Bounded evidence preview"
                    value={selectedDetail.immutable_evidence}
                    emptyText="No immutable evidence was returned for this log entry."
                  />
                </div>
              </>
            ) : null}
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
