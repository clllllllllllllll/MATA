import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  listParsedAcademicMonthBoundaries,
  listParsedFormF1Records,
  listParsedPublicHolidays,
  listParsedResidentPostings,
  listParsedResidents,
  listParsedTeachingNameCatalogue,
  listParsedTeachingTargets,
} from '../../api/parsedData'
import { getUploadLog, listUploadLogs } from '../../api/uploadLogs'
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
import type { RawMultiPostingDecision, RawMultiPostingFragment, UploadLogDetail, UploadLogListItem } from '../../types/upload'
import {
  clearMemoryCache,
  clearMemoryCacheResource,
  getMemoryCache,
  makeScopedCacheKey,
  readThroughMemoryCache,
  setMemoryCache,
  type CacheScope,
} from '../../utils/memoryReadCache'

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

interface RawFragmentPostingGroup {
  key: string
  rawPostingCode: string | null
  normalizedPostingCode: string | null
  decision: RawMultiPostingDecision | null
  effectivePostingCode: string | null
  ruleType: string | null
  ruleId: string | null
  warningId: string | null
  fragments: RawMultiPostingFragment[]
}

interface RawFragmentSourceGroup {
  key: string
  sourceFragment: RawMultiPostingFragment
  postingGroups: RawFragmentPostingGroup[]
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

const decisionLabels: Record<string, string> = {
  collapsed_into_main: 'Collapsed into main',
  persisted_independent: 'Persisted independent',
  combined: 'Combined',
  half_month: 'Half month',
  unmatched_warning: 'Unmatched warning',
  excluded: 'Excluded',
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

const decisionTone = (decision?: string | null): 'success' | 'warning' | 'critical' | 'info' | 'neutral' => {
  switch (decision) {
    case 'collapsed_into_main':
    case 'combined':
      return 'success'
    case 'half_month':
    case 'persisted_independent':
      return 'info'
    case 'unmatched_warning':
      return 'warning'
    case 'excluded':
      return 'neutral'
    default:
      return decision ? 'info' : 'neutral'
  }
}

const formatDecisionLabel = (decision?: string | null) => {
  if (!decision) {
    return '-'
  }
  return decisionLabels[decision] ?? humanizeKey(decision)
}

const boolBadge = (value: boolean, trueLabel = 'Yes', falseLabel = 'No') => (
  <StatusBadge label={value ? trueLabel : falseLabel} tone={value ? 'success' : 'neutral'} />
)

const compareText = (left?: string | null, right?: string | null) =>
  (left ?? '').localeCompare(right ?? '', 'en-SG', { sensitivity: 'base' })

const dateSortKey = (value?: string | null) => {
  if (!value) {
    return Number.MAX_SAFE_INTEGER
  }
  const time = Date.parse(value)
  return Number.isNaN(time) ? Number.MAX_SAFE_INTEGER : time
}

const sortParsedRowsForDisplay = (tabId: ParsedDataTabId, items: ParsedDataRow[]) => {
  if (tabId !== 'resident-postings') {
    return items
  }
  return [...items].sort((left, right) => {
    const leftPosting = left as ParsedResidentPostingRow
    const rightPosting = right as ParsedResidentPostingRow
    return (
      compareText(leftPosting.programme_code, rightPosting.programme_code) ||
      compareText(leftPosting.resident_name, rightPosting.resident_name) ||
      dateSortKey(leftPosting.start_date) - dateSortKey(rightPosting.start_date) ||
      compareText(leftPosting.mcr, rightPosting.mcr) ||
      compareText(leftPosting.id, rightPosting.id)
    )
  })
}

const formatSingaporeDateTime = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString('en-SG', {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZone: 'Asia/Singapore',
      })
    : '-'

const formatSource = (fragment: RawMultiPostingFragment) =>
  [
    fragment.sheet_name,
    fragment.row_number === null ? null : `Row ${fragment.row_number}`,
    fragment.cell_ref,
  ]
    .filter(Boolean)
    .join(' \u00b7 ') || '-'

const formatDateRange = (start?: string | null, end?: string | null) => {
  if (!start && !end) {
    return '-'
  }
  return `${start ?? '-'} to ${end ?? '-'}`
}

const formatDayPart = (dayPart?: string | null) => {
  if (!dayPart) {
    return 'Full day'
  }
  return dayPart
}

const optionalString = (value: unknown): string | null => {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed || null
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value)
  }
  return null
}

const optionalNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) {
    return Number(value)
  }
  return null
}

const summaryObject = (summary: unknown): Record<string, unknown> => {
  if (typeof summary === 'object' && summary !== null && !Array.isArray(summary)) {
    return summary as Record<string, unknown>
  }
  return {}
}

const summaryValue = (summary: unknown, key: string): unknown => {
  const topLevel = summaryObject(summary)
  if (key in topLevel) {
    return topLevel[key]
  }
  const metadata = summaryObject(topLevel.metadata)
  return metadata[key]
}

const summaryRawFragments = (uploadLog: UploadLogDetail | null): RawMultiPostingFragment[] => {
  const rawValue = uploadLog ? summaryValue(uploadLog.summary, 'raw_multi_posting_fragments') : null
  if (!Array.isArray(rawValue)) {
    return []
  }

  return rawValue
    .filter((value): value is Record<string, unknown> => typeof value === 'object' && value !== null)
    .map((value, index) => {
      const fragmentIndex = optionalNumber(value.fragment_index) ?? index + 1
      const rowNumber = optionalNumber(value.row_number)
      const mcr = optionalString(value.mcr)
      const cellRef = optionalString(value.cell_ref)
      return {
        id: [
          uploadLog?.id ?? 'rdb-upload',
          optionalString(value.programme_code) ?? 'programme',
          mcr ?? 'mcr',
          rowNumber ?? 'row',
          cellRef ?? 'cell',
          fragmentIndex,
        ].join(':'),
        mcr,
        resident_name: optionalString(value.resident_name),
        programme_code: optionalString(value.programme_code),
        r_year: optionalString(value.r_year),
        sheet_name: optionalString(value.sheet_name),
        row_number: rowNumber,
        cell_ref: cellRef,
        month_label: optionalString(value.month_label),
        source_column_header: optionalString(value.source_column_header),
        source_cell_text: optionalString(value.source_cell_text),
        fragment_index: fragmentIndex,
        raw_posting_code: optionalString(value.raw_posting_code),
        normalized_posting_code: optionalString(value.normalized_posting_code),
        fragment_start_date: optionalString(value.fragment_start_date),
        fragment_end_date: optionalString(value.fragment_end_date),
        day_part: optionalString(value.day_part),
        decision: optionalString(value.decision) as RawMultiPostingDecision | null,
        effective_posting_code: optionalString(value.effective_posting_code),
        rule_type: optionalString(value.rule_type),
        rule_id: optionalString(value.rule_id),
        warning_id: optionalString(value.warning_id),
      }
    })
}

const sortRawFragments = (items: RawMultiPostingFragment[]) =>
  [...items].sort((left, right) => (
    compareText(left.programme_code, right.programme_code) ||
    dateSortKey(left.fragment_start_date) - dateSortKey(right.fragment_start_date) ||
    compareText(left.mcr, right.mcr) ||
    left.fragment_index - right.fragment_index
  ))

const normalizedMatchValue = (value?: string | null) => value?.trim().toLowerCase() ?? ''

const sameText = (left?: string | null, right?: string | null) =>
  normalizedMatchValue(left) === normalizedMatchValue(right)

const dateRangeOverlaps = (
  leftStart?: string | null,
  leftEnd?: string | null,
  rightStart?: string | null,
  rightEnd?: string | null,
) => {
  const leftStartTime = Date.parse(leftStart ?? '')
  const leftEndTime = Date.parse(leftEnd ?? '')
  const rightStartTime = Date.parse(rightStart ?? '')
  const rightEndTime = Date.parse(rightEnd ?? '')
  if (
    Number.isNaN(leftStartTime) ||
    Number.isNaN(leftEndTime) ||
    Number.isNaN(rightStartTime) ||
    Number.isNaN(rightEndTime)
  ) {
    return false
  }
  return rightStartTime <= leftEndTime && rightEndTime >= leftStartTime
}

const matchingRawFragmentsForPosting = (
  row: ParsedResidentPostingRow,
  fragments: RawMultiPostingFragment[],
) =>
  fragments.filter((fragment) => {
    if (!sameText(fragment.mcr, row.mcr)) {
      return false
    }
    if (!sameText(fragment.programme_code, row.programme_code)) {
      return false
    }
    if (!sameText(fragment.r_year, row.r_year)) {
      return false
    }
    if (!sameText(fragment.month_label, row.month_label)) {
      return false
    }
    if (!sameText(fragment.effective_posting_code, row.posting_code)) {
      return false
    }
    if (
      fragment.fragment_start_date &&
      fragment.fragment_end_date &&
      row.start_date &&
      row.end_date
    ) {
      return dateRangeOverlaps(row.start_date, row.end_date, fragment.fragment_start_date, fragment.fragment_end_date)
    }
    return true
  })

const uniqueFragmentValues = (
  fragments: RawMultiPostingFragment[],
  pickValue: (fragment: RawMultiPostingFragment) => string | null,
) => Array.from(new Set(fragments.map(pickValue).filter((value): value is string => Boolean(value)))).sort(compareText)

const RawPostingCell = ({ fragments }: { fragments: RawMultiPostingFragment[] }) => {
  if (fragments.length === 0) {
    return <span className="muted-text">-</span>
  }
  const rawPostings = uniqueFragmentValues(fragments, (fragment) => fragment.raw_posting_code)
  if (fragments.length === 1 && rawPostings.length === 1) {
    return <span className="mono-cell">{rawPostings[0]}</span>
  }
  return <span className="count-chip">{fragments.length} raw fragments</span>
}

const ParserDecisionCell = ({ fragments }: { fragments: RawMultiPostingFragment[] }) => {
  if (fragments.length === 0) {
    return <span className="muted-text">-</span>
  }
  const decisions = uniqueFragmentValues(fragments, (fragment) => fragment.decision)
  if (decisions.length === 0) {
    return <span className="muted-text">-</span>
  }
  if (decisions.length === 1) {
    return <StatusBadge label={formatDecisionLabel(decisions[0])} tone={decisionTone(decisions[0])} />
  }
  return <span className="count-chip">{decisions.length} decisions</span>
}

const RawSourceCell = ({ fragments }: { fragments: RawMultiPostingFragment[] }) => {
  if (fragments.length === 0) {
    return <span className="muted-text">-</span>
  }
  if (fragments.length === 1) {
    return <span>{formatSource(fragments[0])}</span>
  }
  return <span className="count-chip">{fragments.length} sources</span>
}

const rawGroupKeyPart = (value: string | number | null | undefined) => String(value ?? '-')

const rawSourceGroupKey = (fragment: RawMultiPostingFragment) =>
  [
    fragment.source_cell_text,
    fragment.sheet_name,
    fragment.row_number,
    fragment.cell_ref,
    fragment.source_column_header,
  ].map(rawGroupKeyPart).join('|')

const rawPostingGroupKey = (fragment: RawMultiPostingFragment) =>
  [
    fragment.raw_posting_code,
    fragment.normalized_posting_code,
    fragment.effective_posting_code,
    fragment.decision,
    fragment.rule_type,
    fragment.rule_id,
    fragment.warning_id,
  ].map(rawGroupKeyPart).join('|')

const sortFragmentsByDateRange = (fragments: RawMultiPostingFragment[]) =>
  [...fragments].sort((left, right) => (
    dateSortKey(left.fragment_start_date) - dateSortKey(right.fragment_start_date) ||
    dateSortKey(left.fragment_end_date) - dateSortKey(right.fragment_end_date) ||
    left.fragment_index - right.fragment_index
  ))

const groupRawFragmentsForDrawer = (fragments: RawMultiPostingFragment[]): RawFragmentSourceGroup[] => {
  const sourceGroups = new Map<string, RawFragmentSourceGroup>()

  fragments.forEach((fragment) => {
    const sourceKey = rawSourceGroupKey(fragment)
    const sourceGroup = sourceGroups.get(sourceKey) ?? {
      key: sourceKey,
      sourceFragment: fragment,
      postingGroups: [],
    }
    if (!sourceGroups.has(sourceKey)) {
      sourceGroups.set(sourceKey, sourceGroup)
    }

    const postingKey = rawPostingGroupKey(fragment)
    let postingGroup = sourceGroup.postingGroups.find((group) => group.key === postingKey)
    if (!postingGroup) {
      postingGroup = {
        key: postingKey,
        rawPostingCode: fragment.raw_posting_code,
        normalizedPostingCode: fragment.normalized_posting_code,
        decision: fragment.decision,
        effectivePostingCode: fragment.effective_posting_code,
        ruleType: fragment.rule_type,
        ruleId: fragment.rule_id,
        warningId: fragment.warning_id,
        fragments: [],
      }
      sourceGroup.postingGroups.push(postingGroup)
    }
    postingGroup.fragments.push(fragment)
  })

  return Array.from(sourceGroups.values()).map((sourceGroup) => ({
    ...sourceGroup,
    postingGroups: sourceGroup.postingGroups
      .map((postingGroup) => ({
        ...postingGroup,
        fragments: sortFragmentsByDateRange(postingGroup.fragments),
      }))
      .sort((left, right) => (
        compareText(left.rawPostingCode, right.rawPostingCode) ||
        compareText(left.normalizedPostingCode, right.normalizedPostingCode) ||
        dateSortKey(left.fragments[0]?.fragment_start_date) - dateSortKey(right.fragments[0]?.fragment_start_date)
      )),
  }))
}

const formatFragmentDateRangeLine = (fragment: RawMultiPostingFragment) =>
  `${formatDateRange(fragment.fragment_start_date, fragment.fragment_end_date)} - ${formatDayPart(fragment.day_part)}`

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
    minWidth: 1680,
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
  const { role, demoAdminId, demoAdminProgrammes, reportingPeriods } = useAppState()
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
  const [rdbUploadLogs, setRdbUploadLogs] = useState<UploadLogListItem[]>([])
  const [selectedRdbUploadId, setSelectedRdbUploadId] = useState<string | null>(null)
  const [selectedRdbUploadDetail, setSelectedRdbUploadDetail] = useState<UploadLogDetail | null>(null)
  const [isRawLogLoading, setIsRawLogLoading] = useState(true)
  const [isRawDetailLoading, setIsRawDetailLoading] = useState(false)
  const [rawFragmentError, setRawFragmentError] = useState<string | null>(null)

  const activeTab = useMemo(
    () => tabDefinitions.find((tab) => tab.id === activeTabId) ?? tabDefinitions[0],
    [activeTabId],
  )

  const cacheScope = useMemo<CacheScope>(() => ({
    role,
    userId: demoAdminId,
    programmeScope: demoAdminProgrammes,
  }), [demoAdminId, demoAdminProgrammes, role])

  const parsedDataCacheKey = useCallback((
    tabId: ParsedDataTabId,
    queryFilters: ParsedDataFilters,
    queryOffset: number,
  ) => makeScopedCacheKey(cacheScope, 'admin.parsed-data', {
    view: tabId,
    filters: queryFilters,
    limit: pageSize,
    offset: queryOffset,
  }), [cacheScope])

  const uploadLogListCacheKey = useCallback(() => makeScopedCacheKey(cacheScope, 'admin.upload-logs.rdb-source-list', {
    uploadType: 'rdb',
    limit: 50,
  }), [cacheScope])

  const uploadLogDetailCacheKey = useCallback((uploadLogId: string) => makeScopedCacheKey(
    cacheScope,
    'admin.upload-logs.rdb-source-detail',
    { uploadLogId },
  ), [cacheScope])

  const setFilter = (key: FilterKey, value: string) => {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setOffset(0)
  }

  const clearFilters = () => {
    setFilters({ ...initialFilters })
    setOffset(0)
  }

  const hydrateRowsFromCache = useCallback((
    tabId: ParsedDataTabId,
    queryFilters: ParsedDataFilters,
    queryOffset: number,
  ): boolean => {
    const cached = getMemoryCache<ParsedDataListResponse<ParsedDataRow>>(
      parsedDataCacheKey(tabId, queryFilters, queryOffset),
    )
    if (!cached) {
      return false
    }

    setRows(sortParsedRowsForDisplay(tabId, cached.data.items))
    setTotal(cached.data.total)
    hasLoadedRowsRef.current = true
    setIsInitialLoading(false)
    return true
  }, [parsedDataCacheKey])

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
      const key = parsedDataCacheKey(activeTabId, filters, offset)
      clearMemoryCache((cacheKey) => cacheKey === key)
      clearMemoryCacheResource('admin.upload-logs.rdb-source-list')
      clearMemoryCacheResource('admin.upload-logs.rdb-source-detail')
      const response = await loadRows(activeTabId, filters, offset)
      setMemoryCache(key, response)
      setDebouncedFilters((previous) => (areFiltersEqual(previous, filters) ? previous : filters))
      setRows(sortParsedRowsForDisplay(activeTabId, response.items))
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
  }, [activeTabId, filters, loadRows, offset, parsedDataCacheKey])

  useEffect(() => {
    let active = true
    ;(async () => {
      const key = parsedDataCacheKey(activeTabId, debouncedFilters, offset)
      const cached = getMemoryCache<ParsedDataListResponse<ParsedDataRow>>(key)
      if (cached) {
        setRows(sortParsedRowsForDisplay(activeTabId, cached.data.items))
        setTotal(cached.data.total)
        hasLoadedRowsRef.current = true
        setIsInitialLoading(false)
      }
      const isBackgroundRefetch = hasLoadedRowsRef.current
      if (isBackgroundRefetch) {
        setIsRefetching(true)
      } else {
        setIsInitialLoading(true)
      }
      setError(null)
      setSelectedRow(null)

      try {
        const { data: response } = await readThroughMemoryCache(
          key,
          () => loadRows(activeTabId, debouncedFilters, offset),
          { force: Boolean(cached) },
        )
        if (active) {
          setRows(sortParsedRowsForDisplay(activeTabId, response.items))
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
  }, [activeTabId, debouncedFilters, loadRows, offset, parsedDataCacheKey])

  const loadRdbUploadLogs = useCallback(async () => {
    if (activeTabId !== 'resident-postings') {
      return
    }
    setIsRawLogLoading(true)
    setRawFragmentError(null)
    try {
      const { data: response } = await readThroughMemoryCache(
        uploadLogListCacheKey(),
        () => listUploadLogs({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel: 'master',
          uploadType: 'rdb',
          limit: 50,
        }),
      )
      setRdbUploadLogs(response.items)
      setSelectedRdbUploadId((current) => {
        if (current && response.items.some((item) => item.id === current)) {
          return current
        }
        return response.items[0]?.id ?? null
      })
      if (response.items.length === 0) {
        setSelectedRdbUploadDetail(null)
      }
    } catch (fetchError) {
      setRdbUploadLogs([])
      setSelectedRdbUploadId(null)
      setSelectedRdbUploadDetail(null)
      setRawFragmentError(fetchError instanceof Error ? fetchError.message : 'Unable to load RDB upload logs.')
    } finally {
      setIsRawLogLoading(false)
    }
  }, [activeTabId, demoAdminId, demoAdminProgrammes, uploadLogListCacheKey])

  useEffect(() => {
    if (activeTabId === 'resident-postings') {
      void loadRdbUploadLogs()
    }
  }, [activeTabId, loadRdbUploadLogs])

  useEffect(() => {
    if (activeTabId !== 'resident-postings' || !selectedRdbUploadId) {
      setSelectedRdbUploadDetail(null)
      setIsRawDetailLoading(false)
      return
    }

    let active = true
    ;(async () => {
      setIsRawDetailLoading(true)
      setRawFragmentError(null)
      try {
        const { data: detail } = await readThroughMemoryCache(
          uploadLogDetailCacheKey(selectedRdbUploadId),
          () => getUploadLog({
            adminId: demoAdminId,
            adminProgrammes: demoAdminProgrammes,
            adminLevel: 'master',
            uploadLogId: selectedRdbUploadId,
          }),
        )
        if (active) {
          setSelectedRdbUploadDetail(detail)
        }
      } catch (fetchError) {
        if (active) {
          setSelectedRdbUploadDetail(null)
          setRawFragmentError(fetchError instanceof Error ? fetchError.message : 'Unable to load RDB upload detail.')
        }
      } finally {
        if (active) {
          setIsRawDetailLoading(false)
        }
      }
    })()

    return () => {
      active = false
    }
  }, [activeTabId, demoAdminId, demoAdminProgrammes, selectedRdbUploadId, uploadLogDetailCacheKey])

  const firstItem = total === 0 ? 0 : offset + 1
  const lastItem = Math.min(offset + rows.length, total)
  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < total
  const rawFragments = useMemo(
    () => sortRawFragments(summaryRawFragments(selectedRdbUploadDetail)),
    [selectedRdbUploadDetail],
  )
  const selectedRdbLogLabel = selectedRdbUploadDetail
    ? [
        formatSingaporeDateTime(selectedRdbUploadDetail.uploaded_at),
        selectedRdbUploadDetail.reporting_period_label ?? selectedRdbUploadDetail.reporting_period_id,
        selectedRdbUploadDetail.programme_code ?? 'Global',
        selectedRdbUploadDetail.original_filename,
      ].filter(Boolean).join(' | ')
    : null
  const rawFragmentsByPostingId = useMemo(() => {
    const matches = new Map<string, RawMultiPostingFragment[]>()
    if (activeTabId !== 'resident-postings') {
      return matches
    }
    rows.forEach((row) => {
      const postingRow = row as ParsedResidentPostingRow
      matches.set(postingRow.id, matchingRawFragmentsForPosting(postingRow, rawFragments))
    })
    return matches
  }, [activeTabId, rawFragments, rows])
  const selectedRowRawFragments = selectedRow && activeTabId === 'resident-postings'
    ? rawFragmentsByPostingId.get((selectedRow as ParsedResidentPostingRow).id) ?? []
    : []
  const selectedRowRawSourceGroups = useMemo(
    () => groupRawFragmentsForDrawer(selectedRowRawFragments),
    [selectedRowRawFragments],
  )

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
                const nextFilters = { ...initialFilters }
                setActiveTabId(tab.id)
                setFilters(nextFilters)
                setDebouncedFilters(nextFilters)
                setOffset(0)
                setError(null)
                setSelectedRow(null)
                const hydrated = hydrateRowsFromCache(tab.id, nextFilters, 0)
                if (hydrated) {
                  setIsRefetching(true)
                } else {
                  setRows([])
                  setTotal(0)
                  hasLoadedRowsRef.current = false
                  setIsInitialLoading(true)
                  setIsRefetching(false)
                }
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      <section className="card filter-bar warning-filter-card parsed-data-filter-card">
        {activeTab.filters.map(renderFilter)}
        {activeTabId === 'resident-postings' ? (
          <label>
            RDB upload source
            <select
              value={selectedRdbUploadId ?? ''}
              onChange={(event) => {
                setSelectedRdbUploadId(event.target.value || null)
              }}
              disabled={isRawLogLoading || rdbUploadLogs.length === 0}
            >
              {rdbUploadLogs.length === 0 ? (
                <option value="">No RDB uploads</option>
              ) : null}
              {rdbUploadLogs.map((log) => (
                <option key={log.id} value={log.id}>
                  {formatSingaporeDateTime(log.uploaded_at)} | {log.reporting_period_label ?? log.reporting_period_id ?? 'No period'} | {log.programme_code ?? 'Global'}
                </option>
              ))}
            </select>
          </label>
        ) : null}
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

      {activeTabId === 'resident-postings' && rawFragmentError ? (
        <section className="inline-callout callout-warning parsed-data-inline-error">
          <span>{rawFragmentError}</span>
        </section>
      ) : null}

      <section className={`warning-group-card parsed-data-table-card ${isRefetching ? 'is-refetching' : ''}`}>
        <div className="warning-group-header">
          <div>
            <span className="warning-group-kicker">Persisted parser output</span>
            <h2>{activeTab.label}</h2>
          </div>
          <div className="parsed-data-count-status">
            {isRefetching ? <span className="parsed-data-updating">Refreshing...</span> : null}
            <span className="warning-count-pill">
              {firstItem}-{lastItem} of {total}
            </span>
          </div>
        </div>
        {isInitialLoading && rows.length === 0 ? (
          <div className="warning-state-card parsed-data-state-card">Loading parsed data...</div>
        ) : error && rows.length === 0 ? (
          <div className="warning-state-card parsed-data-state-card">
            <strong>Parsed data could not be loaded.</strong>
            <p>{error}</p>
            <button type="button" className="button button-secondary" onClick={() => void fetchRows()}>
              Retry
            </button>
          </div>
        ) : rows.length === 0 ? (
          <div className="warning-state-card parsed-data-state-card">
            <strong>{hasFilters ? 'No parsed rows match these filters' : `No ${activeTab.label.toLowerCase()} rows found`}</strong>
            <p>
              {hasFilters
                ? 'Clear filters or adjust the search to inspect persisted parser output.'
                : 'Rows will appear here after the corresponding parser has persisted upload data.'}
            </p>
          </div>
        ) : (
          <>
            <div className="table-scroll">
              <table className="table parsed-data-table" style={{ minWidth: activeTab.minWidth }}>
                <thead>
                  <tr>
                    {activeTab.columns.map((column) => (
                      <Fragment key={column.label}>
                        <th>{column.label}</th>
                        {activeTabId === 'resident-postings' && column.label === 'Posting Code' ? (
                          <>
                            <th>Raw Posting</th>
                            <th>Parser Decision</th>
                            <th>Source</th>
                          </>
                        ) : null}
                      </Fragment>
                    ))}
                    <th aria-label="Open detail" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const rawMatches = activeTabId === 'resident-postings'
                      ? rawFragmentsByPostingId.get((row as ParsedResidentPostingRow).id) ?? []
                      : []
                    return (
                      <tr
                        key={row.id}
                        className="table-clickable-row"
                        onClick={() => setSelectedRow(row)}
                      >
                        {activeTab.columns.map((column) => (
                          <Fragment key={column.label}>
                            <td className={column.className}>
                              {column.value(row)}
                            </td>
                            {activeTabId === 'resident-postings' && column.label === 'Posting Code' ? (
                              <>
                                <td><RawPostingCell fragments={rawMatches} /></td>
                                <td><ParserDecisionCell fragments={rawMatches} /></td>
                                <td className="raw-source-cell"><RawSourceCell fragments={rawMatches} /></td>
                              </>
                            ) : null}
                          </Fragment>
                        ))}
                        <td className="cell-chevron">
                          <IconChevRight size={14} />
                        </td>
                      </tr>
                    )
                  })}
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
          </>
        )}
      </section>

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
            {activeTabId === 'resident-postings' ? (
              <div className="detail-block raw-fragment-list">
                <h3>Raw source traceability</h3>
                <p>RDB upload source: {selectedRdbLogLabel ?? '-'}</p>
                {isRawLogLoading || isRawDetailLoading ? (
                  <p>Loading raw source context...</p>
                ) : selectedRowRawFragments.length === 0 ? (
                  <p>No raw fragment mapped to this posting row.</p>
                ) : (
                  selectedRowRawSourceGroups.map((sourceGroup) => (
                    <div key={sourceGroup.key} className="raw-fragment-detail-card">
                      <div className="parsed-data-detail-grid raw-source-group-grid">
                        <div className="parsed-data-detail-item">
                          <span>Source</span>
                          <strong>{formatSource(sourceGroup.sourceFragment)}</strong>
                        </div>
                        <div className="parsed-data-detail-item">
                          <span>Source Column Header</span>
                          <strong>{formatValue(sourceGroup.sourceFragment.source_column_header)}</strong>
                        </div>
                        <div className="parsed-data-detail-item">
                          <span>Source Cell Text</span>
                          <strong className="raw-fragment-source-text">{formatValue(sourceGroup.sourceFragment.source_cell_text)}</strong>
                        </div>
                      </div>
                      {sourceGroup.postingGroups.map((postingGroup) => (
                        <div key={postingGroup.key} className="raw-posting-group-card">
                          <div className="parsed-data-detail-grid">
                            <div className="parsed-data-detail-item">
                              <span>Raw Posting Group</span>
                              <strong className="mono-cell">{formatValue(postingGroup.rawPostingCode)}</strong>
                            </div>
                            <div className="parsed-data-detail-item">
                              <span>Normalized Posting</span>
                              <strong className="mono-cell">{formatValue(postingGroup.normalizedPostingCode)}</strong>
                            </div>
                            <div className="parsed-data-detail-item">
                              <span>Parser Decision</span>
                              <strong>
                                <StatusBadge
                                  label={formatDecisionLabel(postingGroup.decision)}
                                  tone={decisionTone(postingGroup.decision)}
                                />
                              </strong>
                            </div>
                            <div className="parsed-data-detail-item">
                              <span>Effective Posting</span>
                              <strong className="mono-cell">{formatValue(postingGroup.effectivePostingCode)}</strong>
                            </div>
                            <div className="parsed-data-detail-item">
                              <span>Rule Type</span>
                              <strong>{formatValue(postingGroup.ruleType ? humanizeKey(postingGroup.ruleType) : null)}</strong>
                            </div>
                            <div className="parsed-data-detail-item">
                              <span>Rule ID</span>
                              <strong className="mono-cell">{formatValue(postingGroup.ruleId)}</strong>
                            </div>
                            <div className="parsed-data-detail-item">
                              <span>Warning</span>
                              <strong>
                                {postingGroup.warningId ? (
                                  <a
                                    href={`/admin/upload/warnings?mode=history&upload_type=rdb&search=${encodeURIComponent(postingGroup.warningId)}`}
                                  >
                                    {postingGroup.warningId}
                                  </a>
                                ) : (
                                  '-'
                                )}
                              </strong>
                            </div>
                            <div className="parsed-data-detail-item">
                              <span>Fragment Date Ranges</span>
                              <strong>
                                <ul className="raw-date-range-list">
                                  {postingGroup.fragments.map((fragment) => (
                                    <li key={fragment.id}>{formatFragmentDateRangeLine(fragment)}</li>
                                  ))}
                                </ul>
                              </strong>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ))
                )}
              </div>
            ) : null}
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
