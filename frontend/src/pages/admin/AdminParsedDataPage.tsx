import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  listParsedDataCorrections,
  listParsedAcademicMonthBoundaries,
  listParsedFormF1Records,
  listParsedResidentPostings,
  listParsedResidents,
  listParsedTeachingTargets,
  replaceParsedResidentPostingSourceCell,
  updateParsedAcademicMonthBoundary,
  updateParsedFormF1Record,
  updateParsedResident,
  updateParsedResidentPosting,
  updateParsedTeachingTarget,
} from '../../api/parsedData'
import { ApiRequestError } from '../../api/http'
import { getUploadLog, listUploadLogs } from '../../api/uploadLogs'
import { DataRevalidationCallout } from '../../components/DataRevalidationCallout'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'
import type {
  AyDateCategory,
  ParsedDataCorrectionHistoryRow,
  ParsedDataCorrectionValue,
  ParsedAcademicMonthBoundaryRow,
  ParsedDataListResponse,
  ParsedDataRow,
  ParsedFormF1RecordRow,
  ParsedDataCorrectionRequest,
  ResidentPostingReplacementRow,
  ResidentPostingSourceCellReplaceRequest,
  ParsedResidentPostingRow,
  ParsedResidentRow,
  ParsedTeachingTargetRow,
} from '../../types/parsedData'
import type { DataRevalidationImpact } from '../../types/dataRevalidation'
import type { RawMultiPostingDecision, RawMultiPostingFragment, UploadLogDetail, UploadLogListItem } from '../../types/upload'
import {
  clearMemoryCache,
  clearMemoryCacheResource,
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

type ParsedDataTabId =
  | 'residents'
  | 'resident-postings'
  | 'teaching-targets'
  | 'form-f1-records'
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
  | 'isActive'
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
  isActive: 'all' | 'true' | 'false'
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

type CorrectionMode = 'none' | 'row'
type CorrectionFieldType = 'text' | 'number' | 'boolean' | 'date' | 'select'
type FragmentDraftDayPart = '' | 'AM' | 'PM'

interface CorrectionFieldDefinition {
  key: string
  label: string
  type: CorrectionFieldType
  options?: { value: string; label: string }[]
  highRisk?: boolean
  helper?: string
}

interface FragmentDraftRange {
  id: string
  fragment_start_date: string
  fragment_end_date: string
  day_part: FragmentDraftDayPart
}

interface FragmentDraftGroup {
  id: string
  posting_code: string
  ranges: FragmentDraftRange[]
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
  isActive: 'all',
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

const draftId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`

const toFragmentDayPart = (value?: string | null): FragmentDraftDayPart => (
  value === 'AM' || value === 'PM' ? value : ''
)

const newDraftRange = (
  startDate = '',
  endDate = '',
  dayPart?: string | null,
): FragmentDraftRange => ({
  id: draftId(),
  fragment_start_date: startDate,
  fragment_end_date: endDate,
  day_part: toFragmentDayPart(dayPart),
})

const newDraftGroup = (
  postingCode = '',
  ranges: FragmentDraftRange[] = [newDraftRange()],
): FragmentDraftGroup => ({
  id: draftId(),
  posting_code: postingCode,
  ranges,
})

const buildFragmentDraftGroups = (
  row: ParsedResidentPostingRow,
  fragments: RawMultiPostingFragment[],
): FragmentDraftGroup[] => {
  if (fragments.length === 0) {
    return [
      newDraftGroup(
        row.posting_code ?? '',
        [newDraftRange(row.start_date, row.end_date, row.day_part)],
      ),
    ]
  }

  const groups = new Map<string, FragmentDraftGroup>()
  sortFragmentsByDateRange(fragments).forEach((fragment) => {
    const postingCode =
      fragment.raw_posting_code ??
      fragment.normalized_posting_code ??
      fragment.effective_posting_code ??
      row.posting_code ??
      ''
    const groupKey = postingCode || 'posting'
    const existing = groups.get(groupKey)
    const nextRange = newDraftRange(
      fragment.fragment_start_date ?? row.start_date,
      fragment.fragment_end_date ?? row.end_date,
      fragment.day_part,
    )
    if (existing) {
      existing.ranges.push(nextRange)
    } else {
      groups.set(groupKey, newDraftGroup(postingCode, [nextRange]))
    }
  })
  return Array.from(groups.values())
}

const rdbDateMonths = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const formatRdbDraftDate = (value: string) => {
  const date = new Date(`${value}T00:00:00`)
  if (Number.isNaN(date.getTime())) {
    return value || '-'
  }
  const day = String(date.getDate()).padStart(2, '0')
  return `${day}-${rdbDateMonths[date.getMonth()]}-${date.getFullYear()}`
}

const formatDraftRangeLine = (range: FragmentDraftRange) => {
  const dayPart = range.day_part ? ` ${range.day_part}` : ''
  return `(from ${formatRdbDraftDate(range.fragment_start_date)} to ${formatRdbDraftDate(range.fragment_end_date)}${dayPart})`
}

const correctedSourceCellDraftText = (groups: FragmentDraftGroup[]) =>
  groups
    .map((group) => [
      group.posting_code.trim() || '[Posting code required]',
      ...group.ranges.map(formatDraftRangeLine),
    ].join('\n'))
    .join('\n')

const fragmentDraftValidationErrors = (groups: FragmentDraftGroup[]) => {
  const errors: string[] = []
  if (groups.length === 0) {
    errors.push('At least one posting group is required.')
  }
  groups.forEach((group, groupIndex) => {
    const groupLabel = `Posting group ${groupIndex + 1}`
    if (!group.posting_code.trim()) {
      errors.push(`${groupLabel}: posting code is required.`)
    }
    if (group.ranges.length === 0) {
      errors.push(`${groupLabel}: at least one date range is required.`)
    }
    group.ranges.forEach((range, rangeIndex) => {
      const rangeLabel = `${groupLabel}, range ${rangeIndex + 1}`
      if (!range.fragment_start_date) {
        errors.push(`${rangeLabel}: start date is required.`)
      }
      if (!range.fragment_end_date) {
        errors.push(`${rangeLabel}: end date is required.`)
      }
      if (range.fragment_start_date && range.fragment_end_date && range.fragment_start_date > range.fragment_end_date) {
        errors.push(`${rangeLabel}: start date must be on or before end date.`)
      }
      if (!['', 'AM', 'PM'].includes(range.day_part)) {
        errors.push(`${rangeLabel}: day part must be full day, AM, or PM.`)
      }
    })
  })
  return errors
}

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
       { key: 'search', label: 'Search', type: 'search', placeholder: 'Session or tag...' },
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
    ],
  },
]

const activeToBoolean = (value: 'all' | 'true' | 'false') => {
  if (value === 'all') {
    return 'all'
  }
  return value === 'true'
}

const rowValue = (row: ParsedDataRow, key: string): unknown =>
  (row as unknown as Record<string, unknown>)[key]

const draftValueForField = (row: ParsedDataRow, field: CorrectionFieldDefinition) => {
  const value = rowValue(row, field.key)
  if (field.type === 'boolean') {
    return value === true
  }
  return value === null || value === undefined ? '' : String(value)
}

const correctionValueForField = (
  field: CorrectionFieldDefinition,
  value: string | boolean,
): ParsedDataCorrectionValue => {
  if (field.type === 'boolean') {
    return value === true
  }
  const text = String(value).trim()
  if (!text) {
    return null
  }
  if (field.type === 'number') {
    const numeric = Number(text)
    return Number.isFinite(numeric) ? numeric : text
  }
  return text
}

const comparableCorrectionValue = (value: unknown) => {
  if (value === null || value === undefined || value === '') {
    return null
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null
  }
  if (typeof value === 'boolean') {
    return value
  }
  return String(value)
}

const buildCorrectionChanges = (
  row: ParsedDataRow,
  fields: CorrectionFieldDefinition[],
  draft: Record<string, string | boolean>,
) => fields.reduce<Record<string, ParsedDataCorrectionValue>>((changes, field) => {
  const nextValue = correctionValueForField(field, draft[field.key] ?? '')
  if (comparableCorrectionValue(rowValue(row, field.key)) !== comparableCorrectionValue(nextValue)) {
    changes[field.key] = nextValue
  }
  return changes
}, {})

const correctionErrorMessage = (error: unknown) => {
  if (error instanceof ApiRequestError && error.status === 409) {
    return 'This row changed since you opened it. Refresh and review the latest value before applying corrections.'
  }
  if (error instanceof ApiRequestError) {
    if (error.status === 403) {
      return 'You do not have permission to apply this correction.'
    }
    if (error.status === 404) {
      return 'This row could not be found. Refresh and review the latest live data.'
    }
    if (error.status === 422) {
      return formatUserFacingApiError(error, {
        validationMessage: 'The correction was rejected. Review the fields and try again.',
      })
    }
    if (error.isNetworkError) {
      return formatUserFacingApiError(error, {
        fallbackMessage: 'Unable to apply correction.',
      })
    }
  }
  return formatUserFacingApiError(error, {
    fallbackMessage: 'Unable to apply correction.',
  })
}

const formatJsonPreview = (value: unknown) => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return formatValue(value)
  }
  if (Array.isArray(value)) {
    return `${value.length.toLocaleString('en-SG')} item${value.length === 1 ? '' : 's'}`
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    const displayValue =
      optionalString(record.name) ??
      optionalString(record.resident_name) ??
      optionalString(record.session_type_name) ??
      optionalString(record.keyword) ??
      optionalString(record.label)
    return displayValue ?? `${Object.keys(record).length.toLocaleString('en-SG')} fields`
  }
  return String(value)
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const toRecord = (value: unknown): Record<string, unknown> => (
  isRecord(value) ? value : {}
)

const arrayValue = (value: unknown): unknown[] => (Array.isArray(value) ? value : [])

const correctionActionLabels: Record<string, string> = {
  'admin.parsed_data.resident.update': 'Resident updated',
  'admin.parsed_data.resident_posting.update': 'Resident posting updated',
  'admin.parsed_data.teaching_target.update': 'Teaching target updated',
  'admin.parsed_data.form_f1_record.update': 'FormF1 record updated',
  'admin.parsed_data.academic_month_boundary.update': 'Academic month boundary updated',
  'admin.parsed_data.resident_posting.source_cell_replace': 'Resident posting source-cell result replaced',
}

const correctionFieldLabels: Record<string, string> = {
  employee_code: 'Employee Code',
  name: 'Name',
  mcr: 'MCR',
  classification: 'Classification',
  programme_code: 'Programme',
  r_year: 'R Year',
  reg_type: 'Registration Type',
  base_institution: 'Base Institution',
  email: 'Email',
  phone: 'Phone',
  status: 'Status',
  employer_tag: 'Employer Tag',
  posting_code: 'Posting Code',
  start_date: 'Start Date',
  end_date: 'End Date',
  day_part: 'Day Part',
  month_label: 'Month',
  loa_type: 'LOA Type',
  loa_start_date: 'LOA Start',
  loa_end_date: 'LOA End',
  refresher_training_type: 'Refresher Training Type',
  refresher_training_start: 'Refresher Training Start',
  refresher_training_end: 'Refresher Training End',
  active_months_weight: 'Active Weight',
  working_days_in_month: 'Working Days',
  monthly_target: 'Monthly Target',
  is_tracked: 'Tracked',
  is_reallocatable: 'Reallocatable',
  tag: 'Tag',
  status_raw: 'FormF1 Status',
  is_active: 'Active',
  promotion_date: 'Promotion Date',
  academic_year_label: 'Academic Year',
  ay_date_category: 'AY Date Category',
}

const hiddenCorrectionDiffFields = new Set([
  'id',
  'resident_id',
  'reporting_period_id',
  'reporting_period_label',
  'session_type_id',
  'upload_id',
  'created_at',
  'updated_at',
])

const hiddenParsedDataDetailFields = new Set([
  'id',
  'resident_id',
  'reporting_period_id',
  'session_type_id',
  'upload_id',
])

const parsedDataDetailEntries = (row: ParsedDataRow) =>
  Object.entries(row).filter(([key]) => !hiddenParsedDataDetailFields.has(key) && !key.endsWith('_id'))

const formatCorrectionActionLabel = (action: string) =>
  correctionActionLabels[action] ?? humanizeKey(action.replace(/^admin\.parsed_data\./, '').replace(/\./g, '_'))

const formatCorrectionFieldLabel = (fieldKey: string) =>
  correctionFieldLabels[fieldKey] ?? humanizeKey(fieldKey)

const normalisedDiffValue = (value: unknown): unknown => {
  if (value === undefined || value === null || value === '') {
    return null
  }
  if (Array.isArray(value)) {
    return value.map(normalisedDiffValue)
  }
  if (isRecord(value)) {
    return Object.fromEntries(
      Object.entries(value).map(([key, entry]) => [key, normalisedDiffValue(entry)]),
    )
  }
  return value
}

const valuesAreEqual = (left: unknown, right: unknown) =>
  JSON.stringify(normalisedDiffValue(left)) === JSON.stringify(normalisedDiffValue(right))

const updatedFieldsFromMetadata = (metadata: unknown) => {
  const fields = toRecord(metadata).updated_fields
  return Array.isArray(fields)
    ? fields.map((field) => String(field)).filter(Boolean)
    : []
}

interface CorrectionFieldChange {
  key: string
  before: unknown
  after: unknown
}

const getChangedFields = (
  before: unknown,
  after: unknown,
  metadata: unknown,
): CorrectionFieldChange[] => {
  const beforeRow = toRecord(before)
  const afterRow = toRecord(after)
  const preferredFields = updatedFieldsFromMetadata(metadata)
  const candidateFields = preferredFields.length > 0
    ? preferredFields
    : Array.from(new Set([...Object.keys(beforeRow), ...Object.keys(afterRow)]))
      .filter((key) => !hiddenCorrectionDiffFields.has(key))
  return candidateFields
    .filter((key) => !hiddenCorrectionDiffFields.has(key))
    .filter((key) => !valuesAreEqual(beforeRow[key], afterRow[key]))
    .map((key) => ({ key, before: beforeRow[key], after: afterRow[key] }))
}

const looksLikeDateField = (fieldKey?: string) =>
  Boolean(fieldKey && (fieldKey.endsWith('_date') || fieldKey === 'start_date' || fieldKey === 'end_date'))

const formatPostingRowSummary = (value: unknown) => {
  const row = toRecord(value)
  const posting = optionalString(row.posting_code) ?? 'No posting code'
  const start = optionalString(row.start_date) ?? '-'
  const end = optionalString(row.end_date) ?? '-'
  const dayPart = optionalString(row.day_part) ?? 'Full day'
  const month = optionalString(row.month_label)
  return [posting, `${start} to ${end}`, dayPart, month].filter(Boolean).join(' | ')
}

const formatCorrectionValue = (value: unknown, fieldKey?: string): string => {
  if (value === null || value === undefined || value === '') {
    return '-'
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No'
  }
  if (typeof value === 'number') {
    return formatNumber(value)
  }
  if (typeof value === 'string') {
    return looksLikeDateField(fieldKey) ? formatDate(value) : value
  }
  if (Array.isArray(value)) {
    const formattedItems = value.map((item) => formatCorrectionValue(item, fieldKey)).filter((item) => item !== '-')
    if (formattedItems.length <= 4) {
      return formattedItems.join(', ') || '-'
    }
    return `${formattedItems.length} items: ${formattedItems.slice(0, 3).join(', ')}...`
  }
  if (isRecord(value)) {
    if ('posting_code' in value || 'start_date' in value || 'end_date' in value) {
      return formatPostingRowSummary(value)
    }
    const displayValue =
      optionalString(value.name) ??
      optionalString(value.resident_name) ??
      optionalString(value.session_type_name) ??
      optionalString(value.keyword) ??
      optionalString(value.label)
    return displayValue ?? `${Object.keys(value).length} fields`
  }
  return String(value)
}

const sourceFromMetadata = (metadata: unknown) => {
  const details = toRecord(metadata)
  const verified = details.verified_source_metadata
  const source = details.source
  const clientSource = details.client_selected_source_metadata
  if (isRecord(verified)) {
    return verified
  }
  if (isRecord(source)) {
    return source
  }
  if (isRecord(clientSource)) {
    return clientSource
  }
  return {}
}

const hasSourceSummary = (metadata: unknown) => {
  const source = sourceFromMetadata(metadata)
  return Boolean(source.sheet_name || source.row_number || source.cell_ref || source.source_metadata_verified)
}

const renderCorrectionDiff = (entry: ParsedDataCorrectionHistoryRow) => {
  const changes = getChangedFields(entry.before_json, entry.after_json, entry.metadata_json)
  if (changes.length === 0) {
    return <p>No changed fields were recorded for this audit entry.</p>
  }
  if (changes.length === 1) {
    const change = changes[0]
    return (
      <dl className="correction-summary-list">
        <dt>Field</dt>
        <dd>{formatCorrectionFieldLabel(change.key)}</dd>
        <dt>Before</dt>
        <dd>{formatCorrectionValue(change.before, change.key)}</dd>
        <dt>After</dt>
        <dd>{formatCorrectionValue(change.after, change.key)}</dd>
      </dl>
    )
  }
  return (
    <div className="correction-diff-table" role="table" aria-label="Changed fields">
      <div className="correction-diff-row correction-diff-header" role="row">
        <span role="columnheader">Field</span>
        <span role="columnheader">Before</span>
        <span role="columnheader">After</span>
      </div>
      {changes.map((change) => (
        <div key={change.key} className="correction-diff-row" role="row">
          <span role="cell">{formatCorrectionFieldLabel(change.key)}</span>
          <span role="cell">{formatCorrectionValue(change.before, change.key)}</span>
          <span role="cell">{formatCorrectionValue(change.after, change.key)}</span>
        </div>
      ))}
    </div>
  )
}

const sourceRowsFromAudit = (payload: unknown, key: 'before_rows' | 'after_rows') => {
  const record = toRecord(payload)
  return arrayValue(record[key])
}

const renderSourceCellReplacementSummary = (entry: ParsedDataCorrectionHistoryRow) => {
  const beforeRows = sourceRowsFromAudit(entry.before_json, 'before_rows')
  const afterRows = sourceRowsFromAudit(entry.after_json, 'after_rows')
  if (beforeRows.length === 0 && afterRows.length === 0) {
    return null
  }
  return (
    <div className="source-cell-history-summary">
      <div>
        <strong>Before</strong>
        {beforeRows.length === 0 ? (
          <p>-</p>
        ) : (
          <ul>
            {beforeRows.map((row, index) => (
              <li key={`before-${index}`}>{formatPostingRowSummary(row)}</li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <strong>After</strong>
        {afterRows.length === 0 ? (
          <p>-</p>
        ) : (
          <ul>
            {afterRows.map((row, index) => (
              <li key={`after-${index}`}>{formatPostingRowSummary(row)}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

const renderSourceSummary = (metadata: unknown) => {
  if (!hasSourceSummary(metadata)) {
    return null
  }
  const details = toRecord(metadata)
  const source = sourceFromMetadata(metadata)
  const sourceText = [
    optionalString(source.sheet_name),
    source.row_number ? `Row ${String(source.row_number)}` : null,
    optionalString(source.cell_ref),
  ].filter(Boolean).join(' | ') || '-'
  const uploadedAt = optionalString(source.uploaded_at) ?? optionalString(details.uploaded_at)
  const verified = details.source_metadata_verified === true
  return (
    <dl className="correction-summary-list correction-source-summary">
      <dt>Source</dt>
      <dd>{sourceText}</dd>
      {uploadedAt ? (
        <>
          <dt>Upload</dt>
          <dd>{formatSingaporeDateTime(uploadedAt)}</dd>
        </>
      ) : null}
      <dt>Verified</dt>
      <dd>{verified ? 'Yes' : 'No - source selection was provided by the user'}</dd>
    </dl>
  )
}

const mergeCorrectionHistoryRows = (groups: ParsedDataCorrectionHistoryRow[][]) => {
  const seen = new Set<string>()
  return groups
    .flat()
    .filter((entry) => {
      if (seen.has(entry.id)) {
        return false
      }
      seen.add(entry.id)
      return true
    })
    .sort((left, right) => (
      Date.parse(right.created_at) - Date.parse(left.created_at) ||
      compareText(right.id, left.id)
    ))
}

const optimisticActionByTab: Record<ParsedDataTabId, string> = {
  residents: 'admin.parsed_data.resident.update',
  'resident-postings': 'admin.parsed_data.resident_posting.update',
  'teaching-targets': 'admin.parsed_data.teaching_target.update',
  'form-f1-records': 'admin.parsed_data.form_f1_record.update',
  'academic-month-boundaries': 'admin.parsed_data.academic_month_boundary.update',
}

const optimisticCorrectionHistoryEntry = ({
  auditLogId,
  action,
  entityType,
  entityId,
  correctionReason,
  before,
  after,
  metadata,
}: {
  auditLogId: string
  action: string
  entityType: string
  entityId: string | null
  correctionReason: string
  before: unknown
  after: unknown
  metadata: Record<string, unknown>
}): ParsedDataCorrectionHistoryRow => ({
  id: auditLogId,
  created_at: new Date().toISOString(),
  actor_user_id: null,
  actor_role: 'admin',
  actor_name: 'Unknown actor',
  action,
  entity_type: entityType,
  entity_id: entityId,
  correction_reason: correctionReason,
  before_json: before,
  after_json: after,
  metadata_json: {
    source_page: 'parsed_data',
    correction_reason: correctionReason,
    ...metadata,
  },
})

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

const residentPostingStatusOptions = [
  { value: 'active', label: 'Active' },
  { value: 'loa', label: 'LOA' },
  { value: 'loa_working', label: 'LOA, continue working' },
  { value: 'employed', label: 'Employed' },
]

const dayPartOptions = [
  { value: '', label: 'Full day' },
  { value: 'AM', label: 'AM' },
  { value: 'PM', label: 'PM' },
]

const formF1StatusOptions = [
  { value: '', label: 'Blank (Inactive)' },
  { value: 'Active', label: 'Active' },
  { value: 'Extension', label: 'Extension' },
  { value: 'Inactive', label: 'Inactive' },
]

const ayDateCategoryOptions = [
  { value: 'im_subspec', label: 'IM subspec' },
  { value: 'non_im_subspec', label: 'Non-IM subspec' },
]

const correctionFieldsByTab: Partial<Record<ParsedDataTabId, CorrectionFieldDefinition[]>> = {
  residents: [
    { key: 'employee_code', label: 'Employee Code', type: 'text' },
    { key: 'name', label: 'Name', type: 'text' },
    { key: 'mcr', label: 'MCR', type: 'text', highRisk: true },
    { key: 'classification', label: 'Classification', type: 'text' },
    { key: 'programme_code', label: 'Programme Code', type: 'text', highRisk: true },
    { key: 'r_year', label: 'R Year', type: 'text' },
    { key: 'reg_type', label: 'Registration Type', type: 'text' },
    { key: 'base_institution', label: 'Base Institution', type: 'text' },
    { key: 'email', label: 'Email', type: 'text' },
    { key: 'phone', label: 'Phone', type: 'text' },
    { key: 'status', label: 'Status', type: 'text', highRisk: true },
    { key: 'employer_tag', label: 'Employer Tag', type: 'text', highRisk: true },
  ],
  'resident-postings': [
    { key: 'posting_code', label: 'Posting Code', type: 'text' },
    { key: 'start_date', label: 'Start Date', type: 'date' },
    { key: 'end_date', label: 'End Date', type: 'date' },
    { key: 'day_part', label: 'Day Part', type: 'select', options: dayPartOptions },
    { key: 'month_label', label: 'Month Label', type: 'text' },
    { key: 'r_year', label: 'R Year', type: 'text' },
    { key: 'status', label: 'Status', type: 'select', options: residentPostingStatusOptions },
    { key: 'loa_type', label: 'LOA Type', type: 'text' },
    { key: 'loa_start_date', label: 'LOA Start Date', type: 'date' },
    { key: 'loa_end_date', label: 'LOA End Date', type: 'date' },
    { key: 'refresher_training_type', label: 'Refresher Training Type', type: 'text' },
    { key: 'refresher_training_start', label: 'Refresher Training Start', type: 'date' },
    { key: 'refresher_training_end', label: 'Refresher Training End', type: 'date' },
    { key: 'active_months_weight', label: 'Active Months Weight', type: 'number' },
    { key: 'working_days_in_month', label: 'Working Days In Month', type: 'number' },
  ],
  'teaching-targets': [
    { key: 'monthly_target', label: 'Monthly Target', type: 'number' },
    { key: 'is_tracked', label: 'Tracked', type: 'boolean' },
    { key: 'is_reallocatable', label: 'Reallocatable', type: 'boolean' },
    { key: 'tag', label: 'Tag', type: 'text' },
  ],
  'form-f1-records': [
    { key: 'status_raw', label: 'Status Raw', type: 'select', options: formF1StatusOptions },
    { key: 'is_active', label: 'Active', type: 'boolean' },
    { key: 'promotion_date', label: 'Promotion Date', type: 'date' },
  ],
  'academic-month-boundaries': [
    { key: 'academic_year_label', label: 'Academic Year Label', type: 'text' },
    { key: 'ay_date_category', label: 'AY Date Category', type: 'select', options: ayDateCategoryOptions },
    { key: 'month_label', label: 'Month Label', type: 'text' },
    { key: 'start_date', label: 'Start Date', type: 'date' },
    { key: 'end_date', label: 'End Date', type: 'date' },
  ],
}

const entityTypeByTab: Record<ParsedDataTabId, string> = {
  residents: 'resident',
  'resident-postings': 'resident_posting',
  'teaching-targets': 'teaching_target',
  'form-f1-records': 'form_f1_record',
  'academic-month-boundaries': 'academic_month_boundary',
}

export const AdminParsedDataPage = () => {
  const {
    authCacheScope,
    demoAdminId,
    demoAdminProgrammes,
    reportingPeriods,
  } = useAppState()
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
  const [correctionMode, setCorrectionMode] = useState<CorrectionMode>('none')
  const [correctionDraft, setCorrectionDraft] = useState<Record<string, string | boolean>>({})
  const [fragmentDraftGroups, setFragmentDraftGroups] = useState<FragmentDraftGroup[]>([])
  const [isFragmentCorrection, setIsFragmentCorrection] = useState(false)
  const [correctionReason, setCorrectionReason] = useState('')
  const [correctionError, setCorrectionError] = useState<string | null>(null)
  const [correctionSuccess, setCorrectionSuccess] = useState<string | null>(null)
  const [correctionRevalidation, setCorrectionRevalidation] =
    useState<DataRevalidationImpact | null>(null)
  const [isCorrectionSubmitting, setIsCorrectionSubmitting] = useState(false)
  const [correctionHistory, setCorrectionHistory] = useState<ParsedDataCorrectionHistoryRow[]>([])
  const [isCorrectionHistoryLoading, setIsCorrectionHistoryLoading] = useState(false)
  const [correctionHistoryError, setCorrectionHistoryError] = useState<string | null>(null)
  const [lastOptimisticHistory, setLastOptimisticHistory] = useState<{
    rowId: string
    entry: ParsedDataCorrectionHistoryRow
  } | null>(null)
  const authScopeKey = useMemo(
    () => makeScopedCacheKey(authCacheScope, 'admin.parsed-data.auth-scope', {}),
    [authCacheScope],
  )
  const currentAuthScopeKeyRef = useRef(authScopeKey)
  const rowsRequestRef = useRef(0)
  const rawLogRequestRef = useRef(0)
  const rawDetailRequestRef = useRef(0)
  const historyRequestRef = useRef(0)
  const correctionRequestRef = useRef(0)
  const rowsRequestContextKey = useMemo(
    () => makeScopedCacheKey(authCacheScope, 'admin.parsed-data.request-context', {
      activeTabId,
      filters,
      offset,
    }),
    [activeTabId, authCacheScope, filters, offset],
  )
  const currentRowsRequestContextKeyRef = useRef(rowsRequestContextKey)
  const rawRequestContextKey = useMemo(
    () => makeScopedCacheKey(authCacheScope, 'admin.parsed-data.raw-request-context', {
      activeTabId,
    }),
    [activeTabId, authCacheScope],
  )
  const currentRawRequestContextKeyRef = useRef(rawRequestContextKey)
  const rawDetailRequestContextKey = useMemo(
    () => makeScopedCacheKey(authCacheScope, 'admin.parsed-data.raw-detail-request-context', {
      activeTabId,
      selectedRdbUploadId,
    }),
    [activeTabId, authCacheScope, selectedRdbUploadId],
  )
  const currentRawDetailRequestContextKeyRef = useRef(rawDetailRequestContextKey)

  useLayoutEffect(() => {
    currentAuthScopeKeyRef.current = authScopeKey
  }, [authScopeKey])
  useLayoutEffect(() => {
    currentRowsRequestContextKeyRef.current = rowsRequestContextKey
    rowsRequestRef.current += 1
    historyRequestRef.current += 1
    correctionRequestRef.current += 1
  }, [rowsRequestContextKey])
  useLayoutEffect(() => {
    currentRawRequestContextKeyRef.current = rawRequestContextKey
    rawLogRequestRef.current += 1
  }, [rawRequestContextKey])
  useLayoutEffect(() => {
    currentRawDetailRequestContextKeyRef.current = rawDetailRequestContextKey
    rawDetailRequestRef.current += 1
  }, [rawDetailRequestContextKey])
  const beginCorrectionRequest = useCallback(() => {
    const requestId = correctionRequestRef.current + 1
    correctionRequestRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(authScopeKey, requestId)
    return () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentAuthScopeKeyRef.current,
      correctionRequestRef.current,
    )
  }, [authScopeKey])

  const activeTab = useMemo(
    () => tabDefinitions.find((tab) => tab.id === activeTabId) ?? tabDefinitions[0],
    [activeTabId],
  )
  const correctionFields = useMemo(() => correctionFieldsByTab[activeTabId] ?? [], [activeTabId])

  const adminRequestParams = useMemo(() => ({
    adminId: demoAdminId,
    adminProgrammes: demoAdminProgrammes,
    adminLevel: 'master' as const,
  }), [demoAdminId, demoAdminProgrammes])

  const parsedDataCacheKey = useCallback((
    tabId: ParsedDataTabId,
    queryFilters: ParsedDataFilters,
    queryOffset: number,
  ) => makeScopedCacheKey(authCacheScope, 'admin.parsed-data', {
    view: tabId,
    filters: queryFilters,
    limit: pageSize,
    offset: queryOffset,
  }), [authCacheScope])

  const uploadLogListCacheKey = useCallback(() => makeScopedCacheKey(authCacheScope, 'admin.upload-logs.rdb-source-list', {
    uploadType: 'rdb',
    limit: 50,
  }), [authCacheScope])

  const uploadLogDetailCacheKey = useCallback((uploadLogId: string) => makeScopedCacheKey(
    authCacheScope,
    'admin.upload-logs.rdb-source-detail',
    { uploadLogId },
  ), [authCacheScope])

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
    let active = true
    queueMicrotask(() => {
      if (!active) {
        return
      }
      hasLoadedRowsRef.current = false
      setRows([])
      setTotal(0)
      setError(null)
      setSelectedRow(null)
      setRdbUploadLogs([])
      setSelectedRdbUploadId(null)
      setSelectedRdbUploadDetail(null)
      setRawFragmentError(null)
      setIsRawLogLoading(true)
      setIsRawDetailLoading(false)
      setCorrectionMode('none')
      setCorrectionDraft({})
      setFragmentDraftGroups([])
      setIsFragmentCorrection(false)
      setCorrectionReason('')
      setCorrectionError(null)
      setCorrectionSuccess(null)
      setCorrectionRevalidation(null)
      setIsCorrectionSubmitting(false)
      setCorrectionHistory([])
      setCorrectionHistoryError(null)
      setIsCorrectionHistoryLoading(false)
      setLastOptimisticHistory(null)
      setIsManualRefreshing(false)
      setIsRefetching(false)
      setIsInitialLoading(true)
    })
    return () => {
      active = false
    }
  }, [authScopeKey])

  useEffect(() => {
    let active = true
    queueMicrotask(() => {
      if (!active) {
        return
      }
      setCorrectionMode('none')
      setCorrectionReason('')
      setCorrectionError(null)
      setCorrectionSuccess(null)
      setCorrectionDraft(
        selectedRow
          ? correctionFields.reduce<Record<string, string | boolean>>((draft, field) => {
            draft[field.key] = draftValueForField(selectedRow, field)
            return draft
          }, {})
          : {},
      )
    })
    return () => {
      active = false
    }
  }, [correctionFields, selectedRow])

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
    const requestId = rowsRequestRef.current + 1
    rowsRequestRef.current = requestId
    historyRequestRef.current += 1
    correctionRequestRef.current += 1
    setIsManualRefreshing(true)
    setError(null)
    setSelectedRow(null)
    const key = parsedDataCacheKey(activeTabId, filters, offset)
    clearMemoryCache((cacheKey) => cacheKey === key)
    clearMemoryCacheResource('admin.upload-logs.rdb-source-list')
    clearMemoryCacheResource('admin.upload-logs.rdb-source-detail')
    const requestFence = captureProtectedAsyncRequestFence(rowsRequestContextKey, requestId)
    const isCurrentRequest = () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentRowsRequestContextKeyRef.current,
      rowsRequestRef.current,
    )

    try {
      const { data: response } = await readThroughMemoryCache(
        key,
        () => loadRows(activeTabId, filters, offset),
        { force: true },
      )
      if (!isCurrentRequest()) {
        return
      }
      setDebouncedFilters((previous) => (areFiltersEqual(previous, filters) ? previous : filters))
      setRows(sortParsedRowsForDisplay(activeTabId, response.items))
      setTotal(response.total)
      hasLoadedRowsRef.current = true
    } catch (fetchError) {
      if (isMemoryCacheInvalidatedError(fetchError) || !isCurrentRequest()) {
        return
      }
      setRows([])
      setTotal(0)
      hasLoadedRowsRef.current = true
      setError(formatUserFacingApiError(fetchError, {
        fallbackMessage: 'Unable to load parsed data.',
      }))
    } finally {
      if (isCurrentRequest()) {
        setIsManualRefreshing(false)
        setIsInitialLoading(false)
        setIsRefetching(false)
      }
    }
  }, [activeTabId, filters, loadRows, offset, parsedDataCacheKey, rowsRequestContextKey])

  const refreshActiveRowsAfterMutation = useCallback(async (nextSelectedRow?: ParsedDataRow | null) => {
    const requestId = rowsRequestRef.current + 1
    rowsRequestRef.current = requestId
    clearMemoryCacheResource('admin.parsed-data')
    clearMemoryCacheResource('admin.upload-logs.rdb-source-detail')
    const requestFence = captureProtectedAsyncRequestFence(rowsRequestContextKey, requestId)
    const isCurrentRequest = () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentRowsRequestContextKeyRef.current,
      rowsRequestRef.current,
    )
    setIsRefetching(true)
    try {
      const key = parsedDataCacheKey(activeTabId, debouncedFilters, offset)
      const { data: response } = await readThroughMemoryCache(
        key,
        () => loadRows(activeTabId, debouncedFilters, offset),
        { force: true },
      )
      if (!isCurrentRequest()) {
        return
      }
      setRows(sortParsedRowsForDisplay(activeTabId, response.items))
      setTotal(response.total)
      if (nextSelectedRow) {
        const refreshedRow = response.items.find((item) => item.id === nextSelectedRow.id) ?? nextSelectedRow
        setSelectedRow(refreshedRow)
      }
    } catch (fetchError) {
      if (isMemoryCacheInvalidatedError(fetchError) || !isCurrentRequest()) {
        return
      }
      setError(formatUserFacingApiError(fetchError, {
        fallbackMessage: 'Unable to refresh live data.',
      }))
      if (nextSelectedRow) {
        setSelectedRow(nextSelectedRow)
      }
    } finally {
      if (isCurrentRequest()) {
        setIsRefetching(false)
      }
    }
  }, [activeTabId, debouncedFilters, loadRows, offset, parsedDataCacheKey, rowsRequestContextKey])

  useEffect(() => {
    let active = true
    ;(async () => {
      if (!areFiltersEqual(debouncedFilters, filters)) {
        return
      }
      const requestId = rowsRequestRef.current + 1
      rowsRequestRef.current = requestId
      historyRequestRef.current += 1
      correctionRequestRef.current += 1
      const requestFence = captureProtectedAsyncRequestFence(rowsRequestContextKey, requestId)
      const isCurrentRequest = () => active && isProtectedAsyncRequestFenceCurrent(
        requestFence,
        currentRowsRequestContextKeyRef.current,
        rowsRequestRef.current,
      )
      const key = parsedDataCacheKey(activeTabId, debouncedFilters, offset)
      const cached = getMemoryCache<ParsedDataListResponse<ParsedDataRow>>(key)
      if (cached && isCurrentRequest()) {
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
        if (isCurrentRequest()) {
          setRows(sortParsedRowsForDisplay(activeTabId, response.items))
          setTotal(response.total)
          hasLoadedRowsRef.current = true
        }
      } catch (fetchError) {
        if (!isMemoryCacheInvalidatedError(fetchError) && isCurrentRequest()) {
          if (!isBackgroundRefetch) {
            setRows([])
            setTotal(0)
          }
          hasLoadedRowsRef.current = true
          setError(formatUserFacingApiError(fetchError, {
            fallbackMessage: 'Unable to load parsed data.',
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
    activeTabId,
    debouncedFilters,
    filters,
    loadRows,
    offset,
    parsedDataCacheKey,
    rowsRequestContextKey,
  ])

  const loadRdbUploadLogs = useCallback(async () => {
    if (activeTabId !== 'resident-postings') {
      return
    }
    const requestId = rawLogRequestRef.current + 1
    rawLogRequestRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(rawRequestContextKey, requestId)
    const isCurrentRequest = () => isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentRawRequestContextKeyRef.current,
      rawLogRequestRef.current,
    )
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
      if (!isCurrentRequest()) {
        return
      }
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
      if (isMemoryCacheInvalidatedError(fetchError) || !isCurrentRequest()) {
        return
      }
      setRdbUploadLogs([])
      setSelectedRdbUploadId(null)
      setSelectedRdbUploadDetail(null)
      setRawFragmentError(formatUserFacingApiError(fetchError, {
        fallbackMessage: 'Unable to load RDB upload logs.',
      }))
    } finally {
      if (isCurrentRequest()) {
        setIsRawLogLoading(false)
      }
    }
  }, [
    activeTabId,
    demoAdminId,
    demoAdminProgrammes,
    rawRequestContextKey,
    uploadLogListCacheKey,
  ])

  useEffect(() => {
    if (activeTabId === 'resident-postings') {
      let active = true
      queueMicrotask(() => {
        if (active) {
          void loadRdbUploadLogs()
        }
      })
      return () => {
        active = false
      }
    }
  }, [activeTabId, loadRdbUploadLogs])

  useEffect(() => {
    let active = true
    if (activeTabId !== 'resident-postings' || !selectedRdbUploadId) {
      queueMicrotask(() => {
        if (active) {
          setSelectedRdbUploadDetail(null)
          setIsRawDetailLoading(false)
        }
      })
      return () => {
        active = false
      }
    }

    ;(async () => {
      const requestId = rawDetailRequestRef.current + 1
      rawDetailRequestRef.current = requestId
      const requestFence = captureProtectedAsyncRequestFence(rawDetailRequestContextKey, requestId)
      const isCurrentRequest = () => active && isProtectedAsyncRequestFenceCurrent(
        requestFence,
        currentRawDetailRequestContextKeyRef.current,
        rawDetailRequestRef.current,
      )
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
        if (isCurrentRequest()) {
          setSelectedRdbUploadDetail(detail)
        }
      } catch (fetchError) {
        if (!isMemoryCacheInvalidatedError(fetchError) && isCurrentRequest()) {
          setSelectedRdbUploadDetail(null)
          setRawFragmentError(formatUserFacingApiError(fetchError, {
            fallbackMessage: 'Unable to load RDB upload detail.',
          }))
        }
      } finally {
        if (isCurrentRequest()) {
          setIsRawDetailLoading(false)
        }
      }
    })()

    return () => {
      active = false
    }
  }, [
    activeTabId,
    demoAdminId,
    demoAdminProgrammes,
    rawDetailRequestContextKey,
    selectedRdbUploadId,
    uploadLogDetailCacheKey,
  ])

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
        selectedRdbUploadDetail.reporting_period_label ?? 'Reporting period unavailable',
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
  const selectedRowRawFragments = useMemo(() => (
    selectedRow && activeTabId === 'resident-postings'
      ? matchingRawFragmentsForPosting(selectedRow as ParsedResidentPostingRow, rawFragments)
      : []
  ), [activeTabId, rawFragments, selectedRow])
  const selectedRowRawSourceGroups = useMemo(
    () => groupRawFragmentsForDrawer(selectedRowRawFragments),
    [selectedRowRawFragments],
  )
  const selectedSourceGroup = selectedRowRawSourceGroups[0] ?? null
  const selectedSourceGroupKey = selectedSourceGroup?.key ?? null
  const selectedSourceFragment = selectedSourceGroup?.sourceFragment ?? null
  const affectedSourceCellRows = useMemo(() => {
    if (!selectedRow || activeTabId !== 'resident-postings') {
      return []
    }
    const selectedPostingRow = selectedRow as ParsedResidentPostingRow
    if (!selectedSourceGroupKey) {
      return [selectedPostingRow]
    }
    const matchingRows = rows.filter((row): row is ParsedResidentPostingRow => {
      const postingRow = row as ParsedResidentPostingRow
      return (rawFragmentsByPostingId.get(postingRow.id) ?? [])
        .some((fragment) => rawSourceGroupKey(fragment) === selectedSourceGroupKey)
    })
    return matchingRows.some((row) => row.id === selectedPostingRow.id)
      ? matchingRows
      : [selectedPostingRow]
  }, [activeTabId, rawFragmentsByPostingId, rows, selectedRow, selectedSourceGroupKey])
  const hasResidentPostingSourceContext = Boolean(
    activeTabId === 'resident-postings' &&
    selectedRow &&
    selectedRowRawFragments.length > 0,
  )
  const loadCorrectionHistoryForRow = useCallback(async (
    row: ParsedDataRow,
    sourceFragment: RawMultiPostingFragment | null,
  ) => {
    const requests = [
      listParsedDataCorrections({
        ...adminRequestParams,
        entityType: activeTabId === 'resident-postings' ? undefined : entityTypeByTab[activeTabId],
        entityId: row.id,
        limit: 50,
      }),
    ]
    if (
      activeTabId === 'resident-postings' &&
      sourceFragment &&
      selectedRdbUploadId &&
      sourceFragment.sheet_name &&
      sourceFragment.row_number &&
      sourceFragment.cell_ref
    ) {
      requests.push(listParsedDataCorrections({
        ...adminRequestParams,
        uploadLogId: selectedRdbUploadId,
        sheetName: sourceFragment.sheet_name,
        rowNumber: sourceFragment.row_number,
        cellRef: sourceFragment.cell_ref,
        limit: 50,
      }))
    }
    const responses = await Promise.all(requests)
    return mergeCorrectionHistoryRows(responses.map((response) => response.items))
  }, [activeTabId, adminRequestParams, selectedRdbUploadId])
  useEffect(() => {
    let active = true
    const requestId = historyRequestRef.current + 1
    historyRequestRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(authScopeKey, requestId)
    const isCurrentRequest = () => active && isProtectedAsyncRequestFenceCurrent(
      requestFence,
      currentAuthScopeKeyRef.current,
      historyRequestRef.current,
    )
    if (!selectedRow) {
      queueMicrotask(() => {
        if (isCurrentRequest()) {
          setLastOptimisticHistory(null)
          setCorrectionHistory([])
          setCorrectionHistoryError(null)
          setIsCorrectionHistoryLoading(false)
        }
      })
      return () => {
        active = false
      }
    }

    ;(async () => {
      setIsCorrectionHistoryLoading(true)
      setCorrectionHistoryError(null)
      try {
        const items = await loadCorrectionHistoryForRow(selectedRow, selectedSourceFragment)
        if (isCurrentRequest()) {
          setCorrectionHistory(
            lastOptimisticHistory?.rowId === selectedRow.id
              ? mergeCorrectionHistoryRows([items, [lastOptimisticHistory.entry]])
              : items,
          )
        }
      } catch (fetchError) {
        if (isCurrentRequest()) {
          setCorrectionHistory([])
          setCorrectionHistoryError(formatUserFacingApiError(fetchError, {
            fallbackMessage: 'Unable to load correction history.',
          }))
        }
      } finally {
        if (isCurrentRequest()) {
          setIsCorrectionHistoryLoading(false)
        }
      }
    })()

    return () => {
      active = false
    }
  }, [
    authScopeKey,
    lastOptimisticHistory,
    loadCorrectionHistoryForRow,
    selectedRow,
    selectedSourceFragment,
  ])
  useEffect(() => {
    let active = true
    queueMicrotask(() => {
      if (!active) {
        return
      }
      if (selectedRow && activeTabId === 'resident-postings') {
        setFragmentDraftGroups(buildFragmentDraftGroups(
          selectedRow as ParsedResidentPostingRow,
          selectedRowRawFragments,
        ))
      } else {
        setFragmentDraftGroups([])
      }
    })
    return () => {
      active = false
    }
  }, [activeTabId, selectedRow, selectedRowRawFragments])
  useEffect(() => {
    if (correctionMode === 'none') {
      let active = true
      queueMicrotask(() => {
        if (active) {
          setIsFragmentCorrection(hasResidentPostingSourceContext)
        }
      })
      return () => {
        active = false
      }
    }
  }, [correctionMode, hasResidentPostingSourceContext])
  const changedCorrectionFields = selectedRow
    ? correctionFields.filter((field) => field.key in buildCorrectionChanges(selectedRow, correctionFields, correctionDraft))
    : []
  const fragmentDraftErrors = fragmentDraftValidationErrors(fragmentDraftGroups)
  const isTeachingTargetReallocatableDraft = activeTabId === 'teaching-targets' && correctionDraft.is_reallocatable === true

  const resetCorrectionDraft = () => {
    if (!selectedRow) {
      setCorrectionDraft({})
      setCorrectionReason('')
      return
    }
    setCorrectionDraft(correctionFields.reduce<Record<string, string | boolean>>((draft, field) => {
      draft[field.key] = draftValueForField(selectedRow, field)
      return draft
    }, {}))
    if (activeTabId === 'resident-postings') {
      setFragmentDraftGroups(buildFragmentDraftGroups(
        selectedRow as ParsedResidentPostingRow,
        selectedRowRawFragments,
      ))
      setIsFragmentCorrection(selectedRowRawFragments.length > 0)
    } else {
      setIsFragmentCorrection(false)
    }
    setCorrectionReason('')
    setCorrectionError(null)
    setCorrectionSuccess(null)
    setCorrectionRevalidation(null)
  }

  const setCorrectionDraftField = (field: CorrectionFieldDefinition, value: string | boolean) => {
    setCorrectionDraft((prev) => {
      const next = { ...prev, [field.key]: value }
      if (activeTabId === 'form-f1-records' && field.key === 'status_raw') {
        if (value === 'Active' || value === 'Extension') {
          next.is_active = true
        }
        if (value === 'Inactive' || value === '') {
          next.is_active = false
        }
      }
      if (activeTabId === 'teaching-targets' && field.key === 'is_reallocatable' && value !== true) {
        next.tag = ''
      }
      return next
    })
    setCorrectionError(null)
    setCorrectionSuccess(null)
    setCorrectionRevalidation(null)
  }

  const submitRowCorrection = async () => {
    if (!selectedRow) {
      return
    }
    const changes = buildCorrectionChanges(selectedRow, correctionFields, correctionDraft)
    if (Object.keys(changes).length === 0) {
      setCorrectionError('Change at least one field before applying a correction.')
      return
    }
    if (!correctionReason.trim()) {
      setCorrectionError('Correction reason is required.')
      return
    }

    const request: ParsedDataCorrectionRequest = {
      changes,
      correction_reason: correctionReason.trim(),
      last_seen_updated_at: optionalString(rowValue(selectedRow, 'updated_at')),
    }
    const isCurrentRequest = beginCorrectionRequest()

    setIsCorrectionSubmitting(true)
    setCorrectionError(null)
    setCorrectionHistoryError(null)
    setCorrectionRevalidation(null)
    try {
      let updatedRow: ParsedDataRow
      let auditLogId = ''
      let entityType = entityTypeByTab[activeTabId]
      let entityId: string | null = selectedRow.id
      let updatedFields: string[] = []
      let dataRevalidation: DataRevalidationImpact | null | undefined
      switch (activeTabId) {
        case 'residents':
          {
            const response = await updateParsedResident(adminRequestParams, selectedRow.id, request)
            updatedRow = response.item
            auditLogId = response.audit_log_id
            entityType = response.entity_type
            entityId = response.entity_id
            updatedFields = response.updated_fields
            dataRevalidation = response.dataRevalidation
          }
          break
        case 'resident-postings':
          {
            const response = await updateParsedResidentPosting(adminRequestParams, selectedRow.id, request)
            updatedRow = response.item
            auditLogId = response.audit_log_id
            entityType = response.entity_type
            entityId = response.entity_id
            updatedFields = response.updated_fields
            dataRevalidation = response.dataRevalidation
          }
          break
        case 'teaching-targets':
          {
            const response = await updateParsedTeachingTarget(adminRequestParams, selectedRow.id, request)
            updatedRow = response.item
            auditLogId = response.audit_log_id
            entityType = response.entity_type
            entityId = response.entity_id
            updatedFields = response.updated_fields
            dataRevalidation = response.dataRevalidation
          }
          break
        case 'form-f1-records':
          {
            const response = await updateParsedFormF1Record(adminRequestParams, selectedRow.id, request)
            updatedRow = response.item
            auditLogId = response.audit_log_id
            entityType = response.entity_type
            entityId = response.entity_id
            updatedFields = response.updated_fields
            dataRevalidation = response.dataRevalidation
          }
          break
        case 'academic-month-boundaries':
          {
            const response = await updateParsedAcademicMonthBoundary(adminRequestParams, selectedRow.id, request)
            updatedRow = response.item
            auditLogId = response.audit_log_id
            entityType = response.entity_type
            entityId = response.entity_id
            updatedFields = response.updated_fields
            dataRevalidation = response.dataRevalidation
          }
          break
      }
      if (!isCurrentRequest()) {
        return
      }
      const optimisticEntry = optimisticCorrectionHistoryEntry({
        auditLogId,
        action: optimisticActionByTab[activeTabId],
        entityType,
        entityId,
        correctionReason: correctionReason.trim(),
        before: selectedRow,
        after: updatedRow,
        metadata: {
          updated_fields: updatedFields,
          data_revalidation: dataRevalidation ?? null,
        },
      })
      setLastOptimisticHistory({ rowId: updatedRow.id, entry: optimisticEntry })
      setCorrectionMode('none')
      setCorrectionReason('')
      setCorrectionSuccess('Correction applied and audit history updated.')
      setCorrectionRevalidation(dataRevalidation ?? null)
      setRows((currentRows) => currentRows.map((row) => (row.id === updatedRow.id ? updatedRow : row)))
      const history = await loadCorrectionHistoryForRow(updatedRow, selectedSourceFragment)
      if (!isCurrentRequest()) {
        return
      }
      setCorrectionHistory(mergeCorrectionHistoryRows([history, [optimisticEntry]]))
      await refreshActiveRowsAfterMutation(updatedRow)
    } catch (submitError) {
      if (!isCurrentRequest()) {
        return
      }
      setCorrectionError(correctionErrorMessage(submitError))
    } finally {
      if (isCurrentRequest()) {
        setIsCorrectionSubmitting(false)
      }
    }
  }

  const addFragmentPostingGroup = () => {
    setFragmentDraftGroups((current) => [...current, newDraftGroup()])
    setCorrectionError(null)
    setCorrectionSuccess(null)
  }

  const updateFragmentPostingGroup = (groupId: string, postingCode: string) => {
    setFragmentDraftGroups((current) => current.map((group) => (
      group.id === groupId ? { ...group, posting_code: postingCode } : group
    )))
    setCorrectionError(null)
    setCorrectionSuccess(null)
  }

  const removeFragmentPostingGroup = (groupId: string) => {
    setFragmentDraftGroups((current) => current.filter((group) => group.id !== groupId))
    setCorrectionError(null)
    setCorrectionSuccess(null)
  }

  const addFragmentRange = (groupId: string) => {
    setFragmentDraftGroups((current) => current.map((group) => {
      if (group.id !== groupId) {
        return group
      }
      const lastRange = group.ranges[group.ranges.length - 1]
      return {
        ...group,
        ranges: [
          ...group.ranges,
          newDraftRange(lastRange?.fragment_start_date, lastRange?.fragment_end_date, lastRange?.day_part),
        ],
      }
    }))
    setCorrectionError(null)
    setCorrectionSuccess(null)
  }

  const updateFragmentRange = (
    groupId: string,
    rangeId: string,
    field: keyof Omit<FragmentDraftRange, 'id'>,
    value: string,
  ) => {
    setFragmentDraftGroups((current) => current.map((group) => {
      if (group.id !== groupId) {
        return group
      }
      return {
        ...group,
        ranges: group.ranges.map((range) => (
          range.id === rangeId
            ? {
                ...range,
                [field]: field === 'day_part' ? toFragmentDayPart(value) : value,
              }
            : range
        )),
      }
    }))
    setCorrectionError(null)
    setCorrectionSuccess(null)
  }

  const removeFragmentRange = (groupId: string, rangeId: string) => {
    setFragmentDraftGroups((current) => current.map((group) => (
      group.id === groupId
        ? { ...group, ranges: group.ranges.filter((range) => range.id !== rangeId) }
        : group
    )))
    setCorrectionError(null)
    setCorrectionSuccess(null)
  }

  const duplicateFragmentRange = (groupId: string, range: FragmentDraftRange) => {
    setFragmentDraftGroups((current) => current.map((group) => (
      group.id === groupId
        ? {
            ...group,
            ranges: [
              ...group.ranges,
              newDraftRange(range.fragment_start_date, range.fragment_end_date, range.day_part),
            ],
          }
        : group
    )))
    setCorrectionError(null)
    setCorrectionSuccess(null)
  }

  const buildSourceCellReplaceRequest = (): ResidentPostingSourceCellReplaceRequest | null => {
    if (!selectedRow || activeTabId !== 'resident-postings') {
      return null
    }
    const postingRow = selectedRow as ParsedResidentPostingRow
    const affectedRows = affectedSourceCellRows.length > 0 ? affectedSourceCellRows : [postingRow]
    const missingTokenRow = affectedRows.find((row) => !row.updated_at)
    if (missingTokenRow) {
      setCorrectionError(
        `Refresh before correcting ${formatValue(missingTokenRow.resident_name ?? missingTokenRow.mcr)}; an optimistic update token is missing.`,
      )
      return null
    }

    return {
      affected_resident_posting_ids: affectedRows.map((row) => row.id),
      replacement_rows: fragmentDraftGroups.flatMap((group): ResidentPostingReplacementRow[] => (
        group.ranges.map((range) => ({
          resident_id: postingRow.resident_id,
          posting_code: group.posting_code.trim() || null,
          reporting_period_id: postingRow.reporting_period_id,
          start_date: range.fragment_start_date,
          end_date: range.fragment_end_date,
          day_part: range.day_part === 'AM' || range.day_part === 'PM' ? range.day_part : null,
          month_label: postingRow.month_label,
          r_year: postingRow.r_year,
          status: postingRow.status,
          loa_type: postingRow.loa_type,
          loa_start_date: postingRow.loa_start_date,
          loa_end_date: postingRow.loa_end_date,
          refresher_training_type: postingRow.refresher_training_type,
          refresher_training_start: postingRow.refresher_training_start,
          refresher_training_end: postingRow.refresher_training_end,
          active_months_weight: postingRow.active_months_weight ?? 1,
          working_days_in_month: postingRow.working_days_in_month,
        }))
      )),
      source: selectedSourceFragment
        ? {
            upload_log_id: selectedRdbUploadId ?? null,
            sheet_name: selectedSourceFragment.sheet_name,
            row_number: selectedSourceFragment.row_number,
            cell_ref: selectedSourceFragment.cell_ref,
            source_column_header: selectedSourceFragment.source_column_header,
            source_cell_text: selectedSourceFragment.source_cell_text,
          }
        : {
            upload_log_id: null,
            sheet_name: null,
            row_number: null,
            cell_ref: null,
            source_column_header: null,
            source_cell_text: null,
          },
      correction_reason: correctionReason.trim(),
      last_seen_rows: affectedRows.map((row) => ({ id: row.id, updated_at: row.updated_at as string })),
    }
  }

  const submitSourceCellCorrection = async () => {
    if (!selectedRow || activeTabId !== 'resident-postings') {
      return
    }
    if (fragmentDraftErrors.length > 0) {
      setCorrectionError(fragmentDraftErrors.join(' '))
      return
    }
    if (!correctionReason.trim()) {
      setCorrectionError('Correction reason is required.')
      return
    }
    const request = buildSourceCellReplaceRequest()
    if (!request) {
      return
    }
    const isCurrentRequest = beginCorrectionRequest()

    setIsCorrectionSubmitting(true)
    setCorrectionError(null)
    setCorrectionHistoryError(null)
    setCorrectionRevalidation(null)
    try {
      const response = await replaceParsedResidentPostingSourceCell(adminRequestParams, request)
      if (!isCurrentRequest()) {
        return
      }
      const affectedIds = new Set(request.affected_resident_posting_ids)
      setRows((currentRows) => sortParsedRowsForDisplay(
        activeTabId,
        [
          ...currentRows.filter((row) => !affectedIds.has(row.id)),
          ...response.after_rows,
        ],
      ))
      setCorrectionMode('none')
      setCorrectionReason('')
      setCorrectionSuccess('Source-cell correction applied and audit history updated.')
      setCorrectionRevalidation(response.dataRevalidation ?? null)
      const optimisticEntry = optimisticCorrectionHistoryEntry({
        auditLogId: response.audit_log_id,
        action: 'admin.parsed_data.resident_posting.source_cell_replace',
        entityType: response.entity_type,
        entityId: response.entity_id,
        correctionReason: correctionReason.trim(),
        before: { before_rows: response.before_rows },
        after: { after_rows: response.after_rows },
        metadata: {
          updated_fields: response.updated_fields,
          source: request.source,
          source_metadata_verified: Boolean(request.source.upload_log_id),
          affected_resident_posting_ids: request.affected_resident_posting_ids,
          replacement_resident_posting_ids: response.after_rows.map((row) => row.id),
          data_revalidation: response.dataRevalidation ?? null,
        },
      })
      setLastOptimisticHistory({ rowId: selectedRow.id, entry: optimisticEntry })
      try {
        const history = await loadCorrectionHistoryForRow(selectedRow, selectedSourceFragment)
        if (!isCurrentRequest()) {
          return
        }
        setCorrectionHistory(mergeCorrectionHistoryRows([history, [optimisticEntry]]))
      } catch {
        if (!isCurrentRequest()) {
          return
        }
        setCorrectionHistory((current) => mergeCorrectionHistoryRows([[optimisticEntry], current]))
        setCorrectionHistoryError('Correction was saved, but the refreshed audit history could not be loaded.')
      }
      await refreshActiveRowsAfterMutation(null)
    } catch (submitError) {
      if (!isCurrentRequest()) {
        return
      }
      setCorrectionError(correctionErrorMessage(submitError))
    } finally {
      if (isCurrentRequest()) {
        setIsCorrectionSubmitting(false)
      }
    }
  }

  const renderFragmentCorrectionToggle = () => {
    if (activeTabId !== 'resident-postings') {
      return null
    }

    return (
      <label className="fragment-correction-toggle">
        <input
          type="checkbox"
          checked={isFragmentCorrection}
          onChange={(event) => {
            setIsFragmentCorrection(event.target.checked)
            setCorrectionError(null)
            setCorrectionSuccess(null)
          }}
        />
        <span>
          <strong>This correction changes source fragments or posting date ranges</strong>
          <small>
            Use this when changing a simple posting into multiple fragments, merging fragments, or correcting AM/PM/full-day date ranges.
          </small>
        </span>
      </label>
    )
  }

  const renderCorrectionField = (field: CorrectionFieldDefinition) => {
    const value = correctionDraft[field.key] ?? (field.type === 'boolean' ? false : '')
    return (
      <label key={field.key} className="correction-field">
        <span>
          {field.label}
          {field.highRisk ? <em>High-risk field</em> : null}
        </span>
        {field.type === 'boolean' ? (
          <select
            value={value === true ? 'true' : 'false'}
            onChange={(event) => setCorrectionDraftField(field, event.target.value === 'true')}
            disabled={isCorrectionSubmitting}
          >
            <option value="true">Yes</option>
            <option value="false">No</option>
          </select>
        ) : field.type === 'select' ? (
          <select
            value={String(value)}
            onChange={(event) => setCorrectionDraftField(field, event.target.value)}
            disabled={isCorrectionSubmitting}
          >
            {field.options?.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        ) : (
          <input
            type={field.type === 'date' ? 'date' : field.type === 'number' ? 'number' : 'text'}
            min={field.key === 'monthly_target' ? '0' : undefined}
            step={field.key === 'active_months_weight' ? '0.25' : field.key === 'monthly_target' ? '1' : undefined}
            value={String(value)}
            onChange={(event) => setCorrectionDraftField(field, event.target.value)}
            disabled={isCorrectionSubmitting}
          />
        )}
        {field.helper ? <small>{field.helper}</small> : null}
      </label>
    )
  }

  const renderTeachingTargetCorrectionFields = () => {
    const fieldByKey = new Map(correctionFields.map((field) => [field.key, field]))
    const monthlyTargetField = fieldByKey.get('monthly_target')
    const trackedField = fieldByKey.get('is_tracked')
    const reallocatableField = fieldByKey.get('is_reallocatable')
    const tagField = fieldByKey.get('tag')

    return (
      <div className="correction-form-grid teaching-target-correction-grid">
        {monthlyTargetField ? renderCorrectionField(monthlyTargetField) : null}
        {trackedField ? renderCorrectionField(trackedField) : null}
        {reallocatableField ? renderCorrectionField(reallocatableField) : null}
        {isTeachingTargetReallocatableDraft && tagField ? renderCorrectionField(tagField) : null}
      </div>
    )
  }

  const renderCorrectionFields = () => {
    if (activeTabId === 'teaching-targets') {
      return renderTeachingTargetCorrectionFields()
    }
    return (
      <div className="correction-form-grid">
        {correctionFields.map(renderCorrectionField)}
      </div>
    )
  }

  const renderFragmentCorrectionEditor = () => {
    if (!selectedRow || activeTabId !== 'resident-postings') {
      return null
    }

    const draftSourceText = correctedSourceCellDraftText(fragmentDraftGroups)
    const preparedReplacementCount = fragmentDraftGroups.reduce((count, group) => count + group.ranges.length, 0)

    return (
      <div className="fragment-source-editor">
        <div className="inline-callout callout-warning">
          <span>
            Source-cell corrections replace only the affected resident posting row group, preserve audit evidence, and return a Data Revalidation summary after save.
          </span>
        </div>
        {selectedSourceFragment ? (
          <div className="fragment-source-context">
            <h4>Source context</h4>
            <div className="parsed-data-detail-grid raw-source-group-grid">
              <div className="parsed-data-detail-item">
                <span>RDB Upload</span>
                <strong>{selectedRdbLogLabel ?? '-'}</strong>
              </div>
              <div className="parsed-data-detail-item">
                <span>Source</span>
                <strong>{formatSource(selectedSourceFragment)}</strong>
              </div>
              <div className="parsed-data-detail-item">
                <span>Source Column Header</span>
                <strong>{formatValue(selectedSourceFragment.source_column_header)}</strong>
              </div>
              <div className="parsed-data-detail-item">
                <span>Original Source Cell Text</span>
                <strong className="raw-fragment-source-text">{formatValue(selectedSourceFragment.source_cell_text)}</strong>
              </div>
            </div>
            {selectedRowRawSourceGroups.length > 0 ? (
              <div className="fragment-existing-groups">
                <h4>Existing raw fragment groups</h4>
                {selectedRowRawSourceGroups.map((sourceGroup) => (
                  <div key={sourceGroup.key} className="raw-posting-group-card">
                    {sourceGroup.postingGroups.map((postingGroup) => (
                      <div key={postingGroup.key} className="fragment-existing-group-row">
                        <strong className="mono-cell">
                          {formatValue(postingGroup.rawPostingCode ?? postingGroup.normalizedPostingCode)}
                        </strong>
                        <ul className="raw-date-range-list">
                          {postingGroup.fragments.map((fragment) => (
                            <li key={fragment.id}>{formatFragmentDateRangeLine(fragment)}</li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="inline-callout callout-info">
            <span>No uploaded source-cell trace is linked to this row. The draft is prefilled from the persisted final row.</span>
          </div>
        )}
        <div className="fragment-draft-editor">
          <div className="fragment-editor-header">
            <div>
              <h4>Corrected source fragments</h4>
              <p>Add posting groups and date ranges to model a simple, split, merged, or AM/PM source-cell correction.</p>
            </div>
            <button
              type="button"
              className="button button-secondary"
              onClick={addFragmentPostingGroup}
            >
              Add posting group
            </button>
          </div>
          {fragmentDraftGroups.length === 0 ? (
            <div className="inline-callout callout-warning">
              <span>Add at least one posting group to draft corrected source fragments.</span>
            </div>
          ) : (
            fragmentDraftGroups.map((group, groupIndex) => (
              <div key={group.id} className="fragment-draft-group">
                <div className="fragment-draft-group-header">
                  <label className="correction-field">
                    <span>Posting group {groupIndex + 1}</span>
                    <input
                      type="text"
                      value={group.posting_code}
                      onChange={(event) => updateFragmentPostingGroup(group.id, event.target.value)}
                      placeholder="e.g. TTSHGenMed"
                    />
                  </label>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => removeFragmentPostingGroup(group.id)}
                  >
                    Remove group
                  </button>
                </div>
                <div className="fragment-draft-ranges">
                  {group.ranges.map((range, rangeIndex) => (
                    <div key={range.id} className="fragment-draft-range">
                      <label className="correction-field">
                        <span>Range {rangeIndex + 1} start</span>
                        <input
                          type="date"
                          value={range.fragment_start_date}
                          onChange={(event) => updateFragmentRange(
                            group.id,
                            range.id,
                            'fragment_start_date',
                            event.target.value,
                          )}
                        />
                      </label>
                      <label className="correction-field">
                        <span>Range {rangeIndex + 1} end</span>
                        <input
                          type="date"
                          value={range.fragment_end_date}
                          onChange={(event) => updateFragmentRange(
                            group.id,
                            range.id,
                            'fragment_end_date',
                            event.target.value,
                          )}
                        />
                      </label>
                      <label className="correction-field">
                        <span>Day part</span>
                        <select
                          value={range.day_part}
                          onChange={(event) => updateFragmentRange(group.id, range.id, 'day_part', event.target.value)}
                        >
                          {dayPartOptions.map((option) => (
                            <option key={option.value || 'full-day'} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <div className="fragment-range-actions">
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => duplicateFragmentRange(group.id, range)}
                        >
                          Duplicate
                        </button>
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => removeFragmentRange(group.id, range.id)}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => addFragmentRange(group.id)}
                >
                  Add date range
                </button>
              </div>
            ))
          )}
        </div>
        <div className="fragment-draft-preview">
          <h4>Corrected source-cell preview</h4>
          <pre>{draftSourceText || 'Add posting groups and date ranges to preview corrected source-cell text.'}</pre>
          <p>This preview is converted into resident posting replacement rows and validated by the backend before any data is changed.</p>
          <small>
            Prepared {preparedReplacementCount} replacement row{preparedReplacementCount === 1 ? '' : 's'} for {affectedSourceCellRows.length || 1} affected row{(affectedSourceCellRows.length || 1) === 1 ? '' : 's'}.
          </small>
        </div>
        {fragmentDraftErrors.length > 0 ? (
          <div className="inline-callout callout-warning parsed-data-inline-error">
            <span>{fragmentDraftErrors.join(' ')}</span>
          </div>
        ) : null}
      </div>
    )
  }

  const renderCorrectionPanel = () => {
    if (!selectedRow || correctionMode === 'none') {
      return null
    }
    const fragmentCorrectionActive = activeTabId === 'resident-postings' && isFragmentCorrection
    return (
      <div className="detail-block parsed-data-correction-panel">
        <h3>Edit row</h3>
        <p>Update the row directly, or enable source-fragment correction when the posting cell needs to be split, merged, or re-parsed.</p>
        {renderFragmentCorrectionToggle()}
        {fragmentCorrectionActive ? (
          renderFragmentCorrectionEditor()
        ) : (
          renderCorrectionFields()
        )}
        <label className="correction-reason">
          Correction reason
          <textarea
            value={correctionReason}
            onChange={(event) => {
              setCorrectionReason(event.target.value)
              setCorrectionError(null)
            }}
            rows={3}
            maxLength={500}
            disabled={isCorrectionSubmitting}
            required
          />
        </label>
        <div className="correction-preview">
          {!fragmentCorrectionActive ? (
            <>
              <h4>Before / after preview</h4>
              {changedCorrectionFields.length === 0 ? (
                <p>No field changes selected.</p>
              ) : (
                <div className="correction-preview-table">
                  {changedCorrectionFields.map((field) => (
                    <div key={field.key} className="correction-preview-row">
                      <span>{field.label}</span>
                      <strong>{formatJsonPreview(rowValue(selectedRow, field.key))}</strong>
                      <strong>{formatJsonPreview(correctionValueForField(field, correctionDraft[field.key] ?? ''))}</strong>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : null}
        </div>
        {correctionError ? (
          <div className="inline-callout callout-warning parsed-data-inline-error">
            <span>{correctionError}</span>
          </div>
        ) : null}
        <div className="correction-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => {
              resetCorrectionDraft()
              setCorrectionMode('none')
            }}
            disabled={isCorrectionSubmitting}
          >
            Back to inspection
          </button>
          <button
            type="button"
            className="button button-primary"
            onClick={fragmentCorrectionActive ? submitSourceCellCorrection : submitRowCorrection}
            disabled={
              isCorrectionSubmitting ||
              !correctionReason.trim() ||
              (fragmentCorrectionActive
                ? fragmentDraftErrors.length > 0
                : changedCorrectionFields.length === 0)
            }
          >
            {isCorrectionSubmitting ? 'Saving...' : 'Save correction'}
          </button>
        </div>
      </div>
    )
  }

  const renderCorrectionHistory = () => (
    <div className="detail-block parsed-data-correction-history">
      <h3>Correction history</h3>
      {isCorrectionHistoryLoading ? (
        <p>Loading correction history...</p>
      ) : correctionHistoryError ? (
        <p>{correctionHistoryError}</p>
      ) : correctionHistory.length === 0 ? (
        <p>No corrections recorded for this row.</p>
      ) : (
        correctionHistory.map((entry) => (
          <div key={entry.id} className="correction-history-entry">
            <div className="correction-history-header">
              <strong>{formatCorrectionActionLabel(entry.action)}</strong>
              <span>{formatSingaporeDateTime(entry.created_at)}</span>
            </div>
            <p>{entry.correction_reason ?? 'No reason recorded.'}</p>
            <dl className="correction-summary-list">
              <dt>Entity</dt>
              <dd>{formatCorrectionFieldLabel(entry.entity_type)}</dd>
            </dl>
            {entry.action === 'admin.parsed_data.resident_posting.source_cell_replace'
              ? renderSourceCellReplacementSummary(entry)
              : renderCorrectionDiff(entry)}
            {renderSourceSummary(entry.metadata_json)}
          </div>
        ))
      )}
    </div>
  )

  const renderCompactLine = (items: Array<string | number | null | undefined>) => {
    const values = items
      .map((item) => formatValue(item))
      .filter((item) => item !== '-')

    if (values.length === 0) {
      return null
    }

    return <span className="parsed-data-mobile-compact-line safe-wrap">{values.join(' · ')}</span>
  }

  const selectRowForDetail = (row: ParsedDataRow) => {
    historyRequestRef.current += 1
    correctionRequestRef.current += 1
    setSelectedRow(row)
  }

  const closeRowDetail = () => {
    historyRequestRef.current += 1
    correctionRequestRef.current += 1
    setSelectedRow(null)
  }

  const renderMobileCardBody = (row: ParsedDataRow) => {
    if (activeTabId === 'residents') {
      const resident = row as ParsedResidentRow
      return (
        <>
          {renderCompactLine([resident.mcr, resident.programme_code, resident.r_year])}
          {renderCompactLine([resident.classification, resident.reg_type])}
        </>
      )
    }

    if (activeTabId === 'resident-postings') {
      const posting = row as ParsedResidentPostingRow
      const rawMatches = rawFragmentsByPostingId.get(posting.id) ?? []
      return (
        <>
          {renderCompactLine([posting.month_label, posting.posting_code, posting.r_year])}
          <span className="parsed-data-mobile-compact-line safe-wrap">
            {formatDate(posting.start_date)} - {formatDate(posting.end_date)}
          </span>
          {rawMatches.length > 0 ? (
            <span className="parsed-data-mobile-source safe-wrap">
              Source: {formatSource(rawMatches[0])}
              {rawMatches.length > 1 ? ` + ${rawMatches.length - 1} more` : ''}
            </span>
          ) : null}
        </>
      )
    }

    if (activeTabId === 'teaching-targets') {
      const target = row as ParsedTeachingTargetRow
      return (
        <>
          {renderCompactLine([target.programme_code, target.r_year, `target ${formatNumber(target.monthly_target)}/mo`])}
          {renderCompactLine([
            target.is_reallocatable ? 'Reallocatable' : 'Not reallocatable',
            target.tag ? `tag ${target.tag}` : null,
          ])}
        </>
      )
    }

    if (activeTabId === 'form-f1-records') {
      const record = row as ParsedFormF1RecordRow
      return (
        <>
          {renderCompactLine([record.month_label, record.status_raw, record.programme_code])}
          {renderCompactLine([record.resident_name])}
          {record.promotion_date ? (
            <span className="parsed-data-mobile-compact-line safe-wrap">
              Promotion: {formatDate(record.promotion_date)}
            </span>
          ) : null}
        </>
      )
    }

    const boundary = row as ParsedAcademicMonthBoundaryRow
    return (
      <>
        {renderCompactLine([boundary.academic_year_label])}
        <span className="parsed-data-mobile-compact-line safe-wrap">
          {formatDate(boundary.start_date)} - {formatDate(boundary.end_date)}
        </span>
      </>
    )
  }

  const renderMobileRowCard = (row: ParsedDataRow) => {
    let title: ReactNode
    let status: ReactNode

    if (activeTabId === 'residents') {
      const resident = row as ParsedResidentRow
      title = formatValue(resident.name)
      status = <StatusBadge label={formatValue(resident.status)} tone={statusTone(resident.status)} />
    } else if (activeTabId === 'resident-postings') {
      const posting = row as ParsedResidentPostingRow
      title = [posting.resident_name, posting.mcr].map(formatValue).filter((item) => item !== '-').join(' · ') || '-'
      status = <StatusBadge label={formatValue(posting.status)} tone={statusTone(posting.status)} />
    } else if (activeTabId === 'teaching-targets') {
      const target = row as ParsedTeachingTargetRow
      title = [target.posting_code, target.session_type_name].map(formatValue).filter((item) => item !== '-').join(' · ') || '-'
      status = boolBadge(target.is_tracked, 'Tracked', 'Untracked')
    } else if (activeTabId === 'form-f1-records') {
      const record = row as ParsedFormF1RecordRow
      title = formatValue(record.mcr)
      status = boolBadge(record.is_active, 'Active', 'Inactive')
    } else {
      const boundary = row as ParsedAcademicMonthBoundaryRow
      title = formatValue(boundary.month_label)
      status = <span className="parsed-data-mobile-type">{formatValue(boundary.ay_date_category)}</span>
    }

    return (
      <button
        key={`${activeTab.id}-${row.id}-mobile`}
        type="button"
        className="mobile-record-card admin-mobile-record-card parsed-data-mobile-card"
        onClick={() => selectRowForDetail(row)}
        aria-label={`Open ${activeTab.label} row detail`}
      >
        <span className="admin-mobile-card-header parsed-data-mobile-card-header">
          <span className="admin-mobile-card-title safe-wrap">
            {title}
          </span>
          <span className="parsed-data-mobile-status">{status}</span>
        </span>
        <span className="admin-mobile-card-meta parsed-data-mobile-card-meta">
          {renderMobileCardBody(row)}
        </span>
        <span className="parsed-data-mobile-action">View details</span>
      </button>
    )
  }

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
        title="Live Data"
        subtitle="Review uploaded records, inspect parser traceability, and apply audited corrections."
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

      <section className="card parsed-data-tab-card">
        <div className="parsed-data-tabs" role="tablist" aria-label="Live data tables">
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
        <div className="admin-filter-summary parsed-data-filter-summary">
          <span>Filters</span>
          <strong>{hasFilters ? 'Active filters applied' : `All ${activeTab.label.toLowerCase()}`}</strong>
        </div>
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
                  {formatSingaporeDateTime(log.uploaded_at)} | {log.reporting_period_label ?? 'Reporting period unavailable'} | {log.programme_code ?? 'Global'}
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
          <div className="warning-state-card parsed-data-state-card">Loading live data...</div>
        ) : error && rows.length === 0 ? (
          <div className="warning-state-card parsed-data-state-card">
            <strong>Live data could not be loaded.</strong>
            <p>{error}</p>
            <button type="button" className="button button-secondary" onClick={() => void fetchRows()}>
              Retry
            </button>
          </div>
        ) : rows.length === 0 ? (
          <div className="warning-state-card parsed-data-state-card">
            <strong>{hasFilters ? 'No live rows match these filters' : `No ${activeTab.label.toLowerCase()} rows found`}</strong>
            <p>
              {hasFilters
                ? 'Clear filters or adjust the search to inspect persisted upload data.'
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
                        onClick={() => selectRowForDetail(row)}
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
            <div className="responsive-card-list admin-mobile-record-list parsed-data-mobile-card-list" aria-label="Live data row cards">
              {rows.map(renderMobileRowCard)}
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
        title={selectedRow ? `${activeTab.label} row` : 'Live data row'}
        open={Boolean(selectedRow)}
        onClose={closeRowDetail}
      >
        {selectedRow ? (
          <div className="warning-detail parsed-data-detail">
            {correctionMode !== 'none' ? (
              renderCorrectionPanel()
            ) : (
              <>
                <div className="detail-block">
                  <h3>Row inspection</h3>
                  <p>This drawer shows the persisted upload row and read-only source evidence.</p>
                  <div className="correction-actions">
                    {correctionFields.length > 0 ? (
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => {
                          resetCorrectionDraft()
                          setCorrectionMode('row')
                          setCorrectionError(null)
                          setCorrectionSuccess(null)
                        }}
                        disabled={isCorrectionSubmitting}
                      >
                        Edit row
                      </button>
                    ) : null}
                  </div>
                  {correctionSuccess ? (
                    <div className="inline-callout callout-success">
                      <span>{correctionSuccess}</span>
                      <DataRevalidationCallout impact={correctionRevalidation} compact />
                    </div>
                  ) : null}
                </div>
                <div className="parsed-data-detail-grid">
                  {parsedDataDetailEntries(selectedRow).map(([key, value]) => (
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
                {renderCorrectionHistory()}
              </>
            )}
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
