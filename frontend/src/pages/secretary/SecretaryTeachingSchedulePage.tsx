import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconCalendar, IconDownload, IconPlus } from '../../components/icons'
import { frontendConfig } from '../../config/frontendConfig'
import { useAppState } from '../../context/useAppState'
import { ApiRequestError } from '../../api/http'
import {
  listSecretaryTeachingNameProgrammes,
  secretaryTeachingNamesChangedEvent,
} from '../../api/secretaryTeachingNames'
import { teachingEventCreatedByDisplay } from '../../utils/teachingEventSource'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'
import {
  isEffectivelyActiveReportingPeriod,
  reportingPeriodDisplayStatus,
} from '../../utils/reportingPeriods'
import {
  canAddTeachingFromOptions,
  resolveTeachingNameOptionsState,
} from '../../utils/teachingNameOptionsState'
import {
  loadSecretaryEventsForPeriod,
  shouldApplySecretaryEventLoad,
} from '../../utils/secretaryEventPeriodScope'
import {
  downloadSecretaryTeachingScheduleCsv,
  SECRETARY_TEACHING_EVENT_EXPORT_ERROR,
} from './secretaryTeachingScheduleExport'
import {
  createSecretaryTeachingEvent,
  deleteSecretaryTeachingEvent,
  duplicateSecretaryTeachingEvent,
  updateSecretaryTeachingEvent,
  listSecretaryTeachingEvents,
  listSecretaryTeachingNameOptions,
  sourceKeyForSecretaryTeachingEvent,
  type SecretaryTeachingEvent,
  type TeachingNameOption,
} from '../../api/secretaryEvents'
import {
  isCurrentTeachingSourceEligible,
  poolStartTimeValidationError,
  resolveSecretaryEventProgrammeContext,
  serverComputedPoolEndTime,
  shouldTemporarilyRetainPoolSource,
} from '../../utils/secretaryTeachingScheduleState'
import { createScopedRequestFence } from '../../utils/scopedRequestFence'

interface TeachingFormState {
  sourceKey: string
  eventDate: string
  startTime: string
  cmePointsAwarded: boolean
  smcEventCode: string
}

type DrawerMode = 'create' | 'duplicate' | 'edit'

const INITIAL_FORM: TeachingFormState = {
  sourceKey: '',
  eventDate: '',
  startTime: '',
  cmePointsAwarded: false,
  smcEventCode: '',
}

const EMPTY_EVENTS: SecretaryTeachingEvent[] = []
const EMPTY_TEACHING_NAME_OPTIONS: TeachingNameOption[] = []

const START_TIME_OPTIONS = Array.from({ length: 24 * 4 }, (_, index) => {
  const totalMinutes = index * 15
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
})

const toTimeInputValue = (value?: string) => {
  if (!value) {
    return ''
  }
  const parts = value.split(':')
  if (parts.length < 2) {
    return ''
  }
  return `${parts[0].padStart(2, '0')}:${parts[1].padStart(2, '0')}`
}

const formatDate = (value?: string) => {
  if (!value) {
    return '-'
  }
  const dateValue = new Date(value)
  if (!Number.isFinite(dateValue.getTime())) {
    return value
  }
  return dateValue.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const formatCompactDate = (value?: string) => {
  if (!value) {
    return '-'
  }
  const dateValue = new Date(value)
  if (!Number.isFinite(dateValue.getTime())) {
    return value
  }
  return dateValue.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const formatTime = (value?: string) => {
  if (!value) {
    return '-'
  }
  const parts = value.split(':')
  if (parts.length < 2) {
    return value
  }
  const hours = Number(parts[0])
  const minutes = parts[1]
  if (!Number.isFinite(hours)) {
    return value
  }
  const suffix = hours >= 12 ? 'pm' : 'am'
  const hour12 = hours % 12 || 12
  return `${String(hour12).padStart(2, '0')}:${minutes} ${suffix}`
}

const formatDuration = (value?: number) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '-'
  }
  const rounded = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return `${rounded}h`
}

const sourceProgrammeDisplay = (event: SecretaryTeachingEvent) => {
  if (event.sourceProgrammeCode) {
    return event.sourceProgrammeCode
  }
  if (event.globalSessionTypeId) {
    return 'Global'
  }
  return 'Legacy'
}

const normaliseApiError = (error: ApiRequestError, mode: 'list' | 'create' | 'options'): string => {
  if (error.status === 401 || error.status === 403) {
    return 'Your session could not be verified. Sign in again and retry.'
  }
  if (error.status === 422) {
    if (/public holiday/i.test(error.message)) {
      return 'Teaching events cannot be created on public holidays.'
    }
    return formatUserFacingApiError(error, {
      validationMessage: 'Teaching event could not be saved. Review the form and try again.',
    })
  }
  if (error.status === 409) {
    if (/attendance exists/i.test(error.message)) {
      return 'Teaching event cannot be edited or deleted because attendance exists.'
    }
    return formatUserFacingApiError(error, {
      conflictMessage: 'Teaching event cannot be edited or deleted because attendance exists.',
    })
  }
  if (error.isNetworkError) {
    return 'The system could not complete the request. Try again later.'
  }
  if (mode === 'list') {
    return 'Unable to load teaching events right now.'
  }
  if (mode === 'options') {
    return 'Unable to load teaching name options right now.'
  }
  return 'Unable to create teaching event right now. Please try again.'
}

const formulaUnsafeCsvPrefix = /^[=+@-]/

const sanitizeCsvCell = (cell: unknown) => {
  const value = String(cell)
  return formulaUnsafeCsvPrefix.test(value.trimStart()) ? `'${value}` : value
}

const quoteCsvCell = (cell: unknown) =>
  `"${sanitizeCsvCell(cell).replaceAll('"', '""')}"`

const buildEventCsv = (events: SecretaryTeachingEvent[]) => {
  const headers = [
    'Teaching Type',
    'Name of Teaching',
    'Date',
    'Start Time',
    'Duration',
    'CME Points',
    'SMC Event',
    'Created By',
    'Created',
  ]
  const rows = events.map((event) => [
    '',
    event.teachingName,
    event.eventDate,
    event.startTime,
    event.durationHours ?? '',
    event.cmePointsAwarded ? 'Yes' : 'No',
    event.smcEventCode ?? '',
    teachingEventCreatedByDisplay(event.createdByRole),
    event.createdAt ?? '',
  ])
  const csvRows = [headers, ...rows]
  return csvRows.map((row) => row.map(quoteCsvCell).join(',')).join('\n')
}

const isDateWithinPeriod = (eventDate: string, periodStart?: string, periodEnd?: string) => {
  if (!eventDate || !periodStart || !periodEnd) {
    return true
  }
  return eventDate >= periodStart && eventDate <= periodEnd
}

export const SecretaryTeachingSchedulePage = () => {
  const {
    reportingPeriodId,
    setReportingPeriodId,
    reportingPeriods,
    reportingPeriodsLoading,
    reportingPeriodsError,
  } = useAppState()

  const [events, setEvents] = useState<SecretaryTeachingEvent[]>([])
  const [recentCreatedEvents, setRecentCreatedEvents] = useState<SecretaryTeachingEvent[]>([])
  const [eventsLoading, setEventsLoading] = useState(true)
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [supportsEventListEndpoint, setSupportsEventListEndpoint] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const [nameOptions, setNameOptions] = useState<TeachingNameOption[]>([])
  const [nameOptionsLoading, setNameOptionsLoading] = useState(false)
  const [nameOptionsError, setNameOptionsError] = useState<string | null>(null)
  const [loadedNameOptionsContextKey, setLoadedNameOptionsContextKey] = useState<string | null>(null)
  const nameOptionsRequestFenceRef = useRef(createScopedRequestFence())
  const [teachingNameProgrammes, setTeachingNameProgrammes] = useState<string[]>([])
  const [teachingNameProgrammesLoading, setTeachingNameProgrammesLoading] = useState(true)
  const [teachingNameProgrammesLoaded, setTeachingNameProgrammesLoaded] = useState(false)
  const [teachingNameProgrammesError, setTeachingNameProgrammesError] = useState<string | null>(null)
  const [selectedTeachingNameProgrammeCode, setSelectedTeachingNameProgrammeCode] = useState('')
  const preservedEventSourceProgrammeRef = useRef<string | null>(null)
  const [pendingSourceProgrammeContextKey, setPendingSourceProgrammeContextKey] = useState<string | null>(null)

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerMode, setDrawerMode] = useState<DrawerMode>('create')
  const [sourceEvent, setSourceEvent] = useState<SecretaryTeachingEvent | null>(null)
  const [formState, setFormState] = useState<TeachingFormState>(INITIAL_FORM)
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof TeachingFormState, string>>>({})
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')
  const [submitMessage, setSubmitMessage] = useState<string | null>(null)

  const selectedPeriod = useMemo(() => {
    const candidate = reportingPeriods.find((period) => period.id === reportingPeriodId)
    return candidate && isEffectivelyActiveReportingPeriod(candidate) ? candidate : undefined
  }, [reportingPeriods, reportingPeriodId])
  const selectedPeriodId = selectedPeriod?.id ?? null
  const selectedPeriodIdRef = useRef<string | null>(selectedPeriodId)
  useEffect(() => {
    selectedPeriodIdRef.current = selectedPeriodId
  }, [selectedPeriodId])
  const nameOptionsContextKey = selectedPeriod && teachingNameProgrammesLoaded
    ? `${selectedPeriod.id}:${selectedTeachingNameProgrammeCode || 'global'}`
    : null
  const nameOptionsContextKeyRef = useRef<string | null>(nameOptionsContextKey)
  useEffect(() => {
    nameOptionsContextKeyRef.current = nameOptionsContextKey
  }, [nameOptionsContextKey])
  const nameOptionsLoaded = Boolean(
    nameOptionsContextKey && loadedNameOptionsContextKey === nameOptionsContextKey,
  )

  const loadEvents = useCallback(async (): Promise<SecretaryTeachingEvent[]> => {
    return (await loadSecretaryEventsForPeriod(selectedPeriod, listSecretaryTeachingEvents)) ?? []
  }, [selectedPeriod])

  useEffect(() => {
    let active = true
    if (!selectedPeriod) {
      void Promise.resolve().then(() => {
        if (!active) {
          return
        }
        setEvents([])
        setRecentCreatedEvents([])
        setSelectedIds(new Set())
        setEventsError(null)
        setEventsLoading(false)
      })
      return () => {
        active = false
      }
    }
    const requestedPeriodId = selectedPeriod.id
    ;(async () => {
      setEventsLoading(true)
      setEventsError(null)
      try {
        const response = await loadEvents()
        if (!active || !shouldApplySecretaryEventLoad(requestedPeriodId, selectedPeriodIdRef.current)) {
          return
        }
        setSupportsEventListEndpoint(true)
        setEvents(response)
        setSelectedIds(new Set())
        setSubmitState('idle')
        setSubmitMessage(null)
      } catch (error) {
        if (!active || !shouldApplySecretaryEventLoad(requestedPeriodId, selectedPeriodIdRef.current)) {
          return
        }
        if (error instanceof ApiRequestError && error.status === 404) {
          setSupportsEventListEndpoint(false)
          setEvents([])
          setEventsError(
            'Teaching-event list endpoint is unavailable. Showing locally created events for demo continuity.',
          )
        } else {
          const message =
            error instanceof ApiRequestError
              ? normaliseApiError(error, 'list')
              : 'Unable to load teaching events right now.'
          setEventsError(message)
        }
      } finally {
        if (active && shouldApplySecretaryEventLoad(requestedPeriodId, selectedPeriodIdRef.current)) {
          setEventsLoading(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [loadEvents, selectedPeriod])

  useEffect(() => {
    let active = true
    ;(async () => {
      setTeachingNameProgrammesLoading(true)
      setTeachingNameProgrammesError(null)
      try {
        const response = await listSecretaryTeachingNameProgrammes()
        if (!active) {
          return
        }
        const nextProgrammes = [...new Set(response.map((item) => item.programmeCode))]
        setTeachingNameProgrammes(nextProgrammes)
        setSelectedTeachingNameProgrammeCode((current) =>
          current && nextProgrammes.includes(current) ? current : nextProgrammes[0] ?? '',
        )
        setTeachingNameProgrammesLoaded(true)
      } catch (error) {
        if (!active) {
          return
        }
        setTeachingNameProgrammes([])
        setSelectedTeachingNameProgrammeCode('')
        setTeachingNameProgrammesLoaded(false)
        setTeachingNameProgrammesError(formatUserFacingApiError(error, {
          fallbackMessage: 'Unable to load authorised Teaching Name programmes.',
        }))
      } finally {
        if (active) {
          setTeachingNameProgrammesLoading(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const loadTeachingNameOptions = useCallback(async () => {
    const requestToken = nameOptionsRequestFenceRef.current.begin(nameOptionsContextKey)
    if (!selectedPeriod || !nameOptionsContextKey) {
      setNameOptions([])
      setNameOptionsError(null)
      setLoadedNameOptionsContextKey(null)
      setNameOptionsLoading(false)
      setPendingSourceProgrammeContextKey(null)
      return
    }
    const requestedContextKey = nameOptionsContextKey
    setNameOptions([])
    setNameOptionsLoading(true)
    setNameOptionsError(null)
    setLoadedNameOptionsContextKey(null)
    try {
      const options = await listSecretaryTeachingNameOptions({
        reportingPeriodId: selectedPeriod.id,
        programmeCode: selectedTeachingNameProgrammeCode || undefined,
      })
      if (!nameOptionsRequestFenceRef.current.isCurrent(requestToken, nameOptionsContextKeyRef.current)) {
        return
      }
      setNameOptions(options)
      setLoadedNameOptionsContextKey(requestedContextKey)
    } catch (error) {
      if (!nameOptionsRequestFenceRef.current.isCurrent(requestToken, nameOptionsContextKeyRef.current)) {
        return
      }
      const message =
        error instanceof ApiRequestError
          ? normaliseApiError(error, 'options')
          : 'Unable to load teaching name options.'
      setNameOptions([])
      setNameOptionsError(message)
      setLoadedNameOptionsContextKey(requestedContextKey)
    } finally {
      if (nameOptionsRequestFenceRef.current.isCurrent(requestToken, nameOptionsContextKeyRef.current)) {
        setNameOptionsLoading(false)
        setPendingSourceProgrammeContextKey((current) =>
          current === requestedContextKey ? null : current,
        )
      }
    }
  }, [nameOptionsContextKey, selectedPeriod, selectedTeachingNameProgrammeCode])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => {
      if (active) {
        return loadTeachingNameOptions()
      }
      return undefined
    })
    return () => {
      active = false
    }
  }, [loadTeachingNameOptions])

  useEffect(() => {
    const refreshOptions = () => {
      void loadTeachingNameOptions()
    }
    window.addEventListener(secretaryTeachingNamesChangedEvent, refreshOptions)
    return () => window.removeEventListener(secretaryTeachingNamesChangedEvent, refreshOptions)
  }, [loadTeachingNameOptions])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => {
      if (!active) {
        return
      }
      const preserveEventDrawer = (
        preservedEventSourceProgrammeRef.current === selectedTeachingNameProgrammeCode
      )
      preservedEventSourceProgrammeRef.current = null
      if (preserveEventDrawer) {
        return
      }
      setPendingSourceProgrammeContextKey(null)
      setFormState(INITIAL_FORM)
      setFormErrors({})
      setSourceEvent(null)
      setDrawerOpen(false)
      setSubmitState('idle')
      setSubmitMessage(null)
    })
    return () => {
      active = false
    }
  }, [selectedPeriodId, selectedTeachingNameProgrammeCode])

  const nameOptionsState = resolveTeachingNameOptionsState({
    hasContext: Boolean(nameOptionsContextKey),
    isLoading: nameOptionsLoading,
    isLoaded: nameOptionsLoaded,
    error: nameOptionsError,
    optionCount: nameOptions.length,
  })
  const currentSourceOptions = nameOptionsState === 'ready'
    ? nameOptions
    : EMPTY_TEACHING_NAME_OPTIONS
  const sourceProgrammeSwitchPending = (
    pendingSourceProgrammeContextKey !== null
    && pendingSourceProgrammeContextKey === nameOptionsContextKey
  )
  const optionsBySourceKey = useMemo(() => {
    const map = new Map<string, TeachingNameOption>()
    currentSourceOptions.forEach((option) => {
      map.set(option.sourceKey, option)
    })
    return map
  }, [currentSourceOptions])
  const retainedInactiveGlobalOption = useMemo<TeachingNameOption | undefined>(() => {
    if (drawerMode !== 'edit' || !sourceEvent?.globalSessionTypeId) {
      return undefined
    }
    const sourceKey = sourceKeyForSecretaryTeachingEvent(sourceEvent)
    if (!sourceKey || optionsBySourceKey.has(sourceKey)) {
      return undefined
    }
    return {
      sourceKey,
      keyword: sourceEvent.teachingName,
      globalSessionTypeId: sourceEvent.globalSessionTypeId,
      sessionTypeId: sourceEvent.sessionTypeId,
      sessionType: sourceEvent.sessionTypeName,
      durationHours: sourceEvent.durationHours,
      isGlobal: true,
    }
  }, [drawerMode, optionsBySourceKey, sourceEvent])
  const retainedPoolSourceOption = useMemo<TeachingNameOption | undefined>(() => {
    if (
      (drawerMode !== 'edit' && drawerMode !== 'duplicate')
      || !sourceEvent?.teachingNameId
    ) {
      return undefined
    }
    const sourceKey = sourceKeyForSecretaryTeachingEvent(sourceEvent)
    if (!sourceKey || !shouldTemporarilyRetainPoolSource({
      event: sourceEvent,
      selectedProgrammeCode: selectedTeachingNameProgrammeCode,
      optionsState: nameOptionsState,
      programmeSwitchPending: sourceProgrammeSwitchPending,
      sourceIsAvailable: optionsBySourceKey.has(sourceKey),
    })) {
      return undefined
    }
    const programmeContext = resolveSecretaryEventProgrammeContext(sourceEvent)
    return {
      sourceKey,
      keyword: sourceEvent.teachingName,
      teachingNameId: sourceEvent.teachingNameId,
      programmeCode: programmeContext.kind === 'pool_backed'
        ? programmeContext.programmeCode
        : undefined,
      durationHours: sourceEvent.durationHours,
      durationIsMapped: false,
      isGlobal: false,
    }
  }, [
    drawerMode,
    nameOptionsState,
    optionsBySourceKey,
    selectedTeachingNameProgrammeCode,
    sourceEvent,
    sourceProgrammeSwitchPending,
  ])
  const retainedEventSourceOption = retainedPoolSourceOption ?? retainedInactiveGlobalOption
  const drawerSourceOptions = useMemo(
    () => retainedEventSourceOption
      ? [...currentSourceOptions, retainedEventSourceOption]
      : currentSourceOptions,
    [currentSourceOptions, retainedEventSourceOption],
  )
  const hasCurrentEligibleSource = isCurrentTeachingSourceEligible(
    formState.sourceKey,
    currentSourceOptions,
  )
  const activeSelectedSourceOption = hasCurrentEligibleSource
    ? optionsBySourceKey.get(formState.sourceKey)
    : undefined
  const isRetainedInactiveGlobalSourceSelected =
    retainedInactiveGlobalOption?.sourceKey === formState.sourceKey
  const sourceOptionForSave = activeSelectedSourceOption
    ?? (isRetainedInactiveGlobalSourceSelected ? retainedInactiveGlobalOption : undefined)
  const selectedSourceOption = activeSelectedSourceOption
    ?? (retainedEventSourceOption?.sourceKey === formState.sourceKey
      ? retainedEventSourceOption
      : undefined)

  const visibleEvents = selectedPeriod
    ? supportsEventListEndpoint
      ? events
      : recentCreatedEvents
    : EMPTY_EVENTS
  const canAddTeaching = canAddTeachingFromOptions(nameOptionsState)
  const canSubmitTeaching = Boolean(sourceOptionForSave)
  const sourceEventProgrammeContext = sourceEvent
    ? resolveSecretaryEventProgrammeContext(sourceEvent)
    : null
  const poolSourceRequiresReselection = Boolean(
    (drawerMode === 'edit' || drawerMode === 'duplicate')
    && sourceEventProgrammeContext?.kind === 'pool_backed'
    && (nameOptionsState === 'ready' || nameOptionsState === 'empty')
    && !sourceOptionForSave,
  )
  const nameOptionsUnavailableMessage =
    nameOptionsState === 'unavailable'
      ? teachingNameProgrammesError
        ? teachingNameProgrammesError
        : teachingNameProgrammesLoading
          ? 'Loading authorised Teaching Name programmes...'
          : 'Select an active reporting period to load teaching names.'
      : nameOptionsState === 'loading'
        ? 'Loading teaching name options...'
        : nameOptionsState === 'error'
          ? nameOptionsError ?? 'Unable to load teaching name options.'
          : 'No teaching-name options are available for this programme and reporting period.'
  const addTeachingTitle =
    nameOptionsState === 'ready'
      ? 'Add a teaching event from the selected source.'
      : nameOptionsUnavailableMessage
  const sourceReselectionMessage =
    'The original Name of Teaching is no longer active or available. Select a currently active source before saving.'
  const disabledSubmitTitle = poolSourceRequiresReselection
    ? sourceReselectionMessage
    : nameOptionsState === 'ready'
      ? 'Select a currently active source before saving.'
      : addTeachingTitle
  const selectedPeriodDateError = useMemo(() => {
    if (!formState.eventDate || !selectedPeriod) {
      return null
    }
    return isDateWithinPeriod(formState.eventDate, selectedPeriod.startDate, selectedPeriod.endDate)
      ? null
      : 'Event date must be within the selected reporting period.'
  }, [formState.eventDate, selectedPeriod])
  const selectedPoolStartTimeError = selectedSourceOption?.teachingNameId
    ? poolStartTimeValidationError(formState.startTime)
    : null
  const selectedPoolEndTime = selectedSourceOption?.teachingNameId
    && selectedSourceOption.durationIsMapped
    && !selectedPoolStartTimeError
    ? serverComputedPoolEndTime(
        formState.startTime,
        selectedSourceOption.durationHours,
      )
    : null

  const toggleSelected = (id: string) => {
    setSelectedIds((previous) => {
      const next = new Set(previous)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
    setSubmitMessage(null)
    setSubmitState('idle')
  }

  const selectedRows = useMemo(() => {
    return visibleEvents.filter((event) => selectedIds.has(event.id))
  }, [selectedIds, visibleEvents])
  const selectedCount = selectedRows.length
  const selectedWithAttendanceCount = selectedRows.filter((event) => event.hasAttendance).length
  const allSelectedHaveAttendance = selectedCount > 0 && selectedWithAttendanceCount === selectedCount
  const anySelectedHaveAttendance = selectedWithAttendanceCount > 0
  const deletableRows = selectedRows.filter((event) => !event.hasAttendance)
  const canEditSelected = selectedCount === 1 && !selectedRows[0]?.hasAttendance
  const canDuplicateSelected = selectedCount === 1
  const canDeleteSelected = selectedCount > 0 && !allSelectedHaveAttendance
  const showEditButton = canEditSelected
  const showDeleteButton = canDeleteSelected
  const showDuplicateButton = canDuplicateSelected
  const singleSelectedEvent = useMemo(() => {
    if (selectedCount !== 1) {
      return null
    }
    return selectedRows[0] ?? null
  }, [selectedCount, selectedRows])
  const selectedActionMessage = useMemo(() => {
    if (selectedCount === 0) {
      return null
    }
    if (selectedCount === 1) {
      if (singleSelectedEvent?.hasAttendance) {
        return 'Editing and deleting are disabled because attendance has been submitted for this event.'
      }
      return null
    }
    if (allSelectedHaveAttendance) {
      return 'Editing and deleting are disabled because attendance has been submitted for the selected events.'
    }
    if (anySelectedHaveAttendance) {
      return 'Some selected events cannot be edited or deleted because attendance has been submitted.'
    }
    return null
  }, [selectedCount, singleSelectedEvent, allSelectedHaveAttendance, anySelectedHaveAttendance])
  const showSelectionActionMessage = submitState === 'idle' && submitMessage === null && selectedActionMessage !== null
  const resetForm = () => {
    setFormState(INITIAL_FORM)
    setFormErrors({})
    setSubmitState('idle')
    setSubmitMessage(null)
    setSourceEvent(null)
  }

  const closeDrawer = () => {
    setDrawerOpen(false)
    setDrawerMode('create')
    setPendingSourceProgrammeContextKey(null)
    resetForm()
  }

  const openDrawer = () => {
    if (!canAddTeaching) {
      setSubmitState('error')
      setSubmitMessage(addTeachingTitle)
      return
    }
    setDrawerMode('create')
    resetForm()
    setDrawerOpen(true)
  }

  const clearSelection = () => {
    setSelectedIds(() => new Set())
    setSubmitMessage(null)
    setSubmitState('idle')
  }

  const prepareEventSourceProgramme = (event: SecretaryTeachingEvent): boolean => {
    const programmeContext = resolveSecretaryEventProgrammeContext(event)
    if (programmeContext.kind === 'not_pool_backed') {
      return true
    }
    if (programmeContext.kind === 'missing_pool_programme') {
      setSubmitState('error')
      setSubmitMessage('This pool-backed teaching event has no source programme context. Refresh the schedule before editing or duplicating it.')
      return false
    }
    if (teachingNameProgrammesLoading || !teachingNameProgrammesLoaded) {
      setSubmitState('error')
      setSubmitMessage('Authorised Teaching Name programmes are still loading. Try again when they are available.')
      return false
    }
    if (!teachingNameProgrammes.includes(programmeContext.programmeCode)) {
      setSubmitState('error')
      setSubmitMessage('This teaching event belongs to a Teaching Name programme you are not currently authorised to manage.')
      return false
    }
    if (selectedTeachingNameProgrammeCode !== programmeContext.programmeCode) {
      preservedEventSourceProgrammeRef.current = programmeContext.programmeCode
      setPendingSourceProgrammeContextKey(
        selectedPeriod ? `${selectedPeriod.id}:${programmeContext.programmeCode}` : null,
      )
      setSelectedTeachingNameProgrammeCode(programmeContext.programmeCode)
    }
    return true
  }

  const handleOpenDuplicate = () => {
    if (!singleSelectedEvent) {
      return
    }
    if (!prepareEventSourceProgramme(singleSelectedEvent)) {
      return
    }
    setSourceEvent(singleSelectedEvent)
    setDrawerMode('duplicate')
    setFormState({
      sourceKey: sourceKeyForSecretaryTeachingEvent(singleSelectedEvent),
      eventDate: singleSelectedEvent.eventDate,
      startTime: toTimeInputValue(singleSelectedEvent.startTime),
      cmePointsAwarded: singleSelectedEvent.cmePointsAwarded,
      smcEventCode: singleSelectedEvent.smcEventCode ?? '',
    })
    setFormErrors({})
    setSubmitState('idle')
    setSubmitMessage(null)
    setDrawerOpen(true)
  }

  const handleOpenEdit = (eventToEdit?: SecretaryTeachingEvent) => {
    const targetEvent = eventToEdit ?? singleSelectedEvent
    if (!targetEvent) {
      return
    }
    if (targetEvent.hasAttendance) {
      setSubmitState('error')
      setSubmitMessage('Editing and deleting are disabled because attendance has been submitted for this event.')
      return
    }
    if (!prepareEventSourceProgramme(targetEvent)) {
      return
    }
    setSourceEvent(targetEvent)
    setDrawerMode('edit')
    setFormState({
      sourceKey: sourceKeyForSecretaryTeachingEvent(targetEvent),
      eventDate: targetEvent.eventDate,
      startTime: toTimeInputValue(targetEvent.startTime),
      cmePointsAwarded: targetEvent.cmePointsAwarded,
      smcEventCode: targetEvent.smcEventCode ?? '',
    })
    setFormErrors({})
    setSubmitState('idle')
    setSubmitMessage(null)
    setDrawerOpen(true)
  }

  const handleDeleteSelected = async () => {
    if (allSelectedHaveAttendance) {
      setSubmitState('error')
      setSubmitMessage(`${selectedCount} teaching event(s) cannot be deleted because attendance exists.`)
      return
    }

    const idsToDelete = deletableRows.map((event) => event.id)
    const attendanceProtectedIds = selectedRows.filter((event) => event.hasAttendance).map((event) => event.id)
    const attendanceProtectedCount = attendanceProtectedIds.length

    if (idsToDelete.length === 0) {
      setSubmitState('error')
      setSubmitMessage(
        `${attendanceProtectedCount} teaching event(s) cannot be deleted because attendance exists.`,
      )
      return
    }
    setSubmitState('submitting')
    setSubmitMessage(null)
    const requestedOptionsContextKey = nameOptionsContextKeyRef.current

    const deleteAttempts = await Promise.allSettled(idsToDelete.map((id) => deleteSecretaryTeachingEvent(id)))
    if (nameOptionsContextKeyRef.current !== requestedOptionsContextKey) {
      return
    }
    const deletedIds: string[] = []
    const errorIds: string[] = []
    for (let index = 0; index < deleteAttempts.length; index++) {
      const id = idsToDelete[index]
      const result = deleteAttempts[index]
      if (result && result.status === 'fulfilled' && id) {
        deletedIds.push(id)
      } else if (id) {
        errorIds.push(id)
      }
    }

    if (deletedIds.length > 0) {
      if (supportsEventListEndpoint) {
        const refreshed = await loadEvents()
        if (nameOptionsContextKeyRef.current !== requestedOptionsContextKey) {
          return
        }
        setEvents(refreshed)
      } else {
        setRecentCreatedEvents((previous) => previous.filter((event) => !idsToDelete.includes(event.id)))
      }
    }
    if (errorIds.length === 0) {
      if (attendanceProtectedCount > 0) {
        setSelectedIds(new Set(attendanceProtectedIds))
        setSubmitState('success')
        setSubmitMessage(
          `Deleted ${deletedIds.length} teaching event(s). ${attendanceProtectedCount} could not be deleted because attendance exists.`,
        )
        return
      }
      setSelectedIds(() => new Set())
      setSubmitState('success')
      setSubmitMessage(`Deleted ${deletedIds.length} teaching event(s).`)
      return
    }

    const failedDelete = deleteAttempts.find((result) => result.status === 'rejected')
    const firstFailure = failedDelete && failedDelete.status === 'rejected' ? failedDelete.reason : null
    const nonDeletableCount = attendanceProtectedCount + errorIds.length
    const allFailureIds = [...attendanceProtectedIds, ...errorIds]
    setSelectedIds(new Set(allFailureIds))
    setSubmitState('error')
    if (attendanceProtectedCount > 0) {
      setSubmitMessage(
        deletedIds.length > 0
          ? `Deleted ${deletedIds.length} teaching event(s). ${nonDeletableCount} could not be deleted because attendance exists.`
          : `${nonDeletableCount} teaching event(s) could not be deleted because attendance exists.`,
      )
    } else if (failedDelete) {
      setSubmitMessage(
        firstFailure instanceof ApiRequestError
          ? normaliseApiError(firstFailure, 'create')
          : 'Unable to delete teaching event right now. Please try again.',
      )
    } else {
      setSubmitMessage('Unable to delete teaching event right now. Please try again.')
    }
  }

  const handleCreate = async () => {
    if (drawerMode === 'edit' && !sourceEvent) {
      setSubmitState('error')
      setSubmitMessage('Please select an event to edit first.')
      return
    }
    if (drawerMode === 'edit' && !sourceEvent?.id) {
      setSubmitState('error')
      setSubmitMessage('Please select an event to edit first.')
      return
    }
    if (drawerMode === 'edit' && sourceEvent?.hasAttendance) {
      setSubmitState('error')
      setSubmitMessage('Editing and deleting are disabled because attendance has been submitted for this event.')
      return
    }
    if (drawerMode === 'duplicate' && sourceEvent) {
      const sourceKey = sourceKeyForSecretaryTeachingEvent(sourceEvent)
      const targetSourceKey = formState.sourceKey
      const sourceStartTime = toTimeInputValue(sourceEvent.startTime)
      const targetStartTime = formState.startTime
      const sourceDate = sourceEvent.eventDate
      const sourceSame =
        sourceKey === targetSourceKey &&
        sourceDate === formState.eventDate &&
        sourceStartTime === targetStartTime
      if (sourceSame && sourceOptionForSave) {
        setSubmitState('error')
        setSubmitMessage('Duplicate has no changes. Update date/time or another field before saving.')
        return
      }
    }
    const nextErrors: Partial<Record<keyof TeachingFormState, string>> = {}
    if (!formState.sourceKey) {
      nextErrors.sourceKey = poolSourceRequiresReselection
        ? sourceReselectionMessage
        : 'Name of Teaching is required.'
    } else if (!sourceOptionForSave) {
      nextErrors.sourceKey = poolSourceRequiresReselection
        ? sourceReselectionMessage
        : 'Select a currently active Name of Teaching from the approved pool or global sources.'
    }
    if (!selectedPeriod) {
      nextErrors.eventDate = 'An active reporting period is required.'
    } else if (!formState.eventDate) {
      nextErrors.eventDate = 'Event date is required.'
    } else if (!isDateWithinPeriod(formState.eventDate, selectedPeriod.startDate, selectedPeriod.endDate)) {
      nextErrors.eventDate = 'Event date must be within the selected reporting period.'
    }
    if (!formState.startTime) {
      nextErrors.startTime = 'Start time is required.'
    } else if (selectedPoolStartTimeError) {
      nextErrors.startTime = selectedPoolStartTimeError
    }
    setFormErrors(nextErrors)
    if (Object.keys(nextErrors).length > 0) {
      setSubmitState('error')
      setSubmitMessage('Please complete required fields before creating the teaching event.')
      return
    }

    setSubmitState('submitting')
    setSubmitMessage(null)
    const requestedOptionsContextKey = nameOptionsContextKeyRef.current
    const payload = {
      teachingNameId: sourceOptionForSave?.teachingNameId,
      globalSessionTypeId: sourceOptionForSave?.globalSessionTypeId,
      eventDate: formState.eventDate,
      startTime: formState.startTime,
      cmePointsAwarded: formState.cmePointsAwarded,
      smcEventCode: formState.cmePointsAwarded ? formState.smcEventCode.trim() || undefined : undefined,
    }
    try {
      const savedEvent =
        drawerMode === 'duplicate' && sourceEvent
          ? await duplicateSecretaryTeachingEvent({
            sourceEventId: sourceEvent.id,
            eventDate: formState.eventDate,
            startTime: formState.startTime,
            teachingNameId:
              formState.sourceKey !== sourceKeyForSecretaryTeachingEvent(sourceEvent)
                ? sourceOptionForSave?.teachingNameId
                : undefined,
            globalSessionTypeId:
              formState.sourceKey !== sourceKeyForSecretaryTeachingEvent(sourceEvent)
                ? sourceOptionForSave?.globalSessionTypeId
                : undefined,
          })
          : drawerMode === 'edit' && sourceEvent
            ? await updateSecretaryTeachingEvent(sourceEvent.id, payload)
            : await createSecretaryTeachingEvent(payload)

      if (nameOptionsContextKeyRef.current !== requestedOptionsContextKey) {
        return
      }

      if (supportsEventListEndpoint) {
        const refreshed = await loadEvents()
        if (nameOptionsContextKeyRef.current !== requestedOptionsContextKey) {
          return
        }
        if (refreshed.some((event) => event.id === savedEvent.id)) {
          setEvents(refreshed)
        } else {
          setEvents([savedEvent, ...refreshed.filter((event) => event.id !== savedEvent.id)])
        }
      } else {
        setRecentCreatedEvents((previous) => [savedEvent, ...previous])
      }

      setSubmitState('success')
      setSubmitMessage(
        drawerMode === 'edit'
          ? 'Teaching event updated successfully.'
          : drawerMode === 'duplicate'
            ? 'Teaching event duplicated successfully.'
            : 'Teaching event created successfully.',
      )
      setSelectedIds(new Set())
      closeDrawer()
    } catch (error) {
      if (nameOptionsContextKeyRef.current !== requestedOptionsContextKey) {
        return
      }
      const message =
        error instanceof ApiRequestError
          ? normaliseApiError(error, 'create')
          : 'Unable to save teaching event right now.'
      setSubmitState('error')
      setSubmitMessage(message)
    }
  }

  const handleExport = () => {
    setExportError(null)
    try {
      downloadSecretaryTeachingScheduleCsv(buildEventCsv(visibleEvents))
    } catch {
      setExportError(SECRETARY_TEACHING_EVENT_EXPORT_ERROR)
    }
  }

  return (
    <div className="page secretary-page">
      <section className="secretary-schedule-header" aria-label="Teaching schedule controls">
        <div className="secretary-header-main">
          <div className="hero-title-block">
            <span className="hero-accent" />
            <div>
              <h1 className="hero-title">Teaching Schedule</h1>
              <p className="hero-subtitle">{frontendConfig.demoSecretaryScopeLabel}</p>
            </div>
          </div>

          <div className="secretary-period-row">
            {reportingPeriodsLoading ? <span className="inline-muted">Loading reporting periods...</span> : null}
            {!reportingPeriodsLoading && reportingPeriods.length > 0 ? (
              <div className="filter-row">
                {reportingPeriods.map((period) => {
                  const active = isEffectivelyActiveReportingPeriod(period)
                  return (
                    <button
                      key={period.id}
                      type="button"
                      className={`filter-chip ${period.id === selectedPeriod?.id ? 'active' : ''}`}
                      onClick={() => setReportingPeriodId(period.id)}
                      disabled={!active}
                      title={active ? reportingPeriodDisplayStatus(period) : 'This reporting period is inactive.'}
                    >
                      {period.label}
                    </button>
                  )
                })}
              </div>
            ) : null}
            {reportingPeriodsError ? <p className="upload-validation-text">{reportingPeriodsError}</p> : null}
            {!reportingPeriodsLoading && !reportingPeriodsError && !selectedPeriod ? (
              <p className="upload-validation-text">Select an active reporting period.</p>
            ) : null}
          </div>
          <div className="secretary-programme-row">
            {teachingNameProgrammesLoading ? (
              <span className="inline-muted">Loading authorised Teaching Name programmes...</span>
            ) : null}
            {teachingNameProgrammesError ? (
              <span className="upload-validation-text">{teachingNameProgrammesError}</span>
            ) : null}
            {!teachingNameProgrammesLoading && !teachingNameProgrammesError && teachingNameProgrammes.length === 1 ? (
              <span className="scope-chip">Teaching Name programme: {teachingNameProgrammes[0]}</span>
            ) : null}
            {!teachingNameProgrammesLoading && !teachingNameProgrammesError && teachingNameProgrammes.length > 1 ? (
              <label className="secretary-teaching-names-select">
                <span>Teaching Name programme</span>
                <select
                  value={selectedTeachingNameProgrammeCode}
                  onChange={(event) => setSelectedTeachingNameProgrammeCode(event.target.value)}
                >
                  {teachingNameProgrammes.map((programmeCode) => (
                    <option key={programmeCode} value={programmeCode}>{programmeCode}</option>
                  ))}
                </select>
              </label>
            ) : null}
            {!teachingNameProgrammesLoading && !teachingNameProgrammesError && teachingNameProgrammes.length === 0 ? (
              <span className="inline-muted">No authorised Teaching Name pool is available. Global session types remain separate.</span>
            ) : null}
          </div>
        </div>

        <div className="secretary-action-cluster">
          <div className="secretary-scope-row">
            <span className="scope-chip">
              <IconCalendar size={12} />
              {selectedTeachingNameProgrammeCode
                ? `Teaching Name programme: ${selectedTeachingNameProgrammeCode}`
                : `Scoped to ${frontendConfig.demoSecretaryScopeLabel}`}
            </span>
          </div>
          <div className="secretary-action-row">
            <div className="secretary-button-row">
              <button
                type="button"
                className="button button-secondary"
                onClick={handleExport}
                disabled={visibleEvents.length === 0}
              >
                <IconDownload size={14} />
                Export
              </button>
              <button
                type="button"
                className="button button-primary"
                onClick={openDrawer}
                disabled={!canAddTeaching}
                title={addTeachingTitle}
              >
                <IconPlus size={14} />
                Add Teaching
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="card secretary-table-card">
        <div className="section-header secretary-table-header">
          <h2>Teaching schedule</h2>
          {selectedCount > 0 ? (
            <span className="inline-muted secretary-selection-count">{selectedCount} selected</span>
          ) : (
            <span className="inline-muted secretary-selection-helper">Select rows to review details</span>
          )}
          <p className="secretary-edit-preface">Only teachings with no submitted attendance can be edited.</p>
          {selectedCount > 0 ? (
            <div className="secretary-selection-toolbar">
              {showEditButton ? (
                <button
                  type="button"
                  className="button button-ghost secretary-mobile-action-button secretary-toolbar-edit-button"
                  onClick={() => handleOpenEdit()}
                  title="Edit selected teaching event."
                >
                  Edit
                </button>
              ) : null}
              {showDuplicateButton ? (
                <button
                  type="button"
                  className="button button-secondary secretary-mobile-action-button"
                  onClick={handleOpenDuplicate}
                  title={
                    selectedCount === 1
                      ? 'Create a duplicate of the selected teaching event.'
                      : 'Select exactly one row to duplicate.'
                  }
                >
                  Duplicate
                </button>
              ) : null}
              {showDeleteButton ? (
                <button
                  type="button"
                  className="button button-ghost danger secretary-mobile-action-button"
                  onClick={() => void handleDeleteSelected()}
                  title="Delete selected teaching event(s)."
                >
                  Delete
                </button>
              ) : null}
              <button
                type="button"
                className="button button-ghost secretary-mobile-action-button"
                onClick={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  clearSelection()
                }}
              >
                Clear
              </button>
            </div>
          ) : null}
        </div>

        {showSelectionActionMessage ? (
          <div className="inline-callout callout-warning secretary-inline-callout secretary-selection-warning">
            <span>{selectedActionMessage}</span>
          </div>
        ) : null}

        {submitState === 'success' && submitMessage ? (
          <div className="inline-callout callout-success secretary-inline-callout">
            <span>{submitMessage}</span>
          </div>
        ) : null}
        {eventsError ? (
          <div className="inline-callout callout-warning secretary-inline-callout">
            <span>{eventsError}</span>
          </div>
        ) : null}
        {exportError ? (
          <div className="inline-callout callout-error secretary-inline-callout" role="alert">
            <span>{exportError}</span>
          </div>
        ) : null}

        <div className="table-wrap secretary-table-wrap">
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th className="col-check" />
                  <th>Teaching Type</th>
                  <th>Name of Teaching</th>
                  <th>Source programme</th>
                  <th>Date</th>
                  <th>Start Time</th>
                  <th>Duration</th>
                  <th>CME Pts</th>
                  <th>SMC Event</th>
                  <th>Created By</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {eventsLoading ? (
                  <tr>
                    <td colSpan={11}>Loading teaching events...</td>
                  </tr>
                ) : visibleEvents.length === 0 ? (
                  <tr>
                    <td colSpan={11}>No teaching events yet.</td>
                  </tr>
                ) : (
                  visibleEvents.map((event) => {
                    const selected = selectedIds.has(event.id)
                    const teachingType = event.sessionTypeName ?? '-'
                    return (
                      <tr
                        key={event.id}
                        className={`table-clickable-row ${selected ? 'secretary-row-selected' : ''}`}
                        onClick={() => toggleSelected(event.id)}
                      >
                        <td>
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => toggleSelected(event.id)}
                            onClick={(clickEvent) => clickEvent.stopPropagation()}
                            aria-label={`Select ${event.teachingName}`}
                          />
                        </td>
                        <td>
                          <span className="secretary-type-pill">{teachingType}</span>
                        </td>
                        <td className="secretary-teaching-name">{event.teachingName}</td>
                        <td className="mono">{sourceProgrammeDisplay(event)}</td>
                        <td className="mono">{formatDate(event.eventDate)}</td>
                        <td className="mono">{formatTime(event.startTime)}</td>
                        <td>{formatDuration(event.durationHours)}</td>
                        <td>
                          <span
                            className={`status-badge ${
                              event.cmePointsAwarded ? 'status-badge-success' : 'status-badge-neutral'
                            }`}
                          >
                            {event.cmePointsAwarded ? 'Yes' : 'No'}
                          </span>
                        </td>
                        <td className="mono">{event.smcEventCode ?? '-'}</td>
                        <td>{teachingEventCreatedByDisplay(event.createdByRole)}</td>
                        <td>{formatDate(event.createdAt)}</td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="secretary-event-card-list" aria-label="Teaching schedule cards">
          {eventsLoading ? (
            <div className="mobile-record-card secretary-event-empty-card">Loading teaching events...</div>
          ) : visibleEvents.length === 0 ? (
            <div className="mobile-record-card secretary-event-empty-card">No teaching events yet.</div>
          ) : (
            visibleEvents.map((event) => {
              const selected = selectedIds.has(event.id)
              const teachingType = event.sessionTypeName ?? '-'
              const postingLabel = event.postingCode || frontendConfig.demoSecretaryScopeLabel
              const sourceLabel = event.isAdhoc ? 'Ad-hoc' : 'Scheduled'
              const sourceProgrammeLabel = sourceProgrammeDisplay(event)

              return (
                <article
                  key={event.id}
                  className={`mobile-record-card secretary-event-card ${selected ? 'is-selected' : ''} ${
                    event.hasAttendance ? 'has-attendance' : ''
                  }`}
                  aria-label={event.teachingName}
                >
                  <span className="secretary-event-card-header">
                    <span className="secretary-event-card-title safe-wrap">{event.teachingName}</span>
                    <span className="secretary-event-card-badges">
                      <span
                        className={`status-badge ${
                          event.cmePointsAwarded ? 'status-badge-success' : 'status-badge-neutral'
                        }`}
                      >
                        {event.cmePointsAwarded ? 'CME Yes' : 'CME No'}
                      </span>
                    </span>
                  </span>
                  <span className="secretary-event-card-meta">
                    <span className="secretary-event-card-line mono">
                      {formatCompactDate(event.eventDate)} · {formatTime(event.startTime)} ·{' '}
                      {formatDuration(event.durationHours)}
                    </span>
                    {teachingType !== '-' ? (
                      <span className="secretary-event-card-line safe-wrap">{teachingType}</span>
                    ) : null}
                    <span className="secretary-event-card-line">
                      {postingLabel} · {sourceLabel} · Source {sourceProgrammeLabel}
                      {' | '}
                      {teachingEventCreatedByDisplay(event.createdByRole)}
                      {event.hasAttendance ? ' · Attendance submitted' : ''}
                      {event.smcEventCode ? ` · SMC ${event.smcEventCode}` : ''}
                    </span>
                  </span>
                  <span className={`secretary-card-action-row ${event.hasAttendance ? 'is-single' : ''}`}>
                    <button
                      type="button"
                      className="secretary-mobile-action-button secretary-card-select-indicator"
                      onClick={() => toggleSelected(event.id)}
                      aria-pressed={selected}
                      aria-label={`${selected ? 'Deselect' : 'Select'} ${event.teachingName}`}
                    >
                      {selected ? 'Selected' : 'Select'}
                    </button>
                    {!event.hasAttendance ? (
                      <button
                        type="button"
                        className="button button-secondary secretary-mobile-action-button secretary-card-edit-button"
                        onClick={(clickEvent) => {
                          clickEvent.stopPropagation()
                          handleOpenEdit(event)
                        }}
                      >
                        Edit
                      </button>
                    ) : null}
                  </span>
                </article>
              )
            })
          )}
        </div>
      </section>

      <DetailDrawer
        title={drawerMode === 'duplicate' ? 'Duplicate Teaching' : drawerMode === 'edit' ? 'Edit Teaching' : 'Add Teaching'}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
          <button type="button" className="button button-ghost" onClick={closeDrawer}>
              Cancel
            </button>
              <button
                type="button"
                className="button button-primary"
                onClick={() => void handleCreate()}
                disabled={
                  submitState === 'submitting' ||
                  !selectedPeriod ||
                  !canSubmitTeaching ||
                  !!selectedPeriodDateError ||
                  (drawerMode === 'edit' && (!sourceEvent || sourceEvent.hasAttendance))
                }
                title={
                  !selectedPeriod
                    ? 'Select an active reporting period before creating a teaching event.'
                    : !canSubmitTeaching
                      ? disabledSubmitTitle
                      : selectedPeriodDateError
                        ? 'Event date must be within the selected reporting period.'
                        : drawerMode === 'edit' && sourceEvent?.hasAttendance
                          ? 'Editing and deleting are disabled because attendance has been submitted for this event.'
                          : drawerMode === 'edit'
                            ? 'Save changes to the selected teaching event.'
                            : drawerMode === 'duplicate'
                              ? 'Create a duplicate teaching event with the selected event values.'
                              : 'Create this teaching event.'
                }
              >
              {drawerMode === 'duplicate'
                ? 'Create duplicate'
                : drawerMode === 'edit'
                  ? 'Save changes'
                  : 'Create teaching'}
            </button>
          </>
        }
      >
        <div className="secretary-form-grid">
          {sourceEvent?.sourceProgrammeCode ? (
            <div className="secretary-teaching-names-form-context" aria-label="Event source programme">
              Source programme: {sourceEvent.sourceProgrammeCode}
            </div>
          ) : null}
          <label>
            Name of Teaching
            {nameOptionsState === 'ready' || retainedEventSourceOption ? (
              <select
                value={formState.sourceKey}
                onChange={(event) =>
                  setFormState((previous) => ({
                    ...previous,
                    sourceKey: event.target.value,
                  }))
                }
              >
                <option value="">Select Name of Teaching</option>
                {drawerSourceOptions.map((option) => (
                  <option key={option.sourceKey} value={option.sourceKey}>
                    {option.keyword}
                    {option.sourceKey === retainedInactiveGlobalOption?.sourceKey
                      ? ' (current inactive global source)'
                      : option.sourceKey === retainedPoolSourceOption?.sourceKey
                        ? ' (current event source)'
                      : ''}
                  </option>
                ))}
              </select>
            ) : (
              <>
                <input type="text" value={nameOptionsUnavailableMessage} readOnly disabled />
                <small>Names of Teaching must come from the approved Teaching Name pool or global session types.</small>
              </>
            )}
            {formErrors.sourceKey ? (
              <small className="upload-validation-text">{formErrors.sourceKey}</small>
            ) : null}
            {poolSourceRequiresReselection ? (
              <small className="upload-validation-text" role="alert">{sourceReselectionMessage}</small>
            ) : null}
            {nameOptionsError ? <small className="upload-validation-text">{nameOptionsError}</small> : null}
            {nameOptionsState === 'empty' ? (
              <small className="inline-muted">
                No teaching-name options were returned for this programme and reporting period.
              </small>
            ) : null}
          </label>

          {selectedSourceOption?.teachingNameId && !selectedSourceOption.durationIsMapped ? (
            <div className="inline-callout callout-neutral" role="status">
              This Teaching Name has not been mapped by the Programme PC. This event will use a temporary one-hour duration. Once mapped, the system will automatically update its duration and end time.
            </div>
          ) : selectedSourceOption ? (
            <div className="secretary-toggle-block" aria-live="polite">
              <span className="secretary-toggle-label">Duration</span>
              <strong>
                {selectedSourceOption.globalSessionTypeId
                  ? `${formatDuration(selectedSourceOption.durationHours)} (global source)`
                  : `${formatDuration(selectedSourceOption.durationHours)} (TTF mapping)`}
              </strong>
              <small>End time is calculated by the server.</small>
            </div>
          ) : null}

          <div className="secretary-form-row">
            <label>
              Event date
              <input
                type="date"
                value={formState.eventDate}
                min={selectedPeriod?.startDate}
                max={selectedPeriod?.endDate}
                onChange={(event) =>
                  setFormState((previous) => ({
                    ...previous,
                    eventDate: event.target.value,
                  }))
                }
              />
              {formErrors.eventDate ? <small className="upload-validation-text">{formErrors.eventDate}</small> : null}
              {!formErrors.eventDate && selectedPeriodDateError ? (
                <small className="upload-validation-text">{selectedPeriodDateError}</small>
              ) : null}
            </label>

            <label>
              Start time
              <select
                value={formState.startTime}
                onChange={(event) =>
                  setFormState((previous) => ({
                    ...previous,
                    startTime: event.target.value,
                  }))
                }
              >
                <option value="">Select start time</option>
                {START_TIME_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
              {formErrors.startTime ? <small className="upload-validation-text">{formErrors.startTime}</small> : null}
              {!formErrors.startTime && selectedPoolStartTimeError ? (
                <small className="upload-validation-text">{selectedPoolStartTimeError}</small>
              ) : null}
            </label>
          </div>

          {selectedSourceOption?.teachingNameId && selectedSourceOption.durationIsMapped ? (
            <div className="secretary-toggle-block" aria-live="polite">
              <span className="secretary-toggle-label">End time</span>
              <strong>{selectedPoolEndTime ?? 'Select a valid start time'}</strong>
              <small>Server-computed from the posting-specific TTF mapping.</small>
            </div>
          ) : null}

          {drawerMode === 'duplicate' ? (
            <div className="secretary-toggle-block">
              <span className="secretary-toggle-label">CME details</span>
              <strong>{sourceEvent?.cmePointsAwarded ? 'Copied from the original event' : 'No CME points on the original event'}</strong>
              <small>Duplicate requests preserve the server-authorised original event details.</small>
            </div>
          ) : (
            <div className="secretary-toggle-block">
              <span className="secretary-toggle-label">CME points awarded</span>
              <div className="secretary-yes-no">
                <button
                  type="button"
                  className={!formState.cmePointsAwarded ? 'is-active' : ''}
                  onClick={() =>
                    setFormState((previous) => ({
                      ...previous,
                      cmePointsAwarded: false,
                      smcEventCode: '',
                    }))
                  }
                >
                  No
                </button>
                <button
                  type="button"
                  className={formState.cmePointsAwarded ? 'is-active' : ''}
                  onClick={() =>
                    setFormState((previous) => ({
                      ...previous,
                      cmePointsAwarded: true,
                    }))
                  }
                >
                  Yes
                </button>
              </div>
            </div>
          )}

          {drawerMode !== 'duplicate' && formState.cmePointsAwarded ? (
            <label>
              SMC event code (optional)
              <input
                type="text"
                value={formState.smcEventCode}
                onChange={(event) =>
                  setFormState((previous) => ({
                    ...previous,
                    smcEventCode: event.target.value,
                  }))
                }
                placeholder="SMC-XXXX-001"
              />
              <small>Shown for CME-awarded sessions. Leave empty if not applicable.</small>
            </label>
          ) : null}

          {submitState === 'error' && submitMessage ? (
            <div className="inline-callout callout-error">
              <div className="secretary-error-stack">
                <span>{submitMessage}</span>
              </div>
            </div>
          ) : null}
        </div>
      </DetailDrawer>
    </div>
  )
}
