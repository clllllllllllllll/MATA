import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  listParsedAcademicMonthBoundaries,
  listParsedFormF1Records,
  listParsedPublicHolidays,
  listParsedResidentPostings,
  listParsedResidents,
  listParsedTeachingNameCatalogue,
  listParsedTeachingTargets,
} from '../../api/parsedData'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'
import type {
  AyDateCategory,
  ParsedAcademicMonthBoundaryRow,
  ParsedDataListResponse,
  ParsedDataRow,
  ParsedFormF1RecordRow,
  ParsedPublicHolidayRow,
  ParsedResidentPostingRow,
  ParsedResidentRow,
  ParsedTeachingNameCatalogueRow,
  ParsedTeachingTargetRow,
} from '../../types/parsedData'

type ParsedDataTabId =
  | 'residents'
  | 'resident-postings'
  | 'teaching-targets'
  | 'teaching-name-catalogue'
  | 'form-f1-records'
  | 'public-holidays'
  | 'academic-month-boundaries'

type FilterKey =
  | 'programmeCode'
  | 'reportingPeriodId'
  | 'postingCode'
  | 'mcr'
  | 'status'
  | 'monthLabel'
  | 'search'
  | 'rYear'
  | 'sessionType'
  | 'isTracked'
  | 'keyword'
  | 'isActive'
  | 'year'
  | 'academicYearLabel'
  | 'ayDateCategory'

interface ParsedDataFilters {
  programmeCode: string
  reportingPeriodId: string
  postingCode: string
  mcr: string
  status: string
  monthLabel: string
  search: string
  rYear: string
  sessionType: string
  isTracked: 'all' | 'true' | 'false'
  keyword: string
  isActive: 'all' | 'true' | 'false'
  year: string
  academicYearLabel: string
  ayDateCategory: 'all' | AyDateCategory
}

interface FilterDefinition {
  key: FilterKey
  label: string
  type?: 'text' | 'search' | 'select'
  placeholder?: string
}

interface ParsedColumn {
  label: string
  className?: string
  value: (row: ParsedDataRow) => ReactNode
}

interface ParsedTabDefinition {
  id: ParsedDataTabId
  label: string
  filters: FilterDefinition[]
  columns: ParsedColumn[]
  minWidth: number
}

const pageSize = 25
const filterDebounceMs = 300

const initialFilters: ParsedDataFilters = {
  programmeCode: '',
  reportingPeriodId: '',
  postingCode: '',
  mcr: '',
  status: '',
  monthLabel: '',
  search: '',
  rYear: '',
  sessionType: '',
  isTracked: 'all',
  keyword: '',
  isActive: 'all',
  year: '',
  academicYearLabel: '',
  ayDateCategory: 'all',
}

const filterKeys = Object.keys(initialFilters) as FilterKey[]

const areFiltersEqual = (left: ParsedDataFilters, right: ParsedDataFilters) =>
  filterKeys.every((key) => left[key] === right[key])

const formatValue = (value?: string | number | boolean | null) => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No'
  }
  return String(value)
}

const formatDate = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

const formatNumber = (value?: number | null) => {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '-'
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

const humanizeKey = (key: string) =>
  key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/\bId\b/g, 'ID')
    .replace(/\bMcr\b/g, 'MCR')
    .replace(/\bAy\b/g, 'AY')
    .replace(/\bLoa\b/g, 'LOA')

const isMonoField = (key: string) =>
  key === 'id' ||
  key.endsWith('_id') ||
  key.includes('mcr') ||
  key.includes('code') ||
  key === 'r_year'

const statusTone = (value?: string | null): 'success' | 'warning' | 'critical' | 'info' | 'neutral' => {
  const normalized = value?.toLowerCase() ?? ''
  if (normalized.includes('inactive') || normalized.includes('error')) {
    return 'critical'
  }
  if (normalized.includes('loa') || normalized.includes('partial')) {
    return 'warning'
  }
  if (normalized.includes('active') || normalized.includes('success')) {
    return 'success'
  }
  if (normalized) {
    return 'info'
  }
  return 'neutral'
}

const boolBadge = (value: boolean, trueLabel = 'Yes', falseLabel = 'No') => (
  <StatusBadge label={value ? trueLabel : falseLabel} tone={value ? 'success' : 'neutral'} />
)

const tabDefinitions: ParsedTabDefinition[] = [
  {
    id: 'residents',
    label: 'Residents',
    minWidth: 1180,
    filters: [
      { key: 'programmeCode', label: 'Programme', placeholder: 'GERI' },
      { key: 'status', label: 'Status', type: 'select' },
      { key: 'mcr', label: 'MCR', placeholder: 'M12345A' },
      { key: 'search', label: 'Search', type: 'search', placeholder: 'Name, MCR, institution...' },
    ],
    columns: [
      { label: 'Name', value: (row) => formatValue((row as ParsedResidentRow).name) },
      {
        label: 'MCR',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedResidentRow).mcr),
      },
      {
        label: 'Programme',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedResidentRow).programme_code),
      },
      {
        label: 'R Year',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedResidentRow).r_year),
      },
      { label: 'Classification', value: (row) => formatValue((row as ParsedResidentRow).classification) },
      { label: 'Reg Type', value: (row) => formatValue((row as ParsedResidentRow).reg_type) },
      { label: 'Base Institution', value: (row) => formatValue((row as ParsedResidentRow).base_institution) },
      { label: 'Employer Tag', value: (row) => formatValue((row as ParsedResidentRow).employer_tag) },
      {
        label: 'Status',
        value: (row) => {
          const status = (row as ParsedResidentRow).status
          return <StatusBadge label={formatValue(status)} tone={statusTone(status)} />
        },
      },
    ],
  },
  {
    id: 'resident-postings',
    label: 'Resident Postings',
    minWidth: 1420,
    filters: [
      { key: 'reportingPeriodId', label: 'Reporting period', type: 'select' },
      { key: 'programmeCode', label: 'Programme', placeholder: 'GERI' },
      { key: 'postingCode', label: 'Posting code', placeholder: 'TTSHGerMed' },
      { key: 'mcr', label: 'MCR', placeholder: 'M12345A' },
      { key: 'status', label: 'Status', type: 'select' },
      { key: 'monthLabel', label: 'Month', placeholder: 'Jan-26' },
      { key: 'search', label: 'Search', type: 'search', placeholder: 'Resident, MCR, posting...' },
    ],
    columns: [
      { label: 'Resident', value: (row) => formatValue((row as ParsedResidentPostingRow).resident_name) },
      {
        label: 'MCR',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedResidentPostingRow).mcr),
      },
      {
        label: 'Programme',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedResidentPostingRow).programme_code),
      },
      {
        label: 'Posting Code',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedResidentPostingRow).posting_code),
      },
      { label: 'Month', value: (row) => formatValue((row as ParsedResidentPostingRow).month_label) },
      { label: 'Start Date', value: (row) => formatDate((row as ParsedResidentPostingRow).start_date) },
      { label: 'End Date', value: (row) => formatDate((row as ParsedResidentPostingRow).end_date) },
      {
        label: 'R Year',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedResidentPostingRow).r_year),
      },
      {
        label: 'Status',
        value: (row) => {
          const status = (row as ParsedResidentPostingRow).status
          return <StatusBadge label={formatValue(status)} tone={statusTone(status)} />
        },
      },
      { label: 'LOA Type', value: (row) => formatValue((row as ParsedResidentPostingRow).loa_type) },
      {
        label: 'Active Weight',
        value: (row) => formatNumber((row as ParsedResidentPostingRow).active_months_weight),
      },
      {
        label: 'Working Days',
        value: (row) => formatNumber((row as ParsedResidentPostingRow).working_days_in_month),
      },
    ],
  },
  {
    id: 'teaching-targets',
    label: 'Teaching Targets',
    minWidth: 1320,
    filters: [
      { key: 'reportingPeriodId', label: 'Reporting period', type: 'select' },
      { key: 'programmeCode', label: 'Programme', placeholder: 'GERI' },
      { key: 'postingCode', label: 'Posting code', placeholder: 'TTSHGerMed' },
      { key: 'rYear', label: 'R Year', placeholder: 'R1 or ALL' },
      { key: 'sessionType', label: 'Session type', placeholder: 'Department Teaching' },
      { key: 'search', label: 'Search', type: 'search', placeholder: 'Session, tag, details...' },
      { key: 'isTracked', label: 'Tracked', type: 'select' },
    ],
    columns: [
      {
        label: 'Programme',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedTeachingTargetRow).programme_code),
      },
      {
        label: 'R Year',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedTeachingTargetRow).r_year),
      },
      {
        label: 'Posting Code',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedTeachingTargetRow).posting_code),
      },
      { label: 'Session Type', value: (row) => formatValue((row as ParsedTeachingTargetRow).session_type_name) },
      {
        label: 'Monthly Target',
        value: (row) => formatNumber((row as ParsedTeachingTargetRow).monthly_target),
      },
      { label: 'Tracked', value: (row) => boolBadge((row as ParsedTeachingTargetRow).is_tracked, 'Tracked', 'Untracked') },
      {
        label: 'Reallocatable',
        value: (row) => boolBadge((row as ParsedTeachingTargetRow).is_reallocatable),
      },
      { label: 'Tag', value: (row) => formatValue((row as ParsedTeachingTargetRow).tag) },
      { label: 'Details of Training', value: (row) => formatValue((row as ParsedTeachingTargetRow).details_of_training) },
    ],
  },
  {
    id: 'teaching-name-catalogue',
    label: 'Teaching Name Catalogue',
    minWidth: 1240,
    filters: [
      { key: 'reportingPeriodId', label: 'Reporting period', type: 'select' },
      { key: 'programmeCode', label: 'Programme', placeholder: 'GERI' },
      { key: 'postingCode', label: 'Posting code', placeholder: 'TTSHGerMed' },
      { key: 'rYear', label: 'R Year', placeholder: 'R1 or ALL' },
      { key: 'keyword', label: 'Keyword', placeholder: 'Journal Club' },
      { key: 'search', label: 'Search', type: 'search', placeholder: 'Keyword, session...' },
      { key: 'isTracked', label: 'Tracked', type: 'select' },
    ],
    columns: [
      { label: 'Keyword', value: (row) => formatValue((row as ParsedTeachingNameCatalogueRow).keyword) },
      {
        label: 'Programme',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedTeachingNameCatalogueRow).programme_code),
      },
      {
        label: 'Posting Code',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedTeachingNameCatalogueRow).posting_code),
      },
      {
        label: 'R Year',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedTeachingNameCatalogueRow).r_year),
      },
      { label: 'Session Type', value: (row) => formatValue((row as ParsedTeachingNameCatalogueRow).session_type_name) },
      { label: 'Duration', value: (row) => formatNumber((row as ParsedTeachingNameCatalogueRow).duration_hours) },
      {
        label: 'Tracked',
        value: (row) => boolBadge((row as ParsedTeachingNameCatalogueRow).is_tracked, 'Tracked', 'Untracked'),
      },
    ],
  },
  {
    id: 'form-f1-records',
    label: 'FormF1 Records',
    minWidth: 980,
    filters: [
      { key: 'reportingPeriodId', label: 'Reporting period', type: 'select' },
      { key: 'programmeCode', label: 'Programme', placeholder: 'GERI' },
      { key: 'mcr', label: 'MCR', placeholder: 'M12345A' },
      { key: 'monthLabel', label: 'Month', placeholder: 'Jan-26' },
      { key: 'isActive', label: 'Active status', type: 'select' },
      { key: 'search', label: 'Search', type: 'search', placeholder: 'MCR, resident, status...' },
    ],
    columns: [
      {
        label: 'MCR',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedFormF1RecordRow).mcr),
      },
      { label: 'Resident', value: (row) => formatValue((row as ParsedFormF1RecordRow).resident_name) },
      {
        label: 'Programme',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedFormF1RecordRow).programme_code),
      },
      { label: 'Month', value: (row) => formatValue((row as ParsedFormF1RecordRow).month_label) },
      { label: 'Status Raw', value: (row) => formatValue((row as ParsedFormF1RecordRow).status_raw) },
      { label: 'Active', value: (row) => boolBadge((row as ParsedFormF1RecordRow).is_active, 'Active', 'Inactive') },
      { label: 'Promotion Date', value: (row) => formatDate((row as ParsedFormF1RecordRow).promotion_date) },
    ],
  },
  {
    id: 'public-holidays',
    label: 'Public Holidays',
    minWidth: 760,
    filters: [
      { key: 'year', label: 'Year', placeholder: '2026' },
      { key: 'search', label: 'Search', type: 'search', placeholder: 'Holiday name...' },
    ],
    columns: [
      { label: 'Holiday Date', value: (row) => formatDate((row as ParsedPublicHolidayRow).holiday_date) },
      { label: 'Name', value: (row) => formatValue((row as ParsedPublicHolidayRow).name) },
      { label: 'Day of Week', value: (row) => formatValue((row as ParsedPublicHolidayRow).day_of_week) },
      { label: 'Year', value: (row) => formatValue((row as ParsedPublicHolidayRow).year) },
    ],
  },
  {
    id: 'academic-month-boundaries',
    label: 'Academic Month Boundaries',
    minWidth: 980,
    filters: [
      { key: 'academicYearLabel', label: 'Academic year', placeholder: 'AY2025/2026' },
      { key: 'ayDateCategory', label: 'AY date category', type: 'select' },
      { key: 'monthLabel', label: 'Month', placeholder: 'Jan-26' },
      { key: 'search', label: 'Search', type: 'search', placeholder: 'Academic year, category, month...' },
    ],
    columns: [
      {
        label: 'Academic Year',
        value: (row) => formatValue((row as ParsedAcademicMonthBoundaryRow).academic_year_label),
      },
      {
        label: 'AY Category',
        value: (row) => formatValue((row as ParsedAcademicMonthBoundaryRow).ay_date_category),
      },
      { label: 'Month', value: (row) => formatValue((row as ParsedAcademicMonthBoundaryRow).month_label) },
      { label: 'Start Date', value: (row) => formatDate((row as ParsedAcademicMonthBoundaryRow).start_date) },
      { label: 'End Date', value: (row) => formatDate((row as ParsedAcademicMonthBoundaryRow).end_date) },
      {
        label: 'Upload ID',
        className: 'mono-cell',
        value: (row) => formatValue((row as ParsedAcademicMonthBoundaryRow).upload_id),
      },
    ],
  },
]

const activeToBoolean = (value: 'all' | 'true' | 'false') => {
  if (value === 'all') {
    return 'all'
  }
  return value === 'true'
}

const statusOptionsByTab: Partial<Record<ParsedDataTabId, { value: string; label: string }[]>> = {
  residents: [
    { value: 'active', label: 'Active' },
    { value: 'inactive', label: 'Inactive' },
  ],
  'resident-postings': [
    { value: 'active', label: 'Active' },
    { value: 'loa', label: 'LOA' },
    { value: 'inactive', label: 'Inactive' },
    { value: 'employed', label: 'Employed' },
  ],
}

export const AdminParsedDataPage = () => {
  const { demoAdminId, demoAdminProgrammes, reportingPeriods } = useAppState()
  const [activeTabId, setActiveTabId] = useState<ParsedDataTabId>('residents')
  const [filters, setFilters] = useState<ParsedDataFilters>({ ...initialFilters })
  const [debouncedFilters, setDebouncedFilters] = useState<ParsedDataFilters>({ ...initialFilters })
  const [rows, setRows] = useState<ParsedDataRow[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const hasLoadedRowsRef = useRef(false)
  const [isInitialLoading, setIsInitialLoading] = useState(true)
  const [isRefetching, setIsRefetching] = useState(false)
  const [isManualRefreshing, setIsManualRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedRow, setSelectedRow] = useState<ParsedDataRow | null>(null)

  const activeTab = useMemo(
    () => tabDefinitions.find((tab) => tab.id === activeTabId) ?? tabDefinitions[0],
    [activeTabId],
  )

  const setFilter = (key: FilterKey, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setOffset(0)
  }

  const clearFilters = () => {
    setFilters({ ...initialFilters })
    setOffset(0)
  }

  const hasFilters = useMemo(() => {
    return Object.entries(filters).some(([key, value]) => {
      if (key === 'isTracked' || key === 'isActive' || key === 'ayDateCategory') {
        return value !== 'all'
      }
      return typeof value === 'string' && value.trim().length > 0
    })
  }, [filters])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedFilters((previous) => (areFiltersEqual(previous, filters) ? previous : filters))
    }, filterDebounceMs)
    return () => window.clearTimeout(timer)
  }, [filters])

  const loadRows = useCallback(async (
    tabId: ParsedDataTabId,
    queryFilters: ParsedDataFilters,
    queryOffset: number,
  ): Promise<ParsedDataListResponse<ParsedDataRow>> => {
    const baseParams = {
      adminId: demoAdminId,
      adminProgrammes: demoAdminProgrammes,
      adminLevel: 'master' as const,
      limit: pageSize,
      offset: queryOffset,
    }

    switch (tabId) {
      case 'residents':
        return listParsedResidents({
          ...baseParams,
          programmeCode: queryFilters.programmeCode,
          mcr: queryFilters.mcr,
          status: queryFilters.status,
          search: queryFilters.search,
        })
      case 'resident-postings':
        return listParsedResidentPostings({
          ...baseParams,
          reportingPeriodId: queryFilters.reportingPeriodId,
          programmeCode: queryFilters.programmeCode,
          postingCode: queryFilters.postingCode,
          mcr: queryFilters.mcr,
          status: queryFilters.status,
          monthLabel: queryFilters.monthLabel,
          search: queryFilters.search,
        })
      case 'teaching-targets':
        return listParsedTeachingTargets({
          ...baseParams,
          reportingPeriodId: queryFilters.reportingPeriodId,
          programmeCode: queryFilters.programmeCode,
          postingCode: queryFilters.postingCode,
          rYear: queryFilters.rYear,
          sessionType: queryFilters.sessionType,
          isTracked: activeToBoolean(queryFilters.isTracked),
          search: queryFilters.search,
        })
      case 'teaching-name-catalogue':
        return listParsedTeachingNameCatalogue({
          ...baseParams,
          reportingPeriodId: queryFilters.reportingPeriodId,
          programmeCode: queryFilters.programmeCode,
          postingCode: queryFilters.postingCode,
          rYear: queryFilters.rYear,
          keyword: queryFilters.keyword,
          isTracked: activeToBoolean(queryFilters.isTracked),
          search: queryFilters.search,
        })
      case 'form-f1-records':
        return listParsedFormF1Records({
          ...baseParams,
          reportingPeriodId: queryFilters.reportingPeriodId,
          programmeCode: queryFilters.programmeCode,
          mcr: queryFilters.mcr,
          monthLabel: queryFilters.monthLabel,
          isActive: activeToBoolean(queryFilters.isActive),
          search: queryFilters.search,
        })
      case 'public-holidays':
        return listParsedPublicHolidays({
          ...baseParams,
          year: queryFilters.year,
          search: queryFilters.search,
        })
      case 'academic-month-boundaries':
        return listParsedAcademicMonthBoundaries({
          ...baseParams,
          academicYearLabel: queryFilters.academicYearLabel,
          ayDateCategory: queryFilters.ayDateCategory,
          monthLabel: queryFilters.monthLabel,
          search: queryFilters.search,
        })
    }
  }, [demoAdminId, demoAdminProgrammes])

  const fetchRows = useCallback(async () => {
    setIsManualRefreshing(true)
    setError(null)
    setSelectedRow(null)

    try {
      const response = await loadRows(activeTabId, filters, offset)
      setDebouncedFilters((previous) => (areFiltersEqual(previous, filters) ? previous : filters))
      setRows(response.items)
      setTotal(response.total)
      hasLoadedRowsRef.current = true
    } catch (fetchError) {
      setRows([])
      setTotal(0)
      hasLoadedRowsRef.current = true
      setError(fetchError instanceof Error ? fetchError.message : 'Unable to load parsed data.')
    } finally {
      setIsManualRefreshing(false)
      setIsInitialLoading(false)
      setIsRefetching(false)
    }
  }, [activeTabId, filters, loadRows, offset])

  useEffect(() => {
    let active = true
    ;(async () => {
      const isBackgroundRefetch = hasLoadedRowsRef.current
      if (isBackgroundRefetch) {
        setIsRefetching(true)
      } else {
        setIsInitialLoading(true)
      }
      setError(null)
      setSelectedRow(null)

      try {
        const response = await loadRows(activeTabId, debouncedFilters, offset)
        if (active) {
          setRows(response.items)
          setTotal(response.total)
          hasLoadedRowsRef.current = true
        }
      } catch (fetchError) {
        if (active) {
          if (!isBackgroundRefetch) {
            setRows([])
            setTotal(0)
          }
          hasLoadedRowsRef.current = true
          setError(fetchError instanceof Error ? fetchError.message : 'Unable to load parsed data.')
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
  }, [activeTabId, debouncedFilters, loadRows, offset])

  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + rows.length, total)
  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < total
    ? 'Read-only preview of persisted parser output'
    : `${total} persisted row${total === 1 ? '' : 's'} in ${activeTab.label}`

  const renderFilter = (filter: FilterDefinition) => {
    if (filter.key === 'reportingPeriodId') {
      return (
        <label key={filter.key}>
          {filter.label}
          <select
            value={filters.reportingPeriodId}
            onChange={(event) => setFilter('reportingPeriodId', event.target.value)}
          >
            <option value="">All periods</option>
            {reportingPeriods.map((period) => (
              <option key={period.id} value={period.id}>
                {period.label}
              </option>
            ))}
          </select>
        </label>
      )
    }

    if (filter.key === 'isTracked') {
      return (
        <label key={filter.key}>
          {filter.label}
          <select
            value={filters.isTracked}
            onChange={(event) => setFilter('isTracked', event.target.value)}
          >
            <option value="all">All rows</option>
            <option value="true">Tracked</option>
            <option value="false">Untracked</option>
          </select>
        </label>
      )
    }

    if (filter.key === 'isActive') {
      return (
        <label key={filter.key}>
          {filter.label}
          <select
            value={filters.isActive}
            onChange={(event) => setFilter('isActive', event.target.value)}
          >
            <option value="all">All rows</option>
            <option value="true">Active</option>
            <option value="false">Inactive</option>
          </select>
        </label>
      )
    }

    if (filter.key === 'ayDateCategory') {
      return (
        <label key={filter.key}>
          {filter.label}
          <select
            value={filters.ayDateCategory}
            onChange={(event) => setFilter('ayDateCategory', event.target.value)}
          >
            <option value="all">All categories</option>
            <option value="im_subspec">IM subspec</option>
            <option value="non_im_subspec">Non-IM subspec</option>
          </select>
        </label>
      )
    }

    if (filter.key === 'status') {
      const options = statusOptionsByTab[activeTabId] ?? []
      return (
        <label key={filter.key}>
          {filter.label}
          <select
            value={filters.status}
            onChange={(event) => setFilter('status', event.target.value)}
          >
            <option value="">All statuses</option>
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      )
    }

    return (
      <label key={filter.key}>
        {filter.label}
        <input
          type={filter.type === 'search' ? 'search' : 'text'}
          value={filters[filter.key]}
          onChange={(event) => setFilter(filter.key, event.target.value)}
          placeholder={filter.placeholder}
        />
      </label>
    )
  }

  return (
    <div className="page parsed-data-page">
      <PageHero
        title="Parsed Data"
        subtitle="Read-only preview of persisted parser output"
        actions={
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void fetchRows()}
            disabled={isManualRefreshing || isInitialLoading}
          >
            <IconRefresh size={14} />
            {isManualRefreshing ? 'Refreshing' : 'Refresh'}
          </button>
        }
      />

      <section className="parsed-data-callout">
        Parsed Data Preview is read-only. Small rectifications must be handled through source uploads or future controlled correction workflows.
      </section>

      <section className="card parsed-data-tab-card">
        <div className="parsed-data-tabs" role="tablist" aria-label="Parsed data tables">
          {tabDefinitions.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={activeTabId === tab.id ? 'is-active' : ''}
              role="tab"
              aria-selected={activeTabId === tab.id}
              onClick={() => {
                setActiveTabId(tab.id)
                setFilters({ ...initialFilters })
                setDebouncedFilters({ ...initialFilters })
                setOffset(0)
                setRows([])
                setTotal(0)
                setError(null)
                setSelectedRow(null)
                hasLoadedRowsRef.current = false
                setIsInitialLoading(true)
                setIsRefetching(false)
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      <section className="card filter-bar warning-filter-card parsed-data-filter-card">
        {activeTab.filters.map(renderFilter)}
        <div className="parsed-data-clear-filter">
          <button type="button" className="button button-ghost" onClick={clearFilters}>
            Clear filters
          </button>
        </div>
      </section>

      {error && rows.length > 0 ? (
        <section className="inline-callout callout-warning parsed-data-inline-error">
          <span>{error}</span>
        </section>
      ) : null}

      {isInitialLoading ? (
        <section className="card warning-state-card parsed-data-state-card">Loading parsed data...</section>
      ) : error && rows.length === 0 ? (
        <section className="card warning-state-card parsed-data-state-card">
          <strong>Parsed data could not be loaded.</strong>
          <p>{error}</p>
          <button type="button" className="button button-secondary" onClick={() => void fetchRows()}>
            Retry
          </button>
        </section>
      ) : rows.length === 0 ? (
        <section className="card warning-state-card parsed-data-state-card">
          <strong>{hasFilters ? 'No parsed rows match these filters' : `No ${activeTab.label.toLowerCase()} rows found`}</strong>
          <p>
            {hasFilters
              ? 'Clear filters or adjust the search to inspect persisted parser output.'
              : 'Rows will appear here after the corresponding parser has persisted upload data.'}
          </p>
        </section>
      ) : (
        <section className={`warning-group-card parsed-data-table-card ${isRefetching ? 'is-refetching' : ''}`}>
          <div className="warning-group-header">
            <div>
              <span className="warning-group-kicker">Persisted parser output</span>
              <h2>{activeTab.label}</h2>
            </div>
            <div className="parsed-data-count-status">
              {isRefetching ? <span className="parsed-data-updating">Updating...</span> : null}
              <span className="warning-count-pill">
                {firstItem}-{lastItem} of {total}
              </span>
            </div>
          </div>
          <div className="table-scroll">
            <table className="table parsed-data-table" style={{ minWidth: activeTab.minWidth }}>
              <thead>
                <tr>
                  {activeTab.columns.map((column) => (
                    <th key={column.label}>{column.label}</th>
                  ))}
                  <th aria-label="Open detail" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.id}
                    className="table-clickable-row"
                    onClick={() => setSelectedRow(row)}
                  >
                    {activeTab.columns.map((column) => (
                      <td key={column.label} className={column.className}>
                        {column.value(row)}
                      </td>
                    ))}
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
        title={selectedRow ? `${activeTab.label} row` : 'Parsed data row'}
        open={Boolean(selectedRow)}
        onClose={() => setSelectedRow(null)}
      >
        {selectedRow ? (
          <div className="warning-detail parsed-data-detail">
            <div className="detail-block">
              <h3>Read-only row inspection</h3>
              <p>This drawer shows the persisted parser row exactly as exposed by the preview read model.</p>
            </div>
            <div className="parsed-data-detail-grid">
              {Object.entries(selectedRow).map(([key, value]) => (
                <div key={key} className="parsed-data-detail-item">
                  <span>{humanizeKey(key)}</span>
                  <strong className={isMonoField(key) ? 'mono-cell' : undefined}>
                    {typeof value === 'boolean'
                      ? formatValue(value)
                      : key.endsWith('_date') || key === 'holiday_date' || key === 'start_date' || key === 'end_date'
                        ? formatDate(value as string | null)
                        : formatValue(value as string | number | null)}
                  </strong>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
