import { Fragment, type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import {
  createLoaType,
  deleteLoaType,
  listLoaTypes,
  updateLoaType,
  type LoaType,
} from '../../api/loaTypes'
import {
  createGlobalSessionType,
  deleteGlobalSessionType,
  listGlobalSessionTypes,
  updateGlobalSessionType,
  type GlobalSessionType,
} from '../../api/globalSessionTypes'
import {
  createPostingGroup,
  deletePostingGroup,
  listPostingGroups,
  updatePostingGroup,
  type PostingGroup,
} from '../../api/postingGroups'
import {
  createPublicHoliday,
  deletePublicHoliday,
  listPublicHolidays,
  updatePublicHoliday,
  type PublicHoliday,
} from '../../api/publicHolidays'
import { listProgrammes, updateProgramme, type Programme } from '../../api/programmes'
import { listPostingCodes, type PostingCodeOption } from '../../api/postingCodes'
import {
  createReportingPeriod,
  deleteReportingPeriod,
  updateReportingPeriod,
} from '../../api/reportingPeriods'
import { listSessionTypes, type SessionTypeOption } from '../../api/sessionTypes'
import {
  createWeekendException,
  deleteWeekendException,
  listWeekendExceptions,
  updateWeekendException,
  type WeekendException,
} from '../../api/weekendExceptions'
import { ApiRequestError } from '../../api/http'
import { DetailDrawer } from '../../components/DetailDrawer'
import { StatusBadge } from '../../components/StatusBadge'
import { IconPlus, IconRefresh, NamedIcon } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { useAppState } from '../../context/useAppState'
import type { ReportingPeriodOption } from '../../types/upload'
import { MultiPostingRulesSection } from './AdminMultiPostingPage'

type ConfigSectionKey =
  | 'reporting-periods'
  | 'public-holidays'
  | 'programmes'
  | 'loa-types'
  | 'multi-posting-rules'
  | 'posting-groups'
  | 'weekend-exceptions'
  | 'global-session-types'

interface ConfigSection {
  key: ConfigSectionKey
  label: string
  icon: string
  title: string
  description: string
  stateLabel: string
  nextStep: string
  rows: Array<{
    field: string
    current: string
    next: string
    mono?: boolean
  }>
  actionLabel?: string
  actionPath?: string
}

interface ReportingPeriodFormState {
  label: string
  startDate: string
  endDate: string
  status: 'open' | 'closed'
}

interface PublicHolidayFormState {
  holidayDate: string
  name: string
}

interface ProgrammeFormState {
  rYearRequired: boolean
  isSubspecialty: boolean
  rdbAlias: string
}

interface LoaTypeFormState {
  code: string
  description: string
}

interface PostingGroupFormState {
  programmeCode: string
  postingCode: string
  groupCode: string
}

interface WeekendExceptionFormState {
  programmeCode: string
  postingCode: string
  dayType: 'sat' | 'sun' | 'both'
  startTimeMin: string
  endTimeMax: string
  sessionTypeId: string
  sessionNamePattern: string
  mutatesToSessionTypeId: string
  adjustedDurationHours: string
}

interface GlobalSessionTypeFormState {
  name: string
  durationHours: string
  isActive: boolean
}

type Feedback = {
  tone: 'success' | 'error'
  message: string
  description?: string
  detailsLabel?: string
  dependencyDetails?: Array<{
    label: string
    count: number
  }>
  rawMessage?: string
} | null

const emptyReportingPeriodForm: ReportingPeriodFormState = {
  label: '',
  startDate: '',
  endDate: '',
  status: 'open',
}

const emptyPublicHolidayForm: PublicHolidayFormState = {
  holidayDate: '',
  name: '',
}

const emptyProgrammeForm: ProgrammeFormState = {
  rYearRequired: false,
  isSubspecialty: false,
  rdbAlias: '',
}

const emptyLoaTypeForm: LoaTypeFormState = {
  code: '',
  description: '',
}

const emptyPostingGroupForm: PostingGroupFormState = {
  programmeCode: '',
  postingCode: '',
  groupCode: '',
}

const emptyWeekendExceptionForm: WeekendExceptionFormState = {
  programmeCode: '',
  postingCode: '',
  dayType: 'sat',
  startTimeMin: '',
  endTimeMax: '',
  sessionTypeId: '',
  sessionNamePattern: '',
  mutatesToSessionTypeId: '',
  adjustedDurationHours: '',
}

const emptyGlobalSessionTypeForm: GlobalSessionTypeFormState = {
  name: '',
  durationHours: '1.0',
  isActive: true,
}

const programmePcConfigSections: ConfigSectionKey[] = ['multi-posting-rules', 'posting-groups']

const ayCategoryLabels: Record<string, string> = {
  im_subspec: 'IM Subspec',
  non_im_subspec: 'Non IM Subspec',
}

const formatAyCategory = (value: string) => ayCategoryLabels[value] ?? value

const configSections: ConfigSection[] = [
  {
    key: 'reporting-periods',
    label: 'Reporting Periods',
    icon: 'calendar',
    title: 'Reporting Periods',
    description: 'Reporting periods are required before RDB, TTF, and FormF1 uploads can be safely scoped.',
    stateLabel: 'Live CRUD',
    nextStep:
      'Create and maintain reporting periods here. Delete is blocked when period-dependent records exist.',
    rows: [],
  },
  {
    key: 'public-holidays',
    label: 'Public Holidays',
    icon: 'calendar',
    title: 'Public Holidays',
    description: 'Holiday and AY boundary data is currently upload-driven from the Academic Calendar / Public Holiday workbook.',
    stateLabel: 'Upload-driven data; manual CRUD pending',
    nextStep:
      'Manual CRUD can be added later. MOM/public holiday sync is intentionally not implemented in this task.',
    rows: [
      {
        field: 'Source',
        current: 'Academic Calendar / Public Holiday workbook upload.',
        next: 'Keep manual edits behind a future CRUD task.',
      },
      {
        field: 'Runtime use',
        current: 'Public holidays block secretary and resident ad-hoc event creation server-side.',
        next: 'Expose read/edit controls only after endpoint scope is confirmed.',
      },
      {
        field: 'External sync',
        current: 'No MOM sync in this shell.',
        next: 'Do not add sync behavior here.',
      },
    ],
  },
  {
    key: 'programmes',
    label: 'Programmes',
    icon: 'database',
    title: 'Programmes',
    description: 'Programme definitions are seeded in the database and editable for parser configuration flags.',
    stateLabel: 'Live list/edit',
    nextStep: 'Future uploads use the saved flags. Existing parsed data is not recalculated by this page.',
    rows: [
      {
        field: 'Seed source',
        current: 'Programme catalogue is database-seeded.',
        next: 'Add safe edit controls for aliases, r-year behavior, and AY categories later.',
      },
      {
        field: 'Scope',
        current: 'Admin accounts are programme-scoped.',
        next: 'Server-side scope checks must remain authoritative.',
      },
      {
        field: 'Current mode',
        current: 'No programme rows are displayed here yet.',
        next: 'Read-only preview pending.',
      },
    ],
  },
  {
    key: 'loa-types',
    label: 'LOA Types',
    icon: 'file',
    title: 'LOA Types',
    description: 'LOA types are seeded validation-catalogue rows for RDB parser warnings.',
    stateLabel: 'Live CRUD',
    nextStep: 'Manual changes affect future validation only. Existing uploaded records are not changed.',
    rows: [
      {
        field: 'Seeded list',
        current: 'Confirmed LOA types are seeded for parser/audit display.',
        next: 'Manual CRUD pending.',
      },
      {
        field: 'Parser behavior',
        current: 'Unknown LOA values should warn rather than reject uploads.',
        next: 'Keep parser behavior unchanged in this UI task.',
      },
      {
        field: 'Compliance',
        current: 'Compliance denominator remains governed by FormF1 active/inactive status.',
        next: 'Do not add compliance logic here.',
      },
    ],
  },
  {
    key: 'multi-posting-rules',
    label: 'Multi-Posting Rules',
    icon: 'settings',
    title: 'Multi-Posting Rules',
    description: 'Multi-Posting Rules affect RDB parsing. Posting Groups affect compliance aggregation.',
    stateLabel: 'Live CRUD',
    nextStep:
      'Maintain parse-time RDB collapse and split rules without changing Posting Groups compliance aggregation.',
    rows: [
      {
        field: 'Main Posting',
        current: 'Collapse matching RDB cell postings to a main posting.',
        next: 'Used for FM one-posting rows and explicit two-posting cases.',
      },
      {
        field: 'To Combine Posting',
        current: 'Collapse two RDB posting cells to one combined posting.',
        next: 'Existing parsed rows are unchanged until the next RDB upload.',
      },
      {
        field: 'Half Month Posting',
        current: 'Split active month weight 50/50 between two postings.',
        next: 'Posting Groups remain a separate config section.',
      },
    ],
  },
  {
    key: 'posting-groups',
    label: 'Posting Groups',
    icon: 'grid',
    title: 'Posting Groups',
    description: 'Posting groups pool related posting codes for compliance aggregation and are separate from multi-posting rules.',
    stateLabel: 'Live CRUD',
    nextStep:
      'Groups are seeded from TTF Column E. Manual CRUD keeps grouped posting aggregation distinct from multi-posting parse rules.',
    rows: [
      {
        field: 'Use case',
        current: 'Pool related posting codes so compliance can aggregate across a group.',
        next: 'Maintain operational corrections without changing RDB parsing behavior.',
      },
      {
        field: 'Seed source',
        current: 'Seeded from non-empty TTF Column E values.',
        next: 'Keep upload seeding behavior unchanged.',
      },
      {
        field: 'Not the same as',
        current: 'Multi-posting rules.',
        next: 'Use multi-posting rules for RDB cell collapse/split behavior, not group aggregation.',
      },
    ],
  },
  {
    key: 'weekend-exceptions',
    label: 'Weekend Exceptions',
    icon: 'calendar',
    title: 'Weekend Exceptions',
    description: 'Weekend exceptions are seeded and later CRUD-manageable.',
    stateLabel: 'CRUD wiring pending',
    nextStep: 'Future edits should preserve read-time exception behavior and confirmed programme-specific rules.',
    rows: [
      {
        field: 'Current source',
        current: 'Seeded weekend exception configuration.',
        next: 'Manual CRUD pending.',
      },
      {
        field: 'Compliance use',
        current: 'Exceptions decide whether weekend sessions count, including read-time ORTHO mutation.',
        next: 'Do not mutate raw attendance records.',
      },
      {
        field: 'Current mode',
        current: 'No editable rows exposed here.',
        next: 'CRUD wiring pending.',
      },
    ],
  },
  {
    key: 'global-session-types',
    label: 'Global Session Types',
    icon: 'settings',
    title: 'Global Session Types',
    description: 'Global session types are compliance-exempt teaching names and later CRUD-manageable.',
    stateLabel: 'CRUD wiring pending',
    nextStep:
      'Future CRUD should keep active global names available to secretary/resident dropdowns while excluding them from compliance.',
    rows: [
      {
        field: 'Compliance effect',
        current: 'Matching global session types are excluded from both numerator and denominator.',
        next: 'Keep this exclusion server-side.',
      },
      {
        field: 'Dropdown use',
        current: 'Secretary and resident ad-hoc flows can include global teaching names when wired.',
        next: 'Manual CRUD pending.',
      },
      {
        field: 'Current mode',
        current: 'Read-only placeholder.',
        next: 'CRUD wiring pending.',
      },
    ],
  },
]

const formatDate = (value?: string) => {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat('en-SG', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(parsed)
}

const deriveDatePreview = (value: string) => {
  if (!value) {
    return { dayOfWeek: '-', year: '-' }
  }
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime())) {
    return { dayOfWeek: '-', year: '-' }
  }
  return {
    dayOfWeek: new Intl.DateTimeFormat('en-SG', { weekday: 'long' }).format(parsed),
    year: String(parsed.getFullYear()),
  }
}

const dependencyLabels: Record<string, string> = {
  upload_logs: 'upload logs',
  resident_postings: 'resident postings',
  teaching_targets: 'teaching targets',
  teaching_name_catalogue: 'teaching name catalogue',
  form_f1_records: 'FormF1 records',
  academic_month_boundaries: 'academic month boundaries',
  period_snapshots: 'period snapshots',
  clawback_records: 'clawback records',
  surplus_ledger: 'surplus ledger rows',
}

const dependencyLabelPatterns = Object.values(dependencyLabels).map((label) => ({
  label,
  pattern: new RegExp(`${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}:\\s*(\\d+)`, 'i'),
}))

const toDependencyDetails = (dependencies?: Record<string, number>) =>
  dependencies
    ? Object.entries(dependencies).map(([key, count]) => ({
        label: dependencyLabels[key] ?? key,
        count,
      }))
    : []

const parseDependencyDetailsFromMessage = (message: string) =>
  dependencyLabelPatterns
    .map(({ label, pattern }) => {
      const match = message.match(pattern)
      return match ? { label, count: Number(match[1]) } : null
    })
    .filter((detail): detail is { label: string; count: number } => detail !== null)

const describeDeleteError = (error: unknown): NonNullable<Feedback> => {
  if (!(error instanceof ApiRequestError)) {
    return {
      tone: 'error',
      message: 'Unable to delete reporting period.',
    }
  }
  const metadata = (error.details as { metadata?: { dependencies?: Record<string, number> } } | undefined)
    ?.metadata
  const dependencyDetails = toDependencyDetails(metadata?.dependencies)
  const parsedDetails =
    dependencyDetails.length > 0 ? dependencyDetails : parseDependencyDetailsFromMessage(error.message)
  const isBlockedDelete =
    error.status === 409 ||
    error.message.toLowerCase().includes('reporting period is in use') ||
    parsedDetails.length > 0

  if (isBlockedDelete) {
    return {
      tone: 'error',
      message: 'This reporting period is already in use and cannot be deleted.',
      description:
        'It has linked uploads and parsed records. Keep it for audit history, or create a new reporting period instead.',
      detailsLabel: 'View linked record details',
      dependencyDetails: parsedDetails,
      rawMessage: parsedDetails.length > 0 ? undefined : error.message,
    }
  }
  return {
    tone: 'error',
    message: error.message,
  }
}

const periodStatusTone = (status: string): 'success' | 'neutral' =>
  status.toLowerCase() === 'open' ? 'success' : 'neutral'

const toFormState = (period: ReportingPeriodOption): ReportingPeriodFormState => ({
  label: period.label,
  startDate: period.startDate,
  endDate: period.endDate,
  status: period.status.toLowerCase() === 'closed' ? 'closed' : 'open',
})

const toPublicHolidayFormState = (holiday: PublicHoliday): PublicHolidayFormState => ({
  holidayDate: holiday.holidayDate,
  name: holiday.name,
})

const toProgrammeFormState = (programme: Programme): ProgrammeFormState => ({
  rYearRequired: programme.rYearRequired,
  isSubspecialty: programme.isSubspecialty,
  rdbAlias: programme.rdbAlias ?? '',
})

const toLoaTypeFormState = (loaType: LoaType): LoaTypeFormState => ({
  code: loaType.code,
  description: loaType.description ?? '',
})

const toPostingGroupFormState = (postingGroup: PostingGroup): PostingGroupFormState => ({
  programmeCode: postingGroup.programmeCode,
  postingCode: postingGroup.postingCode,
  groupCode: postingGroup.groupCode,
})

const toWeekendExceptionFormState = (
  weekendException: WeekendException,
): WeekendExceptionFormState => ({
  programmeCode: weekendException.programmeCode ?? '',
  postingCode: weekendException.postingCode ?? '',
  dayType: weekendException.dayType,
  startTimeMin: normaliseTimeForInput(weekendException.startTimeMin),
  endTimeMax: normaliseTimeForInput(weekendException.endTimeMax),
  sessionTypeId: weekendException.sessionTypeId ?? '',
  sessionNamePattern: weekendException.sessionNamePattern ?? '',
  mutatesToSessionTypeId: weekendException.mutatesToSessionTypeId ?? '',
  adjustedDurationHours: weekendException.adjustedDurationHours ?? '',
})

const toGlobalSessionTypeFormState = (
  globalSessionType: GlobalSessionType,
): GlobalSessionTypeFormState => ({
  name: globalSessionType.name,
  durationHours: globalSessionType.durationHours,
  isActive: globalSessionType.isActive,
})

const booleanTone = (value: boolean): 'success' | 'neutral' => (value ? 'success' : 'neutral')

const normaliseOptionalText = (value: string): string | null => value.trim() || null

const normaliseTimeForInput = (value?: string): string => (value ? value.slice(0, 5) : '')

const dayTypeLabels: Record<WeekendException['dayType'], string> = {
  sat: 'Saturday',
  sun: 'Sunday',
  both: 'Saturday and Sunday',
}

const formatWeekendScope = (weekendException: WeekendException) => {
  const programme = weekendException.programmeCode ?? 'All programmes'
  const posting = weekendException.postingCode ?? 'All postings'
  return `${programme} / ${posting}`
}

const formatTimeWindow = (weekendException: WeekendException) => {
  if (!weekendException.startTimeMin && !weekendException.endTimeMax) {
    return 'Any time'
  }
  return `${normaliseTimeForInput(weekendException.startTimeMin) || 'Any'} - ${
    normaliseTimeForInput(weekendException.endTimeMax) || 'Any'
  }`
}

const formatHourValue = (value?: string) => {
  if (!value) {
    return ''
  }
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) {
    return `${value}h`
  }
  return `${numeric.toFixed(2)}h`
}

const formatWeekendMatch = (weekendException: WeekendException) => {
  if (weekendException.sessionNamePattern) {
    return `Teaching name contains: ${weekendException.sessionNamePattern}`
  }
  if (weekendException.sessionTypeId) {
    return weekendException.sessionTypeName
      ? `Session type: ${weekendException.sessionTypeName}`
      : 'Session type: Configured session type'
  }
  return 'Any session'
}

const formatWeekendCountsAs = (weekendException: WeekendException) => {
  if (!weekendException.mutatesToSessionTypeId && !weekendException.adjustedDurationHours) {
    return 'Submitted session'
  }
  const target = weekendException.mutatesToSessionTypeId
    ? (weekendException.mutatesToSessionTypeName ?? 'Configured mapped session')
    : 'Configured mapped session'
  const duration = formatHourValue(weekendException.adjustedDurationHours)
  return duration ? `${target} / ${duration}` : target
}

const sessionTypeOptionLabel = (option: SessionTypeOption) => option.name

const programmeOptionLabel = (programme: Programme) =>
  programme.name ? `${programme.code} - ${programme.name}` : programme.code

const postingCodeOptionLabel = (postingCode: PostingCodeOption) =>
  postingCode.displayName ? `${postingCode.code} - ${postingCode.displayName}` : postingCode.code

const formatProgrammeCode = (programmeCode: string, programmeMap: Map<string, Programme>) => {
  const programme = programmeMap.get(programmeCode)
  return programme ? programmeOptionLabel(programme) : programmeCode
}

const formatPostingCode = (postingCode: string, postingCodeMap: Map<string, PostingCodeOption>) => {
  const posting = postingCodeMap.get(postingCode)
  return posting ? postingCodeOptionLabel(posting) : postingCode
}

const describeWeekendExceptionError = (
  error: unknown,
  fallbackMessage: string,
): NonNullable<Feedback> => {
  if (!(error instanceof ApiRequestError)) {
    return { tone: 'error', message: fallbackMessage }
  }
  const lowerMessage = error.message.toLowerCase()
  if (lowerMessage.includes('session_type_id') || lowerMessage.includes('mutates_to_session_type_id')) {
    return {
      tone: 'error',
      message: fallbackMessage,
      description:
        'One selected session type could not be found. Choose an existing session type or clear the selection.',
    }
  }
  return {
    tone: 'error',
    message: error.message || fallbackMessage,
  }
}

const describePublicHolidayError = (
  error: unknown,
  fallbackMessage: string,
): NonNullable<Feedback> => {
  if (!(error instanceof ApiRequestError)) {
    return {
      tone: 'error',
      message: fallbackMessage,
    }
  }
  if (error.status === 409) {
    return {
      tone: 'error',
      message: fallbackMessage,
      description: 'That holiday date may already exist. Use edit on the existing row instead.',
    }
  }
  return {
    tone: 'error',
    message: error.message || fallbackMessage,
  }
}

const describeGenericConfigError = (
  error: unknown,
  fallbackMessage: string,
  conflictDescription?: string,
): NonNullable<Feedback> => {
  if (!(error instanceof ApiRequestError)) {
    return {
      tone: 'error',
      message: fallbackMessage,
    }
  }
  if (error.status === 409 && conflictDescription) {
    return {
      tone: 'error',
      message: fallbackMessage,
      description: conflictDescription,
    }
  }
  return {
    tone: 'error',
    message: error.message || fallbackMessage,
  }
}

const ReportingPeriodsSection = () => {
  const {
    reportingPeriods,
    reportingPeriodsLoading,
    reportingPeriodsError,
    reloadReportingPeriods,
    demoAdminId,
    demoAdminProgrammes,
  } = useAppState()
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit'>('create')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedPeriod, setSelectedPeriod] = useState<ReportingPeriodOption | null>(null)
  const [formState, setFormState] = useState<ReportingPeriodFormState>(emptyReportingPeriodForm)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmingDeletePeriod, setConfirmingDeletePeriod] =
    useState<ReportingPeriodOption | null>(null)
  const [feedbackDetailsOpen, setFeedbackDetailsOpen] = useState(false)

  const sortedPeriods = useMemo(
    () =>
      [...reportingPeriods].sort((left, right) => {
        const leftStart = new Date(left.startDate).getTime()
        const rightStart = new Date(right.startDate).getTime()
        return rightStart - leftStart
      }),
    [reportingPeriods],
  )

  const openCreateDrawer = () => {
    setDrawerMode('create')
    setSelectedPeriod(null)
    setFormState(emptyReportingPeriodForm)
    setSubmitState('idle')
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    setConfirmingDeletePeriod(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (period: ReportingPeriodOption) => {
    setDrawerMode('edit')
    setSelectedPeriod(period)
    setFormState(toFormState(period))
    setSubmitState('idle')
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    setConfirmingDeletePeriod(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (submitState === 'submitting') {
      return
    }
    setDrawerOpen(false)
    setSelectedPeriod(null)
    setFormState(emptyReportingPeriodForm)
    setSubmitState('idle')
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitState('submitting')
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    try {
      if (drawerMode === 'edit' && selectedPeriod) {
        await updateReportingPeriod({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          id: selectedPeriod.id,
          payload: formState,
        })
        setFeedback({ tone: 'success', message: 'Reporting period updated.' })
      } else {
        await createReportingPeriod({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          payload: {
            label: formState.label,
            startDate: formState.startDate,
            endDate: formState.endDate,
          },
        })
        setFeedback({ tone: 'success', message: 'Reporting period created.' })
      }
      await reloadReportingPeriods()
      setDrawerOpen(false)
      setSelectedPeriod(null)
      setFormState(emptyReportingPeriodForm)
      setSubmitState('idle')
    } catch (error) {
      setSubmitState('error')
      setFeedback({
        tone: 'error',
        message: error instanceof ApiRequestError ? error.message : 'Unable to save reporting period.',
      })
    }
  }

  const requestDelete = (period: ReportingPeriodOption) => {
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    setConfirmingDeletePeriod(period)
  }

  const dismissFeedback = () => {
    setFeedback(null)
    setFeedbackDetailsOpen(false)
  }

  const handleDelete = async (period: ReportingPeriodOption) => {
    setDeletingId(period.id)
    setFeedback(null)
    setFeedbackDetailsOpen(false)
    try {
      await deleteReportingPeriod({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        id: period.id,
      })
      setFeedback({ tone: 'success', message: 'Reporting period deleted.' })
      await reloadReportingPeriods()
      setConfirmingDeletePeriod(null)
    } catch (error) {
      setConfirmingDeletePeriod(null)
      setFeedback(describeDeleteError(error))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <header className="admin-config-content-header posting-groups-header">
        <div>
          <div className="admin-config-title-row">
            <h2>Reporting Periods</h2>
          </div>
          <p>Six-month windows used by uploads, attendance bucketing, snapshots, and surplus resets.</p>
        </div>
        <div className="admin-config-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reloadReportingPeriods()}
            disabled={reportingPeriodsLoading}
          >
            <IconRefresh size={14} />
            Retry
          </button>
          <button type="button" className="button button-primary" onClick={openCreateDrawer}>
            <IconPlus size={14} />
            New Period
          </button>
        </div>
      </header>

      {feedback ? (
        <div
          className={`inline-callout ${feedback.tone === 'error' ? 'callout-error' : 'callout-success'} admin-config-feedback`}
          role="status"
        >
          <div className="admin-config-feedback-content">
            <strong>{feedback.message}</strong>
            {feedback.description ? <p>{feedback.description}</p> : null}
            {feedback.detailsLabel && (feedback.dependencyDetails?.length || feedback.rawMessage) ? (
              <>
                <button
                  type="button"
                  className="admin-config-details-toggle"
                  onClick={() => setFeedbackDetailsOpen((open) => !open)}
                  aria-expanded={feedbackDetailsOpen}
                >
                  {feedbackDetailsOpen ? 'Hide linked record details' : feedback.detailsLabel}
                </button>
                {feedbackDetailsOpen ? (
                  <div className="admin-config-feedback-details">
                    {feedback.dependencyDetails?.length ? (
                      <dl className="admin-config-dependency-list">
                        {feedback.dependencyDetails.map((detail) => (
                          <Fragment key={detail.label}>
                            <dt>{detail.label}</dt>
                            <dd>{detail.count.toLocaleString('en-SG')}</dd>
                          </Fragment>
                        ))}
                      </dl>
                    ) : null}
                    {feedback.rawMessage ? (
                      <p className="admin-config-raw-error">{feedback.rawMessage}</p>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
          <button
            type="button"
            className="admin-config-feedback-dismiss"
            onClick={dismissFeedback}
            aria-label="Dismiss feedback"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {reportingPeriodsLoading ? (
        <div className="configuration-empty-note">Loading reporting periods...</div>
      ) : reportingPeriodsError ? (
        <div className="configuration-empty-note">
          <div>
            <h3>Unable to load reporting periods</h3>
            <p>{reportingPeriodsError}</p>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void reloadReportingPeriods()}
            >
              <IconRefresh size={14} />
              Retry
            </button>
          </div>
        </div>
      ) : sortedPeriods.length === 0 ? (
        <div className="configuration-empty-note">
          <div>
            <h3>No reporting periods yet</h3>
            <p>Create the first period before upload workflows are used.</p>
          </div>
        </div>
      ) : (
        <div className="admin-config-table-wrap">
          <table className="admin-config-table reporting-periods-table">
            <thead>
              <tr>
                <th>Label</th>
                <th>Start Date</th>
                <th>End Date</th>
                <th>Status</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedPeriods.map((period) => (
                <Fragment key={period.id}>
                  <tr>
                    <td>{period.label}</td>
                    <td>{formatDate(period.startDate)}</td>
                    <td>{formatDate(period.endDate)}</td>
                    <td>
                      <StatusBadge label={period.status} tone={periodStatusTone(period.status)} />
                    </td>
                    <td>{formatDate(period.updatedAt)}</td>
                    <td>
                      <div className="admin-config-row-actions">
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => openEditDrawer(period)}
                          disabled={deletingId === period.id}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="button button-ghost danger"
                          onClick={() => requestDelete(period)}
                          disabled={deletingId === period.id}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                  {confirmingDeletePeriod?.id === period.id ? (
                    <tr className="admin-config-confirm-row">
                      <td colSpan={6}>
                        <div
                          className="admin-config-inline-confirm"
                          role="group"
                          aria-label={`Delete reporting period ${period.label}`}
                        >
                          <div>
                            <strong>{`Delete reporting period "${period.label}"?`}</strong>
                            <p>
                              This only succeeds if the period has no linked uploads or parsed
                              records.
                            </p>
                          </div>
                          <div className="admin-config-confirm-actions">
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => setConfirmingDeletePeriod(null)}
                              disabled={deletingId === period.id}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="button button-ghost danger"
                              onClick={() => void handleDelete(period)}
                              disabled={deletingId === period.id}
                            >
                              {deletingId === period.id ? 'Deleting...' : 'Delete period'}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <DetailDrawer
        title={drawerMode === 'edit' ? 'Edit Reporting Period' : 'New Reporting Period'}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-secondary" onClick={closeDrawer}>
              Cancel
            </button>
            <button
              type="submit"
              form="reporting-period-form"
              className="button button-primary"
              disabled={submitState === 'submitting'}
            >
              {submitState === 'submitting' ? 'Saving...' : 'Save'}
            </button>
          </>
        }
      >
        <form id="reporting-period-form" className="secretary-form-grid" onSubmit={handleSubmit}>
          <label>
            Label
            <input
              type="text"
              value={formState.label}
              onChange={(event) => setFormState((prev) => ({ ...prev, label: event.target.value }))}
              required
              maxLength={30}
            />
          </label>
          <div className="secretary-form-row">
            <label>
              Start date
              <input
                type="date"
                value={formState.startDate}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, startDate: event.target.value }))
                }
                required
              />
            </label>
            <label>
              End date
              <input
                type="date"
                value={formState.endDate}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, endDate: event.target.value }))
                }
                required
              />
            </label>
          </div>
          {drawerMode === 'edit' ? (
            <label>
              Status
              <select
                value={formState.status}
                onChange={(event) =>
                  setFormState((prev) => ({
                    ...prev,
                    status: event.target.value === 'closed' ? 'closed' : 'open',
                  }))
                }
              >
                <option value="open">Open</option>
                <option value="closed">Closed</option>
              </select>
            </label>
          ) : null}
          {submitState === 'error' && feedback ? (
            <div className="inline-callout callout-error">{feedback.message}</div>
          ) : null}
        </form>
      </DetailDrawer>
    </>
  )
}

const PublicHolidaysSection = () => {
  const { demoAdminId, demoAdminProgrammes } = useAppState()
  const [publicHolidays, setPublicHolidays] = useState<PublicHoliday[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit'>('create')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedHoliday, setSelectedHoliday] = useState<PublicHoliday | null>(null)
  const [formState, setFormState] = useState<PublicHolidayFormState>(emptyPublicHolidayForm)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmingDeleteHoliday, setConfirmingDeleteHoliday] = useState<PublicHoliday | null>(null)

  const sortedHolidays = useMemo(
    () =>
      [...publicHolidays].sort((left, right) => {
        const leftDate = new Date(left.holidayDate).getTime()
        const rightDate = new Date(right.holidayDate).getTime()
        return leftDate - rightDate
      }),
    [publicHolidays],
  )

  const datePreview = deriveDatePreview(formState.holidayDate)

  const reloadPublicHolidays = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const rows = await listPublicHolidays({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
      })
      setPublicHolidays(rows)
    } catch (error) {
      const message =
        error instanceof ApiRequestError ? error.message : 'Unable to load public holidays.'
      setLoadError(message)
      setPublicHolidays([])
    } finally {
      setLoading(false)
    }
  }, [demoAdminId, demoAdminProgrammes])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        void reloadPublicHolidays()
      }
    })
    return () => {
      cancelled = true
    }
  }, [reloadPublicHolidays])

  const dismissFeedback = () => setFeedback(null)

  const openCreateDrawer = () => {
    setDrawerMode('create')
    setSelectedHoliday(null)
    setFormState(emptyPublicHolidayForm)
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteHoliday(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (holiday: PublicHoliday) => {
    setDrawerMode('edit')
    setSelectedHoliday(holiday)
    setFormState(toPublicHolidayFormState(holiday))
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteHoliday(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (submitState === 'submitting') {
      return
    }
    setDrawerOpen(false)
    setSelectedHoliday(null)
    setFormState(emptyPublicHolidayForm)
    setSubmitState('idle')
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitState('submitting')
    setFeedback(null)
    try {
      if (drawerMode === 'edit' && selectedHoliday) {
        await updatePublicHoliday({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          id: selectedHoliday.id,
          payload: formState,
        })
        setFeedback({ tone: 'success', message: 'Public holiday updated.' })
      } else {
        await createPublicHoliday({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          payload: formState,
        })
        setFeedback({ tone: 'success', message: 'Public holiday created.' })
      }
      await reloadPublicHolidays()
      setDrawerOpen(false)
      setSelectedHoliday(null)
      setFormState(emptyPublicHolidayForm)
      setSubmitState('idle')
    } catch (error) {
      setSubmitState('error')
      setFeedback(describePublicHolidayError(error, 'Unable to save public holiday.'))
    }
  }

  const requestDelete = (holiday: PublicHoliday) => {
    setFeedback(null)
    setConfirmingDeleteHoliday(holiday)
  }

  const handleDelete = async (holiday: PublicHoliday) => {
    setDeletingId(holiday.id)
    setFeedback(null)
    try {
      await deletePublicHoliday({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        id: holiday.id,
      })
      setFeedback({ tone: 'success', message: 'Public holiday deleted.' })
      await reloadPublicHolidays()
      setConfirmingDeleteHoliday(null)
    } catch (error) {
      setConfirmingDeleteHoliday(null)
      setFeedback(describePublicHolidayError(error, 'Unable to delete public holiday.'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <header className="admin-config-content-header">
        <div>
          <div className="admin-config-title-row">
            <h2>Public Holidays</h2>
          </div>
          <p>Manage dates that block secretary event creation and resident ad-hoc teaching.</p>
        </div>
        <div className="admin-config-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reloadPublicHolidays()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            Retry
          </button>
          <button type="button" className="button button-primary" onClick={openCreateDrawer}>
            <IconPlus size={14} />
            New Holiday
          </button>
        </div>
      </header>

      {feedback ? (
        <div
          className={`inline-callout ${feedback.tone === 'error' ? 'callout-error' : 'callout-success'} admin-config-feedback`}
          role="status"
        >
          <div className="admin-config-feedback-content">
            <strong>{feedback.message}</strong>
            {feedback.description ? <p>{feedback.description}</p> : null}
          </div>
          <button
            type="button"
            className="admin-config-feedback-dismiss"
            onClick={dismissFeedback}
            aria-label="Dismiss feedback"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="configuration-empty-note">Loading public holidays...</div>
      ) : loadError ? (
        <div className="configuration-empty-note">
          <div>
            <h3>Unable to load public holidays</h3>
            <p>{loadError}</p>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void reloadPublicHolidays()}
            >
              <IconRefresh size={14} />
              Retry
            </button>
          </div>
        </div>
      ) : sortedHolidays.length === 0 ? (
        <div className="configuration-empty-note">
          <div>
            <h3>No public holidays configured yet.</h3>
            <p>Use this table for manual corrections after the Academic Calendar upload.</p>
          </div>
        </div>
      ) : (
        <div className="admin-config-table-wrap">
          <table className="admin-config-table public-holidays-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Day</th>
                <th>Holiday Name</th>
                <th>Year</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedHolidays.map((holiday) => (
                <Fragment key={holiday.id}>
                  <tr>
                    <td>{formatDate(holiday.holidayDate)}</td>
                    <td>{holiday.dayOfWeek ?? '-'}</td>
                    <td>{holiday.name || '-'}</td>
                    <td>{holiday.year ?? '-'}</td>
                    <td>{formatDate(holiday.updatedAt)}</td>
                    <td>
                      <div className="admin-config-row-actions">
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => openEditDrawer(holiday)}
                          disabled={deletingId === holiday.id}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="button button-ghost danger"
                          onClick={() => requestDelete(holiday)}
                          disabled={deletingId === holiday.id}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                  {confirmingDeleteHoliday?.id === holiday.id ? (
                    <tr className="admin-config-confirm-row">
                      <td colSpan={6}>
                        <div
                          className="admin-config-inline-confirm"
                          role="group"
                          aria-label={`Delete public holiday ${holiday.name}`}
                        >
                          <div>
                            <strong>
                              {`Delete public holiday "${holiday.name}" on ${holiday.holidayDate}?`}
                            </strong>
                            <p>
                              This removes the date from the manual holiday list. It does not delete
                              uploaded files or teaching records.
                            </p>
                          </div>
                          <div className="admin-config-confirm-actions">
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => setConfirmingDeleteHoliday(null)}
                              disabled={deletingId === holiday.id}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="button button-ghost danger"
                              onClick={() => void handleDelete(holiday)}
                              disabled={deletingId === holiday.id}
                            >
                              {deletingId === holiday.id ? 'Deleting...' : 'Delete holiday'}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <DetailDrawer
        title={drawerMode === 'edit' ? 'Edit Public Holiday' : 'New Public Holiday'}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-secondary" onClick={closeDrawer}>
              Cancel
            </button>
            <button
              type="submit"
              form="public-holiday-form"
              className="button button-primary"
              disabled={submitState === 'submitting'}
            >
              {submitState === 'submitting' ? 'Saving...' : 'Save'}
            </button>
          </>
        }
      >
        <form id="public-holiday-form" className="secretary-form-grid" onSubmit={handleSubmit}>
          <label>
            Holiday date
            <input
              type="date"
              value={formState.holidayDate}
              onChange={(event) =>
                setFormState((prev) => ({ ...prev, holidayDate: event.target.value }))
              }
              required
            />
          </label>
          <label>
            Holiday name
            <input
              type="text"
              value={formState.name}
              onChange={(event) => setFormState((prev) => ({ ...prev, name: event.target.value }))}
              required
              maxLength={100}
            />
          </label>
          <div className="secretary-form-row">
            <label>
              Day
              <input type="text" value={datePreview.dayOfWeek} readOnly />
            </label>
            <label>
              Year
              <input type="text" value={datePreview.year} readOnly />
            </label>
          </div>
          {submitState === 'error' && feedback ? (
            <div className="inline-callout callout-error">{feedback.message}</div>
          ) : null}
        </form>
      </DetailDrawer>
    </>
  )
}

const ProgrammesSection = () => {
  const { demoAdminId, demoAdminProgrammes, role } = useAppState()
  const adminLevel = role === 'master_admin' ? 'master' : 'programme'
  const [programmes, setProgrammes] = useState<Programme[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedProgramme, setSelectedProgramme] = useState<Programme | null>(null)
  const [formState, setFormState] = useState<ProgrammeFormState>(emptyProgrammeForm)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [feedback, setFeedback] = useState<Feedback>(null)

  const sortedProgrammes = useMemo(
    () => [...programmes].sort((left, right) => left.code.localeCompare(right.code)),
    [programmes],
  )

  const reloadProgrammes = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const rows = await listProgrammes({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
      })
      setProgrammes(rows)
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : 'Unable to load programmes.'
      setLoadError(message)
      setProgrammes([])
    } finally {
      setLoading(false)
    }
  }, [adminLevel, demoAdminId, demoAdminProgrammes])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        void reloadProgrammes()
      }
    })
    return () => {
      cancelled = true
    }
  }, [reloadProgrammes])

  const dismissFeedback = () => setFeedback(null)

  const openEditDrawer = (programme: Programme) => {
    setSelectedProgramme(programme)
    setFormState(toProgrammeFormState(programme))
    setSubmitState('idle')
    setFeedback(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (submitState === 'submitting') {
      return
    }
    setDrawerOpen(false)
    setSelectedProgramme(null)
    setFormState(emptyProgrammeForm)
    setSubmitState('idle')
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!selectedProgramme) {
      return
    }
    setSubmitState('submitting')
    setFeedback(null)
    try {
      await updateProgramme({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        code: selectedProgramme.code,
        payload: {
          rYearRequired: formState.rYearRequired,
          isSubspecialty: formState.isSubspecialty,
          rdbAlias: formState.rdbAlias.trim() || null,
        },
      })
      setFeedback({ tone: 'success', message: 'Programme updated.' })
      await reloadProgrammes()
      setDrawerOpen(false)
      setSelectedProgramme(null)
      setFormState(emptyProgrammeForm)
      setSubmitState('idle')
    } catch (error) {
      setSubmitState('error')
      setFeedback(describeGenericConfigError(error, 'Unable to update programme.'))
    }
  }

  return (
    <>
      <header className="admin-config-content-header">
        <div>
          <div className="admin-config-title-row">
            <h2>Programmes</h2>
          </div>
          <p>Review seeded programmes and edit only parser-facing configuration flags.</p>
        </div>
        <div className="admin-config-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reloadProgrammes()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            Retry
          </button>
        </div>
      </header>

      {feedback ? (
        <div
          className={`inline-callout ${feedback.tone === 'error' ? 'callout-error' : 'callout-success'} admin-config-feedback`}
          role="status"
        >
          <div className="admin-config-feedback-content">
            <strong>{feedback.message}</strong>
            {feedback.description ? <p>{feedback.description}</p> : null}
          </div>
          <button
            type="button"
            className="admin-config-feedback-dismiss"
            onClick={dismissFeedback}
            aria-label="Dismiss feedback"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="configuration-empty-note">Loading programmes...</div>
      ) : loadError ? (
        <div className="configuration-empty-note">
          <div>
            <h3>Unable to load programmes</h3>
            <p>{loadError}</p>
            <button type="button" className="button button-secondary" onClick={() => void reloadProgrammes()}>
              <IconRefresh size={14} />
              Retry
            </button>
          </div>
        </div>
      ) : sortedProgrammes.length === 0 ? (
        <div className="configuration-empty-note">
          <div>
            <h3>No programmes available for this admin scope.</h3>
            <p>Programme scope is enforced by the backend. Empty scope does not grant all-programme access.</p>
          </div>
        </div>
      ) : (
        <div className="admin-config-table-wrap">
          <table className="admin-config-table programmes-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Name</th>
                <th>AY Category</th>
                <th>R-Year Required</th>
                <th>Subspecialty</th>
                <th>RDB Alias</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedProgrammes.map((programme) => (
                <tr key={programme.id}>
                  <td className="mono">{programme.code}</td>
                  <td>{programme.name}</td>
                  <td>{formatAyCategory(programme.ayDateCategory)}</td>
                  <td>
                    <StatusBadge
                      label={programme.rYearRequired ? 'Yes' : 'No'}
                      tone={booleanTone(programme.rYearRequired)}
                    />
                  </td>
                  <td>
                    <StatusBadge
                      label={programme.isSubspecialty ? 'Yes' : 'No'}
                      tone={booleanTone(programme.isSubspecialty)}
                    />
                  </td>
                  <td>{programme.rdbAlias ?? '-'}</td>
                  <td>
                    <div className="admin-config-row-actions">
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => openEditDrawer(programme)}
                      >
                        Edit
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <DetailDrawer
        title="Edit Programme"
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-secondary" onClick={closeDrawer}>
              Cancel
            </button>
            <button
              type="submit"
              form="programme-form"
              className="button button-primary"
              disabled={submitState === 'submitting'}
            >
              {submitState === 'submitting' ? 'Saving...' : 'Save'}
            </button>
          </>
        }
      >
        <form id="programme-form" className="secretary-form-grid" onSubmit={handleSubmit}>
          <div className="secretary-form-row">
            <label>
              Code
              <input type="text" value={selectedProgramme?.code ?? ''} readOnly />
            </label>
            <label>
              Classification
              <input type="text" value={selectedProgramme?.classification ?? '-'} readOnly />
            </label>
          </div>
          <label>
            Name
            <input type="text" value={selectedProgramme?.name ?? ''} readOnly />
          </label>
          <label>
            AY category
            <input
              type="text"
              value={selectedProgramme ? formatAyCategory(selectedProgramme.ayDateCategory) : ''}
              readOnly
            />
          </label>
          <label className="admin-config-checkbox-row">
            <input
              type="checkbox"
              checked={formState.rYearRequired}
              onChange={(event) =>
                setFormState((prev) => ({ ...prev, rYearRequired: event.target.checked }))
              }
            />
            R-year required
          </label>
          <label className="admin-config-checkbox-row">
            <input
              type="checkbox"
              checked={formState.isSubspecialty}
              onChange={(event) =>
                setFormState((prev) => ({ ...prev, isSubspecialty: event.target.checked }))
              }
            />
            Subspecialty R-year remapping
          </label>
          <label>
            RDB alias
            <input
              type="text"
              value={formState.rdbAlias}
              onChange={(event) =>
                setFormState((prev) => ({ ...prev, rdbAlias: event.target.value }))
              }
              maxLength={100}
              placeholder="Leave blank when no alias is needed"
            />
          </label>
          <div className="inline-callout callout-neutral">
            Changes affect future parsing/uploads only. Existing parsed postings and targets are not recalculated.
          </div>
          {submitState === 'error' && feedback ? (
            <div className="inline-callout callout-error">{feedback.message}</div>
          ) : null}
        </form>
      </DetailDrawer>
    </>
  )
}

const LoaTypesSection = () => {
  const { demoAdminId, demoAdminProgrammes, role } = useAppState()
  const adminLevel = role === 'master_admin' ? 'master' : 'programme'
  const [loaTypes, setLoaTypes] = useState<LoaType[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit'>('create')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedLoaType, setSelectedLoaType] = useState<LoaType | null>(null)
  const [formState, setFormState] = useState<LoaTypeFormState>(emptyLoaTypeForm)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmingDeleteLoaType, setConfirmingDeleteLoaType] = useState<LoaType | null>(null)

  const sortedLoaTypes = useMemo(
    () => [...loaTypes].sort((left, right) => left.code.localeCompare(right.code)),
    [loaTypes],
  )

  const reloadLoaTypes = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const rows = await listLoaTypes({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
      })
      setLoaTypes(rows)
    } catch (error) {
      const message = error instanceof ApiRequestError ? error.message : 'Unable to load LOA types.'
      setLoadError(message)
      setLoaTypes([])
    } finally {
      setLoading(false)
    }
  }, [adminLevel, demoAdminId, demoAdminProgrammes])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        void reloadLoaTypes()
      }
    })
    return () => {
      cancelled = true
    }
  }, [reloadLoaTypes])

  const dismissFeedback = () => setFeedback(null)

  const openCreateDrawer = () => {
    setDrawerMode('create')
    setSelectedLoaType(null)
    setFormState(emptyLoaTypeForm)
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteLoaType(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (loaType: LoaType) => {
    setDrawerMode('edit')
    setSelectedLoaType(loaType)
    setFormState(toLoaTypeFormState(loaType))
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteLoaType(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (submitState === 'submitting') {
      return
    }
    setDrawerOpen(false)
    setSelectedLoaType(null)
    setFormState(emptyLoaTypeForm)
    setSubmitState('idle')
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitState('submitting')
    setFeedback(null)
    const payload = {
      code: formState.code.trim(),
      description: formState.description.trim() || null,
    }
    try {
      if (drawerMode === 'edit' && selectedLoaType) {
        await updateLoaType({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          id: selectedLoaType.id,
          payload,
        })
        setFeedback({ tone: 'success', message: 'LOA type updated.' })
      } else {
        await createLoaType({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          payload,
        })
        setFeedback({ tone: 'success', message: 'LOA type created.' })
      }
      await reloadLoaTypes()
      setDrawerOpen(false)
      setSelectedLoaType(null)
      setFormState(emptyLoaTypeForm)
      setSubmitState('idle')
    } catch (error) {
      setSubmitState('error')
      setFeedback(
        describeGenericConfigError(
          error,
          'Unable to save LOA type.',
          'That LOA type code may already exist. Use edit on the existing row instead.',
        ),
      )
    }
  }

  const requestDelete = (loaType: LoaType) => {
    setFeedback(null)
    setConfirmingDeleteLoaType(loaType)
  }

  const handleDelete = async (loaType: LoaType) => {
    setDeletingId(loaType.id)
    setFeedback(null)
    try {
      await deleteLoaType({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        id: loaType.id,
      })
      setFeedback({ tone: 'success', message: 'LOA type deleted.' })
      await reloadLoaTypes()
      setConfirmingDeleteLoaType(null)
    } catch (error) {
      setConfirmingDeleteLoaType(null)
      setFeedback(describeGenericConfigError(error, 'Unable to delete LOA type.'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <header className="admin-config-content-header">
        <div>
          <div className="admin-config-title-row">
            <h2>LOA Types</h2>
          </div>
          <p>Maintain the validation catalogue used by future RDB uploads.</p>
        </div>
        <div className="admin-config-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reloadLoaTypes()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            Retry
          </button>
          <button type="button" className="button button-primary" onClick={openCreateDrawer}>
            <IconPlus size={14} />
            New LOA Type
          </button>
        </div>
      </header>

      {feedback ? (
        <div
          className={`inline-callout ${feedback.tone === 'error' ? 'callout-error' : 'callout-success'} admin-config-feedback`}
          role="status"
        >
          <div className="admin-config-feedback-content">
            <strong>{feedback.message}</strong>
            {feedback.description ? <p>{feedback.description}</p> : null}
          </div>
          <button
            type="button"
            className="admin-config-feedback-dismiss"
            onClick={dismissFeedback}
            aria-label="Dismiss feedback"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="configuration-empty-note">Loading LOA types...</div>
      ) : loadError ? (
        <div className="configuration-empty-note">
          <div>
            <h3>Unable to load LOA types</h3>
            <p>{loadError}</p>
            <button type="button" className="button button-secondary" onClick={() => void reloadLoaTypes()}>
              <IconRefresh size={14} />
              Retry
            </button>
          </div>
        </div>
      ) : sortedLoaTypes.length === 0 ? (
        <div className="configuration-empty-note">
          <div>
            <h3>No LOA types configured yet.</h3>
            <p>Add catalogue rows for future RDB validation. Existing uploaded records are not changed.</p>
          </div>
        </div>
      ) : (
        <div className="admin-config-table-wrap">
          <table className="admin-config-table loa-types-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Description</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedLoaTypes.map((loaType) => (
                <Fragment key={loaType.id}>
                  <tr>
                    <td>{loaType.code}</td>
                    <td>{loaType.description ?? '-'}</td>
                    <td>{formatDate(loaType.updatedAt ?? loaType.createdAt)}</td>
                    <td>
                      <div className="admin-config-row-actions">
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => openEditDrawer(loaType)}
                          disabled={deletingId === loaType.id}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="button button-ghost danger"
                          onClick={() => requestDelete(loaType)}
                          disabled={deletingId === loaType.id}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                  {confirmingDeleteLoaType?.id === loaType.id ? (
                    <tr className="admin-config-confirm-row">
                      <td colSpan={4}>
                        <div
                          className="admin-config-inline-confirm"
                          role="group"
                          aria-label={`Delete LOA type ${loaType.code}`}
                        >
                          <div>
                            <strong>{`Delete LOA type "${loaType.code}"?`}</strong>
                            <p>
                              This removes it from the validation catalogue. Existing uploaded records
                              are not changed.
                            </p>
                          </div>
                          <div className="admin-config-confirm-actions">
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => setConfirmingDeleteLoaType(null)}
                              disabled={deletingId === loaType.id}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="button button-ghost danger"
                              onClick={() => void handleDelete(loaType)}
                              disabled={deletingId === loaType.id}
                            >
                              {deletingId === loaType.id ? 'Deleting...' : 'Delete LOA type'}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <DetailDrawer
        title={drawerMode === 'edit' ? 'Edit LOA Type' : 'New LOA Type'}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-secondary" onClick={closeDrawer}>
              Cancel
            </button>
            <button
              type="submit"
              form="loa-type-form"
              className="button button-primary"
              disabled={submitState === 'submitting'}
            >
              {submitState === 'submitting' ? 'Saving...' : 'Save'}
            </button>
          </>
        }
      >
        <form id="loa-type-form" className="secretary-form-grid" onSubmit={handleSubmit}>
          <label>
            Code
            <input
              type="text"
              value={formState.code}
              onChange={(event) => setFormState((prev) => ({ ...prev, code: event.target.value }))}
              required
              maxLength={50}
            />
          </label>
          <label>
            Description
            <textarea
              value={formState.description}
              onChange={(event) =>
                setFormState((prev) => ({ ...prev, description: event.target.value }))
              }
              maxLength={100}
              rows={3}
            />
          </label>
          {submitState === 'error' && feedback ? (
            <div className="inline-callout callout-error">{feedback.message}</div>
          ) : null}
        </form>
      </DetailDrawer>
    </>
  )
}

const PostingGroupsSection = () => {
  const { demoAdminId, demoAdminProgrammes, role } = useAppState()
  const adminLevel = role === 'master_admin' ? 'master' : 'programme'
  const [postingGroups, setPostingGroups] = useState<PostingGroup[]>([])
  const [programmeOptions, setProgrammeOptions] = useState<Programme[]>([])
  const [postingCodeOptions, setPostingCodeOptions] = useState<PostingCodeOption[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit'>('create')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedPostingGroup, setSelectedPostingGroup] = useState<PostingGroup | null>(null)
  const [formState, setFormState] = useState<PostingGroupFormState>(emptyPostingGroupForm)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmingDeleteGroup, setConfirmingDeleteGroup] = useState<PostingGroup | null>(null)

  const sortedGroups = useMemo(
    () =>
      [...postingGroups].sort(
        (left, right) =>
          left.programmeCode.localeCompare(right.programmeCode) ||
          left.groupCode.localeCompare(right.groupCode) ||
          left.postingCode.localeCompare(right.postingCode),
      ),
    [postingGroups],
  )

  const sortedProgrammeOptions = useMemo(
    () => [...programmeOptions].sort((left, right) => left.code.localeCompare(right.code)),
    [programmeOptions],
  )

  const sortedPostingCodeOptions = useMemo(
    () => [...postingCodeOptions].sort((left, right) => left.code.localeCompare(right.code)),
    [postingCodeOptions],
  )

  const programmeMap = useMemo(
    () => new Map(programmeOptions.map((programme) => [programme.code, programme])),
    [programmeOptions],
  )

  const postingCodeMap = useMemo(
    () => new Map(postingCodeOptions.map((postingCode) => [postingCode.code, postingCode])),
    [postingCodeOptions],
  )

  const reloadPostingGroups = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [groupRows, postingRows, programmeRows] = await Promise.all([
        listPostingGroups({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
        }),
        listPostingCodes({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
        }),
        role === 'master_admin'
          ? listProgrammes({
              adminId: demoAdminId,
              adminProgrammes: demoAdminProgrammes,
              adminLevel,
            })
          : Promise.resolve(
              demoAdminProgrammes.map((code) => ({
                id: code,
                code,
                name: '',
                ayDateCategory: '',
                rYearRequired: false,
                isSubspecialty: false,
              })),
            ),
      ])
      setPostingGroups(groupRows)
      setPostingCodeOptions(postingRows)
      setProgrammeOptions(programmeRows)
    } catch (error) {
      const message =
        error instanceof ApiRequestError ? error.message : 'Unable to load posting groups.'
      setLoadError(message)
      setPostingGroups([])
      setPostingCodeOptions([])
      setProgrammeOptions([])
    } finally {
      setLoading(false)
    }
  }, [adminLevel, demoAdminId, demoAdminProgrammes, role])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        void reloadPostingGroups()
      }
    })
    return () => {
      cancelled = true
    }
  }, [reloadPostingGroups])

  const dismissFeedback = () => setFeedback(null)

  const openCreateDrawer = () => {
    setDrawerMode('create')
    setSelectedPostingGroup(null)
    setFormState({
      ...emptyPostingGroupForm,
      programmeCode: sortedProgrammeOptions[0]?.code ?? '',
      postingCode: sortedPostingCodeOptions[0]?.code ?? '',
    })
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteGroup(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (postingGroup: PostingGroup) => {
    setDrawerMode('edit')
    setSelectedPostingGroup(postingGroup)
    setFormState(toPostingGroupFormState(postingGroup))
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteGroup(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (submitState === 'submitting') {
      return
    }
    setDrawerOpen(false)
    setSelectedPostingGroup(null)
    setFormState(emptyPostingGroupForm)
    setSubmitState('idle')
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitState('submitting')
    setFeedback(null)
    const payload = {
      programmeCode: formState.programmeCode.trim(),
      postingCode: formState.postingCode.trim(),
      groupCode: formState.groupCode.trim(),
    }
    try {
      if (drawerMode === 'edit' && selectedPostingGroup) {
        await updatePostingGroup({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          id: selectedPostingGroup.id,
          payload,
        })
        setFeedback({ tone: 'success', message: 'Posting group updated.' })
      } else {
        await createPostingGroup({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          payload,
        })
        setFeedback({ tone: 'success', message: 'Posting group created.' })
      }
      await reloadPostingGroups()
      setDrawerOpen(false)
      setSelectedPostingGroup(null)
      setFormState(emptyPostingGroupForm)
      setSubmitState('idle')
    } catch (error) {
      setSubmitState('error')
      setFeedback(
        describeGenericConfigError(
          error,
          'Unable to save posting group.',
          'A posting can belong to only one posting group per programme.',
        ),
      )
    }
  }

  const requestDelete = (postingGroup: PostingGroup) => {
    setFeedback(null)
    setConfirmingDeleteGroup(postingGroup)
  }

  const handleDelete = async (postingGroup: PostingGroup) => {
    setDeletingId(postingGroup.id)
    setFeedback(null)
    try {
      await deletePostingGroup({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        id: postingGroup.id,
      })
      setFeedback({ tone: 'success', message: 'Posting group deleted.' })
      await reloadPostingGroups()
      setConfirmingDeleteGroup(null)
    } catch (error) {
      setConfirmingDeleteGroup(null)
      setFeedback(
        describeGenericConfigError(
          error,
          'Unable to delete posting group.',
          'This posting group may be protected by related configuration. Existing uploaded records are not changed.',
        ),
      )
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <header className="admin-config-content-header posting-groups-header">
        <div>
          <div className="admin-config-title-row">
            <h2>Posting Groups</h2>
          </div>
          <p>
            Manage posting-code groups used for compliance aggregation.
            <span className="posting-groups-helper">
              Separate from Multi-Posting Rules, which affect RDB parsing.
            </span>
          </p>
        </div>
        <div className="admin-config-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reloadPostingGroups()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            Retry
          </button>
          <button type="button" className="button button-primary" onClick={openCreateDrawer}>
            <IconPlus size={14} />
            New Posting Group
          </button>
        </div>
      </header>

      {feedback ? (
        <div
          className={`inline-callout ${feedback.tone === 'error' ? 'callout-error' : 'callout-success'} admin-config-feedback`}
          role="status"
        >
          <div className="admin-config-feedback-content">
            <strong>{feedback.message}</strong>
            {feedback.description ? <p>{feedback.description}</p> : null}
          </div>
          <button
            type="button"
            className="admin-config-feedback-dismiss"
            onClick={dismissFeedback}
            aria-label="Dismiss feedback"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="configuration-empty-note">Loading posting groups...</div>
      ) : loadError ? (
        <div className="configuration-empty-note">
          <div>
            <h3>Unable to load posting groups</h3>
            <p>{loadError}</p>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void reloadPostingGroups()}
            >
              <IconRefresh size={14} />
              Retry
            </button>
          </div>
        </div>
      ) : sortedGroups.length === 0 ? (
        <div className="configuration-empty-note">
          <div>
            <h3>No posting groups configured yet.</h3>
            <p>Add groups only when related posting codes should be pooled for compliance.</p>
          </div>
        </div>
      ) : (
        <div className="admin-config-table-wrap">
          <table className="admin-config-table posting-groups-table">
            <thead>
              <tr>
                <th>Programme</th>
                <th>Group Code</th>
                <th>Posting</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedGroups.map((postingGroup) => (
                <Fragment key={postingGroup.id}>
                  <tr>
                    <td title={formatProgrammeCode(postingGroup.programmeCode, programmeMap)}>
                      {formatProgrammeCode(postingGroup.programmeCode, programmeMap)}
                    </td>
                    <td title={postingGroup.groupCode}>{postingGroup.groupCode}</td>
                    <td title={formatPostingCode(postingGroup.postingCode, postingCodeMap)}>
                      {formatPostingCode(postingGroup.postingCode, postingCodeMap)}
                    </td>
                    <td>{formatDate(postingGroup.updatedAt ?? postingGroup.createdAt)}</td>
                    <td>
                      <div className="admin-config-row-actions">
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => openEditDrawer(postingGroup)}
                          disabled={deletingId === postingGroup.id}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="button button-ghost danger"
                          onClick={() => requestDelete(postingGroup)}
                          disabled={deletingId === postingGroup.id}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                  {confirmingDeleteGroup?.id === postingGroup.id ? (
                    <tr className="admin-config-confirm-row">
                      <td colSpan={5}>
                        <div
                          className="admin-config-inline-confirm"
                          role="group"
                          aria-label="Delete posting group"
                        >
                          <div>
                            <strong>Delete posting group?</strong>
                            <p>
                              This removes the compliance aggregation link. Existing uploaded
                              records are not changed.
                            </p>
                          </div>
                          <div className="admin-config-confirm-actions">
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => setConfirmingDeleteGroup(null)}
                              disabled={deletingId === postingGroup.id}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="button button-ghost danger"
                              onClick={() => void handleDelete(postingGroup)}
                              disabled={deletingId === postingGroup.id}
                            >
                              {deletingId === postingGroup.id
                                ? 'Deleting...'
                                : 'Delete posting group'}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <DetailDrawer
        title={drawerMode === 'edit' ? 'Edit Posting Group' : 'New Posting Group'}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-secondary" onClick={closeDrawer}>
              Cancel
            </button>
            <button
              type="submit"
              form="posting-group-form"
              className="button button-primary"
              disabled={submitState === 'submitting'}
            >
              {submitState === 'submitting' ? 'Saving...' : 'Save'}
            </button>
          </>
        }
      >
        <form id="posting-group-form" className="secretary-form-grid" onSubmit={handleSubmit}>
          <section className="posting-group-form-section">
            <div>
              <h3>Group details</h3>
              <p>
                Posting groups affect compliance aggregation. They do not change RDB parsing or
                existing posting records.
              </p>
            </div>
            <div className="secretary-form-row">
              <label>
                Programme
                <select
                  value={formState.programmeCode}
                  onChange={(event) =>
                    setFormState((prev) => ({ ...prev, programmeCode: event.target.value }))
                  }
                  required
                >
                  <option value="" disabled>
                    Select programme
                  </option>
                  {formState.programmeCode &&
                  !sortedProgrammeOptions.some((option) => option.code === formState.programmeCode) ? (
                    <option value={formState.programmeCode}>
                      Current programme no longer exists
                    </option>
                  ) : null}
                  {sortedProgrammeOptions.map((programme) => (
                    <option key={programme.code} value={programme.code}>
                      {programmeOptionLabel(programme)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Posting
                <select
                  value={formState.postingCode}
                  onChange={(event) =>
                    setFormState((prev) => ({ ...prev, postingCode: event.target.value }))
                  }
                  required
                >
                  <option value="" disabled>
                    Select posting
                  </option>
                  {formState.postingCode &&
                  !sortedPostingCodeOptions.some((option) => option.code === formState.postingCode) ? (
                    <option value={formState.postingCode}>Current posting no longer exists</option>
                  ) : null}
                  {sortedPostingCodeOptions.map((postingCode) => (
                    <option key={postingCode.code} value={postingCode.code}>
                      {postingCodeOptionLabel(postingCode)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              Group code
              <input
                type="text"
                value={formState.groupCode}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, groupCode: event.target.value }))
                }
                required
                maxLength={100}
              />
              <span className="form-helper">
                Posting codes with the same group code are aggregated together during compliance.
              </span>
            </label>
          </section>
          {submitState === 'error' && feedback ? (
            <div className="inline-callout callout-error">{feedback.message}</div>
          ) : null}
        </form>
      </DetailDrawer>
    </>
  )
}

const WeekendExceptionsSection = () => {
  const { demoAdminId, demoAdminProgrammes, role } = useAppState()
  const adminLevel = role === 'master_admin' ? 'master' : 'programme'
  const [weekendExceptions, setWeekendExceptions] = useState<WeekendException[]>([])
  const [sessionTypeOptions, setSessionTypeOptions] = useState<SessionTypeOption[]>([])
  const [programmeOptions, setProgrammeOptions] = useState<Programme[]>([])
  const [postingCodeOptions, setPostingCodeOptions] = useState<PostingCodeOption[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit'>('create')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedException, setSelectedException] = useState<WeekendException | null>(null)
  const [formState, setFormState] = useState<WeekendExceptionFormState>(emptyWeekendExceptionForm)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmingDeleteException, setConfirmingDeleteException] =
    useState<WeekendException | null>(null)

  const sortedExceptions = useMemo(
    () =>
      [...weekendExceptions].sort((left, right) =>
        formatWeekendScope(left).localeCompare(formatWeekendScope(right)) ||
        left.dayType.localeCompare(right.dayType),
      ),
    [weekendExceptions],
  )

  const sortedSessionTypeOptions = useMemo(
    () => [...sessionTypeOptions].sort((left, right) => left.name.localeCompare(right.name)),
    [sessionTypeOptions],
  )

  const sortedProgrammeOptions = useMemo(
    () => [...programmeOptions].sort((left, right) => left.code.localeCompare(right.code)),
    [programmeOptions],
  )

  const sortedPostingCodeOptions = useMemo(
    () => [...postingCodeOptions].sort((left, right) => left.code.localeCompare(right.code)),
    [postingCodeOptions],
  )

  const reloadWeekendExceptions = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [exceptionRows, sessionTypeRows, programmeRows, postingRows] = await Promise.all([
        listWeekendExceptions({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
        }),
        listSessionTypes({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          limit: 500,
        }),
        listProgrammes({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
        }),
        listPostingCodes({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
        }),
      ])
      setWeekendExceptions(exceptionRows)
      setSessionTypeOptions(sessionTypeRows)
      setProgrammeOptions(programmeRows)
      setPostingCodeOptions(postingRows)
    } catch (error) {
      const message =
        error instanceof ApiRequestError
          ? error.message
          : 'Unable to load weekend exceptions or selector options.'
      setLoadError(message)
      setWeekendExceptions([])
      setSessionTypeOptions([])
      setProgrammeOptions([])
      setPostingCodeOptions([])
    } finally {
      setLoading(false)
    }
  }, [adminLevel, demoAdminId, demoAdminProgrammes])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        void reloadWeekendExceptions()
      }
    })
    return () => {
      cancelled = true
    }
  }, [reloadWeekendExceptions])

  const dismissFeedback = () => setFeedback(null)

  const openCreateDrawer = () => {
    setDrawerMode('create')
    setSelectedException(null)
    setFormState(emptyWeekendExceptionForm)
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteException(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (weekendException: WeekendException) => {
    setDrawerMode('edit')
    setSelectedException(weekendException)
    setFormState(toWeekendExceptionFormState(weekendException))
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteException(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (submitState === 'submitting') {
      return
    }
    setDrawerOpen(false)
    setSelectedException(null)
    setFormState(emptyWeekendExceptionForm)
    setSubmitState('idle')
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitState('submitting')
    setFeedback(null)
    const payload = {
      programmeCode: normaliseOptionalText(formState.programmeCode),
      postingCode: normaliseOptionalText(formState.postingCode),
      dayType: formState.dayType,
      startTimeMin: normaliseOptionalText(formState.startTimeMin),
      endTimeMax: normaliseOptionalText(formState.endTimeMax),
      sessionTypeId: normaliseOptionalText(formState.sessionTypeId),
      sessionNamePattern: normaliseOptionalText(formState.sessionNamePattern),
      mutatesToSessionTypeId: normaliseOptionalText(formState.mutatesToSessionTypeId),
      adjustedDurationHours: normaliseOptionalText(formState.adjustedDurationHours),
    }
    try {
      if (drawerMode === 'edit' && selectedException) {
        await updateWeekendException({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          id: selectedException.id,
          payload,
        })
        setFeedback({ tone: 'success', message: 'Weekend exception updated.' })
      } else {
        await createWeekendException({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          payload,
        })
        setFeedback({ tone: 'success', message: 'Weekend exception created.' })
      }
      await reloadWeekendExceptions()
      setDrawerOpen(false)
      setSelectedException(null)
      setFormState(emptyWeekendExceptionForm)
      setSubmitState('idle')
    } catch (error) {
      setSubmitState('error')
      setFeedback(describeWeekendExceptionError(error, 'Unable to save weekend exception.'))
    }
  }

  const requestDelete = (weekendException: WeekendException) => {
    setFeedback(null)
    setConfirmingDeleteException(weekendException)
  }

  const handleDelete = async (weekendException: WeekendException) => {
    setDeletingId(weekendException.id)
    setFeedback(null)
    try {
      await deleteWeekendException({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        id: weekendException.id,
      })
      setFeedback({ tone: 'success', message: 'Weekend exception deleted.' })
      await reloadWeekendExceptions()
      setConfirmingDeleteException(null)
    } catch (error) {
      setConfirmingDeleteException(null)
      setFeedback(describeWeekendExceptionError(error, 'Unable to delete weekend exception.'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <header className="admin-config-content-header">
        <div>
          <div className="admin-config-title-row">
            <h2>Weekend Exceptions</h2>
          </div>
          <p>Configure which weekend teachings are accepted and how they should count for compliance.</p>
        </div>
        <div className="admin-config-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reloadWeekendExceptions()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            Retry
          </button>
          <button type="button" className="button button-primary" onClick={openCreateDrawer}>
            <IconPlus size={14} />
            New Weekend Exception
          </button>
        </div>
      </header>

      {feedback ? (
        <div
          className={`inline-callout ${feedback.tone === 'error' ? 'callout-error' : 'callout-success'} admin-config-feedback`}
          role="status"
        >
          <div className="admin-config-feedback-content">
            <strong>{feedback.message}</strong>
            {feedback.description ? <p>{feedback.description}</p> : null}
          </div>
          <button
            type="button"
            className="admin-config-feedback-dismiss"
            onClick={dismissFeedback}
            aria-label="Dismiss feedback"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="configuration-empty-note">Loading weekend exceptions...</div>
      ) : loadError ? (
        <div className="configuration-empty-note">
          <div>
            <h3>Unable to load weekend exceptions</h3>
            <p>{loadError}</p>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void reloadWeekendExceptions()}
            >
              <IconRefresh size={14} />
              Retry
            </button>
          </div>
        </div>
      ) : sortedExceptions.length === 0 ? (
        <div className="configuration-empty-note">
          <div>
            <h3>No weekend exceptions configured yet.</h3>
            <p>Add only confirmed weekend rules. Raw attendance remains unchanged.</p>
          </div>
        </div>
      ) : (
        <div className="admin-config-table-wrap">
          <table className="admin-config-table weekend-exceptions-table">
            <thead>
              <tr>
                <th>Scope</th>
                <th>Day</th>
                <th>Time Window</th>
                <th>Applies To</th>
                <th>Counts As</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedExceptions.map((weekendException) => (
                <Fragment key={weekendException.id}>
                  <tr>
                    <td title={formatWeekendScope(weekendException)}>
                      {formatWeekendScope(weekendException)}
                    </td>
                    <td>{dayTypeLabels[weekendException.dayType]}</td>
                    <td>{formatTimeWindow(weekendException)}</td>
                    <td title={formatWeekendMatch(weekendException)}>
                      {formatWeekendMatch(weekendException)}
                    </td>
                    <td title={formatWeekendCountsAs(weekendException)}>
                      {formatWeekendCountsAs(weekendException)}
                    </td>
                    <td>
                      <div className="admin-config-row-actions">
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => openEditDrawer(weekendException)}
                          disabled={deletingId === weekendException.id}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="button button-ghost danger"
                          onClick={() => requestDelete(weekendException)}
                          disabled={deletingId === weekendException.id}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                  {confirmingDeleteException?.id === weekendException.id ? (
                    <tr className="admin-config-confirm-row">
                      <td colSpan={6}>
                        <div
                          className="admin-config-inline-confirm"
                          role="group"
                          aria-label="Delete weekend exception"
                        >
                          <div>
                            <strong>Delete this weekend exception?</strong>
                            <p>
                              This removes the exception rule. It does not mutate attendance records
                              or recalculate historical submissions.
                            </p>
                          </div>
                          <div className="admin-config-confirm-actions">
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => setConfirmingDeleteException(null)}
                              disabled={deletingId === weekendException.id}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="button button-ghost danger"
                              onClick={() => void handleDelete(weekendException)}
                              disabled={deletingId === weekendException.id}
                            >
                              {deletingId === weekendException.id
                                ? 'Deleting...'
                                : 'Delete exception'}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <DetailDrawer
        title={drawerMode === 'edit' ? 'Edit Weekend Exception' : 'New Weekend Exception'}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-secondary" onClick={closeDrawer}>
              Cancel
            </button>
            <button
              type="submit"
              form="weekend-exception-form"
              className="button button-primary"
              disabled={submitState === 'submitting'}
            >
              {submitState === 'submitting' ? 'Saving...' : 'Save'}
            </button>
          </>
        }
      >
        <form id="weekend-exception-form" className="secretary-form-grid" onSubmit={handleSubmit}>
          <section className="weekend-exception-form-section">
            <div>
              <h3>Scope</h3>
              <p>
                Choose where this weekend exception applies. Leave posting blank to apply to all
                postings in the programme.
              </p>
            </div>
            <div className="secretary-form-row">
              <label>
                Programme
                <select
                  value={formState.programmeCode}
                  onChange={(event) =>
                    setFormState((prev) => ({ ...prev, programmeCode: event.target.value }))
                  }
                >
                  <option value="">All programmes</option>
                  {formState.programmeCode &&
                  !sortedProgrammeOptions.some((option) => option.code === formState.programmeCode) ? (
                    <option value={formState.programmeCode}>
                      Current programme no longer exists
                    </option>
                  ) : null}
                  {sortedProgrammeOptions.map((programme) => (
                    <option key={programme.code} value={programme.code}>
                      {programmeOptionLabel(programme)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Posting, optional
                <select
                  value={formState.postingCode}
                  onChange={(event) =>
                    setFormState((prev) => ({ ...prev, postingCode: event.target.value }))
                  }
                >
                  <option value="">All postings</option>
                  {formState.postingCode &&
                  !sortedPostingCodeOptions.some((option) => option.code === formState.postingCode) ? (
                    <option value={formState.postingCode}>Current posting no longer exists</option>
                  ) : null}
                  {sortedPostingCodeOptions.map((postingCode) => (
                    <option key={postingCode.code} value={postingCode.code}>
                      {postingCodeOptionLabel(postingCode)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </section>

          <section className="weekend-exception-form-section">
            <div>
              <h3>Weekend window</h3>
              <p>Choose the weekend day and optional time range that should be accepted.</p>
            </div>
            <div className="secretary-form-row">
              <label>
                Weekend day
                <select
                  value={formState.dayType}
                  onChange={(event) =>
                    setFormState((prev) => ({
                      ...prev,
                      dayType:
                        event.target.value === 'sun' || event.target.value === 'both'
                          ? event.target.value
                          : 'sat',
                    }))
                  }
                >
                  <option value="sat">Saturday</option>
                  <option value="sun">Sunday</option>
                  <option value="both">Saturday and Sunday</option>
                </select>
              </label>
              <label>
                Start time, optional
                <input
                  type="time"
                  value={formState.startTimeMin}
                  onChange={(event) =>
                    setFormState((prev) => ({ ...prev, startTimeMin: event.target.value }))
                  }
                />
              </label>
              <label>
                End time, optional
                <input
                  type="time"
                  value={formState.endTimeMax}
                  onChange={(event) =>
                    setFormState((prev) => ({ ...prev, endTimeMax: event.target.value }))
                  }
                />
              </label>
            </div>
          </section>

          <section className="weekend-exception-form-section">
            <div>
              <h3>Matching sessions</h3>
              <p>
                Choose which sessions this exception applies to. Use either a teaching-name text
                match or an uploaded TTF session type. Leave both blank to accept any session in
                the selected weekend window.
              </p>
            </div>
            <label>
              Teaching name text match
              <input
                type="text"
                value={formState.sessionNamePattern}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, sessionNamePattern: event.target.value }))
                }
                maxLength={100}
                placeholder="e.g. Urology National Teaching (Sat)"
              />
              <span className="form-helper">
                Optional free-text substring match against the teaching event name. Use this only
                when the rule depends on specific wording.
              </span>
            </label>
            <label>
              Session type is
              <select
                value={formState.sessionTypeId}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, sessionTypeId: event.target.value }))
                }
              >
                <option value="">Any session type</option>
                {formState.sessionTypeId &&
                !sortedSessionTypeOptions.some((option) => option.id === formState.sessionTypeId) ? (
                  <option value={formState.sessionTypeId}>Current session type no longer exists</option>
                ) : null}
                {sortedSessionTypeOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {sessionTypeOptionLabel(option)}
                  </option>
                ))}
              </select>
              <span className="form-helper">
                Optional. Restricts this rule to one uploaded TTF session type.
              </span>
              <span className="form-helper">
                Session type options come from uploaded TTF files. Upload additional TTFs to make
                more session types available.
              </span>
            </label>
          </section>

          <section className="weekend-exception-form-section">
            <div>
              <h3>Compliance counting</h3>
              <p>
                Usually leave this unchanged. Use a mapping only when the session should count as a
                different session type for compliance.
              </p>
            </div>
            <label>
              Count as session type
              <select
                value={formState.mutatesToSessionTypeId}
                onChange={(event) =>
                  setFormState((prev) => ({
                    ...prev,
                    mutatesToSessionTypeId: event.target.value,
                  }))
                }
              >
                <option value="">Count as submitted session</option>
                {formState.mutatesToSessionTypeId &&
                !sortedSessionTypeOptions.some(
                  (option) => option.id === formState.mutatesToSessionTypeId,
                ) ? (
                  <option value={formState.mutatesToSessionTypeId}>
                    Current session type no longer exists
                  </option>
                ) : null}
                {sortedSessionTypeOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {sessionTypeOptionLabel(option)}
                  </option>
                ))}
              </select>
              <span className="form-helper">
                Optional. Used for special cases such as ORTHO.
              </span>
              <span className="form-helper">
                Session type options come from uploaded TTF files. Upload additional TTFs to make
                more session types available.
              </span>
            </label>
            <label>
              Counted duration hours
              <input
                type="number"
                min="0.25"
                step="0.25"
                value={formState.adjustedDurationHours}
                onChange={(event) =>
                  setFormState((prev) => ({ ...prev, adjustedDurationHours: event.target.value }))
                }
                placeholder="e.g. 1.00"
              />
              <span className="form-helper">
                Enter hours as a decimal, e.g. 0.25, 1.00, 1.75. Required only when "Count as
                session type" is selected.
              </span>
            </label>
          </section>
          <div className="inline-callout callout-neutral">
            Weekend exceptions affect future submission warnings and compliance reads. Raw
            attendance records are not changed.
          </div>
          {submitState === 'error' && feedback ? (
            <div className="inline-callout callout-error">{feedback.message}</div>
          ) : null}
        </form>
      </DetailDrawer>
    </>
  )
}

const GlobalSessionTypesSection = () => {
  const { demoAdminId, demoAdminProgrammes, role } = useAppState()
  const adminLevel = role === 'master_admin' ? 'master' : 'programme'
  const [globalSessionTypes, setGlobalSessionTypes] = useState<GlobalSessionType[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit'>('create')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [selectedGlobalType, setSelectedGlobalType] = useState<GlobalSessionType | null>(null)
  const [formState, setFormState] =
    useState<GlobalSessionTypeFormState>(emptyGlobalSessionTypeForm)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [confirmingDeleteGlobalType, setConfirmingDeleteGlobalType] =
    useState<GlobalSessionType | null>(null)

  const sortedGlobalTypes = useMemo(
    () => [...globalSessionTypes].sort((left, right) => left.name.localeCompare(right.name)),
    [globalSessionTypes],
  )

  const reloadGlobalSessionTypes = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const rows = await listGlobalSessionTypes({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
      })
      setGlobalSessionTypes(rows)
    } catch (error) {
      const message =
        error instanceof ApiRequestError ? error.message : 'Unable to load global session types.'
      setLoadError(message)
      setGlobalSessionTypes([])
    } finally {
      setLoading(false)
    }
  }, [adminLevel, demoAdminId, demoAdminProgrammes])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        void reloadGlobalSessionTypes()
      }
    })
    return () => {
      cancelled = true
    }
  }, [reloadGlobalSessionTypes])

  const dismissFeedback = () => setFeedback(null)

  const openCreateDrawer = () => {
    setDrawerMode('create')
    setSelectedGlobalType(null)
    setFormState(emptyGlobalSessionTypeForm)
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteGlobalType(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (globalSessionType: GlobalSessionType) => {
    setDrawerMode('edit')
    setSelectedGlobalType(globalSessionType)
    setFormState(toGlobalSessionTypeFormState(globalSessionType))
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteGlobalType(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (submitState === 'submitting') {
      return
    }
    setDrawerOpen(false)
    setSelectedGlobalType(null)
    setFormState(emptyGlobalSessionTypeForm)
    setSubmitState('idle')
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitState('submitting')
    setFeedback(null)
    const payload = {
      name: formState.name.trim(),
      durationHours: formState.durationHours.trim(),
      isActive: formState.isActive,
    }
    try {
      if (drawerMode === 'edit' && selectedGlobalType) {
        await updateGlobalSessionType({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          id: selectedGlobalType.id,
          payload,
        })
        setFeedback({ tone: 'success', message: 'Global session type updated.' })
      } else {
        await createGlobalSessionType({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          payload,
        })
        setFeedback({ tone: 'success', message: 'Global session type created.' })
      }
      await reloadGlobalSessionTypes()
      setDrawerOpen(false)
      setSelectedGlobalType(null)
      setFormState(emptyGlobalSessionTypeForm)
      setSubmitState('idle')
    } catch (error) {
      setSubmitState('error')
      setFeedback(
        describeGenericConfigError(
          error,
          'Unable to save global session type.',
          'That global session type may already exist. Use edit on the existing row instead.',
        ),
      )
    }
  }

  const requestDelete = (globalSessionType: GlobalSessionType) => {
    setFeedback(null)
    setConfirmingDeleteGlobalType(globalSessionType)
  }

  const handleDelete = async (globalSessionType: GlobalSessionType) => {
    setDeletingId(globalSessionType.id)
    setFeedback(null)
    try {
      await deleteGlobalSessionType({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        id: globalSessionType.id,
      })
      setFeedback({ tone: 'success', message: 'Global session type deleted.' })
      await reloadGlobalSessionTypes()
      setConfirmingDeleteGlobalType(null)
    } catch (error) {
      setConfirmingDeleteGlobalType(null)
      setFeedback(
        describeGenericConfigError(
          error,
          'Unable to delete global session type.',
          'This global session type is already used by teaching events. Deactivate it instead.',
        ),
      )
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <>
      <header className="admin-config-content-header">
        <div>
          <div className="admin-config-title-row">
            <h2>Global Session Types</h2>
          </div>
          <p>Manage compliance-exempt session names that remain selectable for teaching events.</p>
        </div>
        <div className="admin-config-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reloadGlobalSessionTypes()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            Retry
          </button>
          <button type="button" className="button button-primary" onClick={openCreateDrawer}>
            <IconPlus size={14} />
            New Global Session Type
          </button>
        </div>
      </header>

      {feedback ? (
        <div
          className={`inline-callout ${feedback.tone === 'error' ? 'callout-error' : 'callout-success'} admin-config-feedback`}
          role="status"
        >
          <div className="admin-config-feedback-content">
            <strong>{feedback.message}</strong>
            {feedback.description ? <p>{feedback.description}</p> : null}
          </div>
          <button
            type="button"
            className="admin-config-feedback-dismiss"
            onClick={dismissFeedback}
            aria-label="Dismiss feedback"
          >
            Dismiss
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="configuration-empty-note">Loading global session types...</div>
      ) : loadError ? (
        <div className="configuration-empty-note">
          <div>
            <h3>Unable to load global session types</h3>
            <p>{loadError}</p>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void reloadGlobalSessionTypes()}
            >
              <IconRefresh size={14} />
              Retry
            </button>
          </div>
        </div>
      ) : sortedGlobalTypes.length === 0 ? (
        <div className="configuration-empty-note">
          <div>
            <h3>No global session types configured yet.</h3>
            <p>Add compliance-exempt teaching names only when they are confirmed.</p>
          </div>
        </div>
      ) : (
        <div className="admin-config-table-wrap">
          <table className="admin-config-table global-session-types-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Duration</th>
                <th>Status</th>
                <th>Updated</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedGlobalTypes.map((globalSessionType) => (
                <Fragment key={globalSessionType.id}>
                  <tr>
                    <td title={globalSessionType.name}>{globalSessionType.name}</td>
                    <td>{formatHourValue(globalSessionType.durationHours)}</td>
                    <td>
                      <StatusBadge
                        label={globalSessionType.isActive ? 'Active' : 'Inactive'}
                        tone={booleanTone(globalSessionType.isActive)}
                      />
                    </td>
                    <td>{formatDate(globalSessionType.updatedAt ?? globalSessionType.createdAt)}</td>
                    <td>
                      <div className="admin-config-row-actions">
                        <button
                          type="button"
                          className="button button-secondary"
                          onClick={() => openEditDrawer(globalSessionType)}
                          disabled={deletingId === globalSessionType.id}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="button button-ghost danger"
                          onClick={() => requestDelete(globalSessionType)}
                          disabled={deletingId === globalSessionType.id}
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                  {confirmingDeleteGlobalType?.id === globalSessionType.id ? (
                    <tr className="admin-config-confirm-row">
                      <td colSpan={5}>
                        <div
                          className="admin-config-inline-confirm"
                          role="group"
                          aria-label={`Delete global session type ${globalSessionType.name}`}
                        >
                          <div>
                            <strong>{`Delete global session type "${globalSessionType.name}"?`}</strong>
                            <p>
                              This only succeeds when no teaching events use this name. If it is in
                              use, deactivate it instead.
                            </p>
                          </div>
                          <div className="admin-config-confirm-actions">
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => setConfirmingDeleteGlobalType(null)}
                              disabled={deletingId === globalSessionType.id}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="button button-ghost danger"
                              onClick={() => void handleDelete(globalSessionType)}
                              disabled={deletingId === globalSessionType.id}
                            >
                              {deletingId === globalSessionType.id
                                ? 'Deleting...'
                                : 'Delete global type'}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <DetailDrawer
        title={drawerMode === 'edit' ? 'Edit Global Session Type' : 'New Global Session Type'}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-secondary" onClick={closeDrawer}>
              Cancel
            </button>
            <button
              type="submit"
              form="global-session-type-form"
              className="button button-primary"
              disabled={submitState === 'submitting'}
            >
              {submitState === 'submitting' ? 'Saving...' : 'Save'}
            </button>
          </>
        }
      >
        <form id="global-session-type-form" className="secretary-form-grid" onSubmit={handleSubmit}>
          <label>
            Name
            <input
              type="text"
              value={formState.name}
              onChange={(event) => setFormState((prev) => ({ ...prev, name: event.target.value }))}
              required
              maxLength={100}
            />
          </label>
          <label>
            Duration hours
            <input
              type="number"
              min="0.25"
              step="0.25"
              value={formState.durationHours}
              onChange={(event) =>
                setFormState((prev) => ({ ...prev, durationHours: event.target.value }))
              }
              required
            />
          </label>
          <label className="admin-config-checkbox-row">
            <input
              type="checkbox"
              checked={formState.isActive}
              onChange={(event) =>
                setFormState((prev) => ({ ...prev, isActive: event.target.checked }))
              }
            />
            Active and selectable
          </label>
          <div className="inline-callout callout-neutral">
            Active global session types remain selectable and are excluded from PTT compliance by
            server-side read logic.
          </div>
          {submitState === 'error' && feedback ? (
            <div className="inline-callout callout-error">{feedback.message}</div>
          ) : null}
        </form>
      </DetailDrawer>
    </>
  )
}

const PlaceholderConfigSection = ({
  activeSection,
}: {
  activeSection: ConfigSection
}) => (
  <>
    <header className="admin-config-content-header">
      <div>
        <div className="admin-config-title-row">
          <h2>{activeSection.title}</h2>
          <span className="admin-config-status-chip">{activeSection.stateLabel}</span>
        </div>
        <p>{activeSection.description}</p>
      </div>
    </header>

    <div className="admin-config-callout">
      <strong>Next step</strong>
      <span>{activeSection.nextStep}</span>
    </div>

    <div className="admin-config-table-wrap">
      <table className="admin-config-table">
        <thead>
          <tr>
            <th>Area</th>
            <th>Current treatment</th>
            <th>Planned follow-up</th>
          </tr>
        </thead>
        <tbody>
          {activeSection.rows.map((row) => (
            <tr key={row.field}>
              <td className={row.mono ? 'mono' : undefined}>{row.field}</td>
              <td className={row.mono ? 'mono' : undefined}>{row.current}</td>
              <td>{row.next}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </>
)

type ConfigViewRole = 'master_admin' | 'programme_pc'

interface AdminConfigPageProps {
  configViewRole?: ConfigViewRole
}

export const AdminConfigPage = ({ configViewRole }: AdminConfigPageProps) => {
  const location = useLocation()
  const { demoAdminProgrammes, role } = useAppState()
  const configRole: ConfigViewRole = configViewRole ?? (role === 'programme_pc' ? 'programme_pc' : 'master_admin')
  const defaultSectionKey: ConfigSectionKey =
    configRole === 'programme_pc' ? 'multi-posting-rules' : 'reporting-periods'
  const requestedSection = (location.state as { configSection?: ConfigSectionKey } | null)?.configSection
  const requestedSectionKey = requestedSection ? `${location.key}:${requestedSection}` : null
  const lastHandledRequestedSection = useRef<string | null>(null)
  const [activeSectionKey, setActiveSectionKey] = useState<ConfigSectionKey>(
    requestedSection ?? defaultSectionKey,
  )
  const visibleConfigSections = useMemo(
    () =>
      configRole === 'programme_pc'
        ? configSections.filter((section) => programmePcConfigSections.includes(section.key))
        : configSections,
    [configRole],
  )
  const activeSection =
    visibleConfigSections.find((section) => section.key === activeSectionKey) ??
    visibleConfigSections[0] ??
    configSections[0]
  const subtitle =
    configRole === 'programme_pc'
      ? `Programme PC - ${demoAdminProgrammes.join(', ')}`
      : 'Master Admin - All programmes'

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (cancelled) {
        return
      }
      if (
        requestedSection &&
        requestedSectionKey !== lastHandledRequestedSection.current &&
        visibleConfigSections.some((section) => section.key === requestedSection)
      ) {
        lastHandledRequestedSection.current = requestedSectionKey
        setActiveSectionKey(requestedSection)
        return
      }
      if (!visibleConfigSections.some((section) => section.key === activeSectionKey)) {
        setActiveSectionKey(visibleConfigSections[0]?.key ?? defaultSectionKey)
      }
    })
    return () => {
      cancelled = true
    }
  }, [activeSectionKey, defaultSectionKey, requestedSection, requestedSectionKey, visibleConfigSections])

  return (
    <div className="page admin-config-page">
      <PageHero title="Configuration" subtitle={subtitle} />

      <section className="admin-config-shell" aria-label="Configuration sections">
        <nav className="admin-config-nav-card" aria-label="Configuration navigation">
          {visibleConfigSections.map((section) => {
            const isActive = section.key === activeSection.key
            return (
              <button
                key={section.key}
                type="button"
                className={`admin-config-nav-item ${isActive ? 'is-active' : ''}`}
                onClick={() => setActiveSectionKey(section.key)}
                aria-current={isActive ? 'page' : undefined}
              >
                <span className="admin-config-nav-main">
                  <NamedIcon name={section.icon} size={14} />
                  <span>{section.label}</span>
                </span>
              </button>
            )
          })}
        </nav>

        <article className="card admin-config-content-card">
          {activeSection.key === 'reporting-periods' ? (
            <ReportingPeriodsSection />
          ) : activeSection.key === 'public-holidays' ? (
            <PublicHolidaysSection />
          ) : activeSection.key === 'programmes' ? (
            <ProgrammesSection />
          ) : activeSection.key === 'loa-types' ? (
            <LoaTypesSection />
          ) : activeSection.key === 'multi-posting-rules' ? (
            <MultiPostingRulesSection configViewRole={configRole} />
          ) : activeSection.key === 'posting-groups' ? (
            <PostingGroupsSection />
          ) : activeSection.key === 'weekend-exceptions' ? (
            <WeekendExceptionsSection />
          ) : activeSection.key === 'global-session-types' ? (
            <GlobalSessionTypesSection />
          ) : (
            <PlaceholderConfigSection activeSection={activeSection} />
          )}
        </article>
      </section>
    </div>
  )
}
